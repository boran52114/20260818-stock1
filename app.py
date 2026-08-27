import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import google.generativeai as genai
from datetime import datetime, timedelta

# ================= 網頁設定 =================
st.set_page_config(page_title="台股波段多空篩選器 V3", page_icon="📈", layout="wide")

# ================= 雲端資料庫設定 =================
GAS_CHIP_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTHRZ3lb6xhRTG9uINlzoiMjlSrqQExX9JoGeg5zI7OoPDk1dF5TUguC4Fq_Oge5ALSCHK-fBUGtrx7/pub?gid=0&single=true&output=csv"
GAS_WEB_APP_URL = "https://script.google.com/macros/s/AKfycbwnswqqpmrAA3CZI4V8vzsfN0X8PLL4_9Y47f6Csz3pMxyQW3iQteXKegrQnaWZmjL9/exec"
GAS_TRACKING_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTHRZ3lb6xhRTG9uINlzoiMjlSrqQExX9JoGeg5zI7OoPDk1dF5TUguC4Fq_Oge5ALSCHK-fBUGtrx7/pub?gid=1643943802&single=true&output=csv"

# ================= AI 設定與自動探測 =================
HAS_AI = False
AI_MODEL_NAME = ""

if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    try:
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        user_target = "models/gemma-4-31b-it"
        if user_target in available_models: AI_MODEL_NAME = user_target
        elif "models/gemini-1.5-pro" in available_models: AI_MODEL_NAME = "models/gemini-1.5-pro"
        elif "models/gemini-1.5-flash" in available_models: AI_MODEL_NAME = "models/gemini-1.5-flash"
        elif len(available_models) > 0: AI_MODEL_NAME = available_models[0]
        if AI_MODEL_NAME:
            model = genai.GenerativeModel(AI_MODEL_NAME)
            HAS_AI = True
    except: pass

# ================= 輔助函式區 =================
@st.cache_data(ttl=86400)
def get_tw_stock_info():
    stock_dict = {}
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res_twse = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", headers=headers, timeout=15)
        if res_twse.status_code == 200:
            for item in res_twse.json():
                code = item['Code']
                if len(code) == 4 or code.startswith('00'): stock_dict[code + '.TW'] = item['Name']
        res_tpex = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", headers=headers, timeout=15)
        if res_tpex.status_code == 200:
            for item in res_tpex.json():
                code = item['SecuritiesCompanyCode']
                if len(code) == 4 or code.startswith('00'): stock_dict[code + '.TWO'] = item['CompanyName']
    except: pass 
    if len(stock_dict) < 100: stock_dict = {'2330.TW': '台積電', '2317.TW': '鴻海', '2454.TW': '聯發科', '0050.TW': '元大台灣50'}
    return stock_dict

@st.cache_data(ttl=1800, show_spinner=False)
def download_stock_data(tickers):
    return yf.download(tickers, period="6mo", group_by="ticker", threads=True, progress=False)

@st.cache_data(ttl=3600, show_spinner=False)
def get_institutional_chips():
    try:
        df = pd.read_csv(GAS_CHIP_CSV_URL)
        df['證券代號'] = df['證券代號'].astype(str)
        return df
    except: return pd.DataFrame()

@st.cache_data(ttl=60, show_spinner=False) # 縮短快取時間，讓狀態更新更快反映
def get_tracking_data():
    try: return pd.read_csv(GAS_TRACKING_CSV_URL)
    except: return pd.DataFrame()

def extract_chip_value(row, keyword):
    for col in row.index:
        if keyword in col and '買賣超' in col:
            try: return int(str(row[col]).replace(',', '').strip()) // 1000 
            except: pass
    return 0

# ★ 寫入追蹤表 (包含籌碼快照)
def save_to_tracking_sheet(date_str, ticker, name, direction, entry_price, f_lots, t_lots, d_lots):
    payload = {
        "date": date_str, "ticker": ticker, "name": name, "direction": direction, 
        "entry_price": entry_price, "f_lots": f_lots, "t_lots": t_lots, "d_lots": d_lots
    }
    try: return requests.post(GAS_WEB_APP_URL, json=payload).status_code == 200
    except: return False

# ★ 更新狀態遙控器
def update_tracking_status(date_str, ticker, new_status):
    payload = {"action": "update_status", "date": date_str, "ticker": ticker, "new_status": new_status}
    try: return requests.post(GAS_WEB_APP_URL, json=payload).status_code == 200
    except: return False

def render_html_table(data_list):
    if not data_list: return "<div style='color: #666;'>本日無符合條件標的</div>"
    html = "<div style='overflow-x: auto;'><table style='width: 100%; border-collapse: collapse; font-size: 15px; text-align: center;'>"
    html += "<tr style='background-color: #f0f2f6; border-bottom: 2px solid #ddd;'><th style='padding: 8px;'>代號名稱</th><th style='padding: 8px;'>收盤價</th><th style='padding: 8px;'>漲跌幅</th><th style='padding: 8px;'>第一低</th><th style='padding: 8px;'>第二低</th><th style='padding: 8px;'>第一高</th><th style='padding: 8px;'>第二高</th></tr>"
    for row in data_list:
        color = "#ff4b4b" if "+" in row['漲跌幅'] else "#09ab3b" if "-" in row['漲跌幅'] else "black"
        html += f"<tr style='border-bottom: 1px solid #eee;'><td style='padding: 6px;'><b>{row['代號名稱']}</b></td><td>{row['收盤價']}</td><td style='color: {color}; font-weight: bold;'>{row['漲跌幅']}</td><td>{row['第一低']}</td><td>{row['第二低']}</td><td>{row['第一高']}</td><td>{row['第二高']}</td></tr>"
    return html + "</table></div>"

def render_tracking_table(data_list):
    if not data_list: return "<div style='color: #666;'>無追蹤中標的</div>"
    html = "<div style='overflow-x: auto;'><table style='width: 100%; border-collapse: collapse; font-size: 15px; text-align: center;'>"
    html += "<tr style='background-color: #f0f2f6; border-bottom: 2px solid #ddd;'><th style='padding: 8px;'>進場日期</th><th style='padding: 8px;'>股票名稱</th><th style='padding: 8px;'>方向</th><th style='padding: 8px;'>進場成本</th><th style='padding: 8px;'>最新報價</th><th style='padding: 8px;'>當前損益</th></tr>"
    for row in data_list:
        html += f"<tr style='border-bottom: 1px solid #eee;'><td style='padding: 6px;'>{row['進場日期']}</td><td><b>{row['股票名稱']}</b></td><td>{row['方向']}</td><td>{row['進場成本']}</td><td>{row['最新報價']}</td><td>{row['當前損益']}</td></tr>"
    return html + "</table></div>"

def calculate_kline_score(df_stock):
    if len(df_stock) < 5: return 30, "<li>資料不足，給予基礎分 (+30)</li>"
    score = 30
    details = ["<li><b>基礎動能</b>：符合波段轉折與 5MA 突破 (+30分)</li>"]
    O1, C1, V1 = df_stock['Open'].iloc[-1], df_stock['Close'].iloc[-1], df_stock['Volume'].iloc[-1]
    V2 = df_stock['Volume'].iloc[-2]
    vol_5ma = df_stock['Volume'].tail(5).mean()
    if V1 > vol_5ma * 1.5:
        score += 20; details.append("<li><b>量能爆發</b>：爆量上漲，主力介入 (+20分)</li>")
    elif V1 < V2 and C1 > O1:
        score -= 20; details.append("<li><span style='color:red;'><b>量價背離</b>：實體突破但量縮，防假突破 (-20分)</span></li>")
    return max(-100, min(100, score)), f"<ul>{''.join(details)}</ul>"

def generate_ai_report(prompt_text, score_val, score_html, df_tech, f_lots, t_lots, d_lots, show_chip_panel=True):
    try:
        response = model.generate_content(prompt_text)
        raw_output = response.text
        clean_output = raw_output[raw_output.find("### 1."):] if "### 1." in raw_output else raw_output
        
        st.success("✨ 診斷完成！已為您生成專屬戰情室報表：")
        st.write("---")
        
        col_left, col_right = st.columns([3, 7])
        with col_left:
            st.subheader("📊 客觀數據儀表板")
            score_title = f"🟢 評分：{score_val} 分" if score_val >= 60 else f"🟡 評分：{score_val} 分" if score_val >= 30 else f"🔴 評分：{score_val} 分"
            with st.expander(score_title, expanded=True): st.markdown(score_html, unsafe_allow_html=True)
            try:
                ma20 = df_tech['Close'].rolling(window=20).mean().iloc[-1]
                bias_20 = ((df_tech['Close'].iloc[-1] - ma20) / ma20) * 100
                temp_msg = f"**乖離率數值：{bias_20:.2f}%**\n\n> 💡 偏離 20MA 過大易拉回，靠近 0 則安全。"
                with st.expander("🌡️ 位階溫度計", expanded=False): st.markdown(temp_msg)
            except: pass
                
            if show_chip_panel:
                chip_details = [
                    "🏦 **【參考法人動向】**",
                    f"* 外資：{'🔴 買' if f_lots > 0 else '🟢 賣' if f_lots < 0 else '⚪ 平'} {f_lots} 張",
                    f"* 投信：{'🔴 買' if t_lots > 0 else '🟢 賣' if t_lots < 0 else '⚪ 平'} {t_lots} 張",
                    f"* 自營：{'🔴 買' if d_lots > 0 else '🟢 賣' if d_lots < 0 else '⚪ 平'} {d_lots} 張"
                ]
                with st.expander("💰 籌碼與雷達", expanded=True): st.markdown("\n".join(chip_details))

        with col_right:
            st.subheader("🤖 AI 操盤導師深度解析")
            st.markdown(clean_output)
    except Exception as e: st.error(f"AI 運算發生錯誤：{e}")

# ================= 側邊欄導航 =================
st.sidebar.title("🎛️ 系統導航")
page_mode = st.sidebar.radio("請選擇戰情室：", ["🎯 波段多空篩選器", "🛡️ 實戰持股保鑣", "🔍 戰術覆盤室"])
st.sidebar.write("---")
st.sidebar.caption("AI 狀態: " + ("✅ 已連線" if HAS_AI else "❌ 未連線"))
if HAS_AI: st.sidebar.caption(f"引擎: `{AI_MODEL_NAME}`")

# ================= 頁面一：波段多空篩選器 =================
if page_mode == "🎯 波段多空篩選器":
    st.title("🎯 波段多空篩選器")

    if 'calc_done' not in st.session_state: st.session_state['calc_done'] = False

    if st.button("🚀 開始篩選 (一鍵執行)", use_container_width=True, type="primary"):
        with st.spinner("正在下載全市場資料並運算中..."):
            stock_info = get_tw_stock_info()
            all_tickers = list(stock_info.keys())
            try: data = download_stock_data(all_tickers)
            except: st.error("資料下載失敗"); st.stop()
                
            valid_dates = data.index.dropna().unique().sort_values()[-5:]
            date_strs = [d.strftime("%Y-%m-%d") for d in valid_dates]
            results_by_date = {d: {'up': [], 'down': []} for d in date_strs}
            
            for ticker in all_tickers:
                try:
                    df_full = data[ticker].copy() if len(all_tickers) > 1 else data.copy()
                    df_full = df_full.dropna()
                    if isinstance(df_full.columns, pd.MultiIndex): df_full.columns = df_full.columns.droplevel(1)
                    if len(df_full) < 15: continue
                        
                    df_full['5MA'] = df_full['Close'].rolling(window=5).mean()
                    df_full = df_full.dropna()
                    df_full['Position'] = df_full.apply(lambda row: 1 if row['Close'] > row['5MA'] else -1, axis=1)
                    
                    for d_idx, target_date in enumerate(valid_dates):
                        date_str = date_strs[d_idx]
                        if target_date not in df_full.index: continue
                        loc = df_full.index.get_loc(target_date)
                        if isinstance(loc, slice) or isinstance(loc, pd.Series): loc = df_full.index.get_indexer([target_date])[0]
                        df = df_full.iloc[:loc+1]
                        if len(df) < 10: continue
                        
                        waves = []
                        current_pos, current_high, current_low = df['Position'].iloc[0], df['High'].iloc[0], df['Low'].iloc[0]
                        for i in range(1, len(df)):
                            pos, high, low = df['Position'].iloc[i], df['High'].iloc[i], df['Low'].iloc[i]
                            if pos == current_pos:
                                if high > current_high: current_high = high
                                if low < current_low: current_low = low
                            else:
                                waves.append({'high': current_high, 'low': current_low})
                                current_pos, current_high, current_low = pos, high, low
                        waves.append({'high': current_high, 'low': current_low})

                        today_pos, yest_pos = df['Position'].iloc[-1], df['Position'].iloc[-2]
                        today_close, yest_close = df['Close'].iloc[-1], df['Close'].iloc[-2]
                        pct_change = ((today_close - yest_close) / yest_close) * 100
                        full_name = f"{ticker.split('.')[0]} {stock_info.get(ticker, '')}"
                        
                        if today_pos == 1 and yest_pos == -1 and pct_change >= 3.0 and len(waves) >= 5:
                            low_2, high_2, low_1, high_1 = waves[-2]['low'], waves[-3]['high'], waves[-4]['low'], waves[-5]['high']
                            if high_2 >= high_1 and low_2 >= low_1:
                                results_by_date[date_str]['up'].append({"代碼": ticker, "代號名稱": full_name, "收盤價": round(today_close, 2), "漲跌幅": f"+{pct_change:.2f}%", "第一低": round(low_1, 2), "第二低": round(low_2, 2), "第一高": round(high_1, 2), "第二高": round(high_2, 2)})

                        elif today_pos == -1 and yest_pos == 1 and pct_change <= -3.0 and len(waves) >= 5:
                            high_2, low_2, high_1, low_1 = waves[-2]['high'], waves[-3]['low'], waves[-4]['high'], waves[-5]['low']
                            if high_2 <= high_1 and low_2 <= low_1:
                                results_by_date[date_str]['down'].append({"代碼": ticker, "代號名稱": full_name, "收盤價": round(today_close, 2), "漲跌幅": f"{pct_change:.2f}%", "第一低": round(low_1, 2), "第二低": round(low_2, 2), "第一高": round(high_1, 2), "第二高": round(high_2, 2)})
                except: continue
                
        st.session_state['results'] = results_by_date
        st.session_state['dates'] = date_strs[::-1]
        st.session_state['calc_done'] = True
        st.rerun()

    if st.session_state.get('calc_done'):
        selected_date = st.radio("📅 選擇資料日期：", st.session_state['dates'], horizontal=True)
        current_data = st.session_state['results'][selected_date]
        tab1, tab2 = st.tabs(["🟢 多方突破", "🔴 空方跌破"])
        with tab1: st.markdown(render_html_table(current_data['up']), unsafe_allow_html=True)
        with tab2: st.markdown(render_html_table(current_data['down']), unsafe_allow_html=True)
        
        st.write("---")
        st.subheader("🤖 AI 專屬操盤助理")
        all_filtered = current_data['up'] + current_data['down']
        
        if all_filtered and HAS_AI:
            stock_options = {row['代號名稱']: row for row in all_filtered}
            selected_stock_name = st.selectbox("請選擇標的：", list(stock_options.keys()))
            target = stock_options[selected_stock_name]
            direction_str = "🟢 多方突破" if target in current_data['up'] else "🔴 空方跌破"
            
            # 抓取今日籌碼供分析與存檔
            chip_df, f_lots, t_lots, d_lots = get_institutional_chips(), 0, 0, 0
            if not chip_df.empty:
                row_chip = chip_df[chip_df['證券代號'] == target['代碼'].split('.')[0]]
                if not row_chip.empty:
                    f_lots, t_lots, d_lots = extract_chip_value(row_chip.iloc[0], '外'), extract_chip_value(row_chip.iloc[0], '投信'), extract_chip_value(row_chip.iloc[0], '自營')

            col1, col2 = st.columns(2)
            if col1.button(f"✨ 診斷 {selected_stock_name}", type="primary", use_container_width=True):
                with st.spinner("AI 深度思考中..."):
                    df_tech = yf.Ticker(target['代碼']).history(period="3mo")
                    score_val, score_html = calculate_kline_score(df_tech)
                    prompt = f"""
                    你是一位精通台股的資深操盤導師。請寫一份極度詳細的繁體中文報告，並且內容要以引導股市新手需要，盡可能說明清楚，拒絕敷衍。
                    標的：{selected_stock_name} ({direction_str}) / 今日收盤：{target['收盤價']}
                    最新單日法人籌碼：外資 {f_lots}張, 投信 {t_lots}張, 自營 {d_lots}張
                    
                    ### 1. 📊 籌碼與K線結構深度解析
                    (結合今日「K線型態數據」與「最新單日法人籌碼」進行比對！推演主力意圖。)
                    ### 2. 📰 基本面與市場題材評估
                    ### 3. 📈 技術指標健檢與教學
                    ### 4. 🎯 實戰交易計畫 (附詳細邏輯)
                    (給出進場區間、停利、停損，並解釋背後均線與型態邏輯)
                    """
                    generate_ai_report(prompt, score_val, score_html, df_tech, f_lots, t_lots, d_lots)

            if col2.button(f"💾 寫入【戰績追蹤表】", use_container_width=True):
                with st.spinner("寫入中，同步記錄當日籌碼快照..."):
                    if save_to_tracking_sheet(selected_date, target['代碼'], target['代號名稱'], direction_str, target['收盤價'], f_lots, t_lots, d_lots):
                        st.success(f"✅ {target['代號名稱']} 已成功存入雲端！(包含突破日籌碼快照)")
                        get_tracking_data.clear() # 強制刷新快取
                    else: st.error("寫入失敗。")

# ================= 頁面二：實戰持股保鑣 =================
elif page_mode == "🛡️ 實戰持股保鑣":
    st.title("🛡️ 實戰持股保鑣 (即時風險控管)")
    
    with st.spinner("正在讀取追蹤清單與最新報價..."):
        tracking_df = get_tracking_data()
        
    if tracking_df.empty or '追蹤狀態' not in tracking_df.columns:
        st.warning("目前無追蹤標的或欄位設定有誤。")
    else:
        active_stocks = tracking_df[tracking_df['追蹤狀態'] == '👀 追蹤中']
        if active_stocks.empty:
            st.info("目前沒有監控中的標的。")
        else:
            tickers_to_fetch = active_stocks['股票代碼'].tolist()
            live_data = yf.download(tickers_to_fetch, period="1d", group_by="ticker", progress=False)
            
            display_list = []
            for _, row in active_stocks.iterrows():
                tkr = row['股票代碼']
                entry_p = float(row['進場收盤價'])
                try:
                    current_p = round(live_data[tkr]['Close'].iloc[-1], 2) if len(tickers_to_fetch)>1 else round(live_data['Close'].iloc[-1], 2)
                    ret_pct = ((current_p - entry_p) / entry_p) * 100
                    color = "red" if ret_pct > 0 else "green"
                    ret_str = f"<span style='color:{color}; font-weight:bold;'>{'+' if ret_pct>0 else ''}{ret_pct:.2f}%</span>"
                except: current_p, ret_str = "讀取中", "-"
                    
                display_list.append({"進場日期": row['選出日期'], "股票名稱": row['股票名稱'], "方向": row['多空方向'], "進場成本": entry_p, "最新報價": current_p, "當前損益": ret_str})
                
            st.markdown(render_tracking_table(display_list), unsafe_allow_html=True)
            st.write("---")
            
            target_name = st.selectbox("🛡️ 請選擇操作標的：", active_stocks['股票名稱'].tolist())
            
            # ★ 網頁遙控器按鈕設計
            col_b1, col_b2 = st.columns(2)
            do_defense = col_b1.button(f"🛡️ 呼叫保鑣檢驗 {target_name}", type="primary", use_container_width=True)
            if col_b2.button(f"✅ 停利/停損結案 (將 {target_name} 移出追蹤)", use_container_width=True):
                with st.spinner("正在通知雲端移除追蹤..."):
                    target_row = active_stocks[active_stocks['股票名稱'] == target_name].iloc[0]
                    if update_tracking_status(target_row['選出日期'], target_row['股票代碼'], "✅ 已結案"):
                        st.success("成功結案！標的已移至「戰術覆盤室」。")
                        get_tracking_data.clear()
                        st.rerun()
                    else:
                        st.error("結案失敗，請稍後再試。")

            if do_defense:
                with st.spinner("AI 正在解析「進場至今」的量價足跡..."):
                    target_row = active_stocks[active_stocks['股票名稱'] == target_name].iloc[0]
                    tkr = target_row['股票代碼']
                    df_tech = yf.Ticker(tkr).history(period="1mo")
                    
                    try:
                        entry_date = pd.to_datetime(target_row['選出日期']).tz_localize(None)
                        df_tech.index = df_tech.index.tz_localize(None)
                        df_post = df_tech[df_tech.index >= entry_date]
                        holding_days = len(df_post)
                        up_vol = df_post[df_post['Close'] > df_post['Open']]['Volume'].mean()
                        down_vol = df_post[df_post['Close'] < df_post['Open']]['Volume'].mean()
                        up_vol_str = f"{int(up_vol)} 張" if not pd.isna(up_vol) else "無上漲日"
                        down_vol_str = f"{int(down_vol)} 張" if not pd.isna(down_vol) else "無下跌日"
                    except: holding_days, up_vol_str, down_vol_str = 0, "無", "無"

                    prompt = f"""
                    你是一位極度重視風險控管的基金經理人。
                    持股：{target_name} ({target_row['多空方向']}) / 進場成本：{target_row['進場收盤價']} / 最新價：{df_tech['Close'].iloc[-1]:.2f}
                    
                    【進場後的真實量價足跡】
                    為了判斷進場這 {holding_days} 天以來主力是否偷跑，請透過以下量價數據推演：
                    - 上漲日平均成交量：{up_vol_str} (若大於下跌量，代表主力持續推升)
                    - 下跌日平均成交量：{down_vol_str} (若爆量，代表主力倒貨；若量縮，代表洗盤)
                    
                    ### 1. 📊 持股現況與量價推演
                    ### 2. 🛡️ 各種技術指標，例如macd、kd、乖離率與風險提示
                    ### 3. 🎯 防禦策略 (強制設定移動停利或停損)
                    ### 4. 💡 操盤手心法
                    """
                    generate_ai_report(prompt, calculate_kline_score(df_tech)[0], calculate_kline_score(df_tech)[1], df_tech, 0, 0, 0, show_chip_panel=False)

# ================= 頁面三：戰術覆盤室 =================
elif page_mode == "🔍 戰術覆盤室":
    st.title("🔍 戰術覆盤室 (歷史交易檢討)")
    
    with st.spinner("正在載入歷史戰績表..."):
        tracking_df = get_tracking_data()
        
    if tracking_df.empty: st.warning("資料庫無歷史紀錄。")
    else:
        # 只顯示已結案的，或讓使用者看全部
        st.dataframe(tracking_df, use_container_width=True)
        st.write("---")
        target_name = st.selectbox("🔍 選擇股票進行【AI 戰術覆盤】：", tracking_df['股票名稱'].tolist())
        
        if st.button(f"🔍 啟動歷史解剖：{target_name}", type="primary"):
            with st.spinner("AI 正在比對選出當天與後續的多K棒軌跡..."):
                target_row = tracking_df[tracking_df['股票名稱'] == target_name].iloc[0]
                tkr = target_row['股票代碼']
                df_tech = yf.Ticker(tkr).history(period="3mo")
                
                # 取得當初存檔的突破日籌碼快照
                snap_f = target_row.get('外資買賣超', 0)
                snap_t = target_row.get('投信買賣超', 0)
                snap_d = target_row.get('自營商買賣超', 0)
                
                kline_history_str = ""
                try:
                    entry_date = pd.to_datetime(target_row['選出日期']).tz_localize(None)
                    df_tech.index = df_tech.index.tz_localize(None)
                    df_post = df_tech[df_tech.index >= entry_date]
                    
                    # 整理連續 K 線資料供 AI 辨識組合型態
                    for idx, r in df_post.iterrows():
                        kline_history_str += f"- {idx.strftime('%m/%d')}: 開{r['Open']:.2f}, 高{r['High']:.2f}, 低{r['Low']:.2f}, 收{r['Close']:.2f}, 量{int(r['Volume'])}張\n"
                        
                except: kline_history_str = "無法取得連續 K 線資料"
                
                prompt = f"""
                你是一位嚴厲但專業的量化策略檢討導師。我們現在要進行事後覆盤。
                標的：{target_name} ({target_row['多空方向']}) 
                當初進場日：{target_row['選出日期']} / 當時收盤價：{target_row['進場收盤價']}
                
                【突破日籌碼快照】
                突破當天的三大法人動向為：外資 {snap_f}張, 投信 {snap_t}張, 自營 {snap_d}張。
                
                【進場後的連續 K 線變化】
                {kline_history_str}
                
                這是一次事後檢討。請針對這筆交易進行法醫解剖，並且嚴格教導：
                ### 1. 📊 多K棒連續型態與結合籌碼印證
                (這是最重要的教學段落！請分析進場後的這幾天，走出了什麼經典 K 棒組合型態？例如三連黑、晨星、吞噬等。並強制印證「當初突破日的籌碼快照」，如果當初法人有買，為何後來走弱？或為何走強？)
                ### 2. 🕵️‍♂️ 成功或失敗的核心原因
                ### 3. 🛡️ 應對的出場時機檢討
                (事後來看，最佳的停利點或停損點應該出現在哪一天的哪一根 K 棒？為什麼？)
                ### 4. 💡 策略進化總結
                (總結這次經驗，教導投資人未來看到類似訊號時，該如何避開陷阱或放大獲利？)
                """
                generate_ai_report(prompt, calculate_kline_score(df_tech)[0], calculate_kline_score(df_tech)[1], df_tech, snap_f, snap_t, snap_d)
