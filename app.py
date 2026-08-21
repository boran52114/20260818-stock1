import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import google.generativeai as genai

# ================= 網頁設定 =================
st.set_page_config(page_title="台股波段多空篩選器", page_icon="📈", layout="wide")

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
        elif "models/gemini-pro" in available_models: AI_MODEL_NAME = "models/gemini-pro"
        elif len(available_models) > 0: AI_MODEL_NAME = available_models[0]
            
        if AI_MODEL_NAME:
            model = genai.GenerativeModel(AI_MODEL_NAME)
            HAS_AI = True
    except Exception:
        HAS_AI = False

# ================= 輔助函式區 =================
@st.cache_data(ttl=86400)
def get_tw_stock_info():
    stock_dict = {}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"}
    try:
        res_twse = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", headers=headers, timeout=15)
        if res_twse.status_code == 200:
            for item in res_twse.json():
                code = item['Code']
                # ★ 優化：長度為4 (一般股票) 或 '00' 開頭 (ETF) 通通納入
                if len(code) == 4 or code.startswith('00'): 
                    stock_dict[code + '.TW'] = item['Name']
        
        res_tpex = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", headers=headers, timeout=15)
        if res_tpex.status_code == 200:
            for item in res_tpex.json():
                code = item['SecuritiesCompanyCode']
                if len(code) == 4 or code.startswith('00'): 
                    stock_dict[code + '.TWO'] = item['CompanyName']
    except Exception:
        pass 

    if len(stock_dict) < 100:
        # 備用名單也加入熱門 ETF
        stock_dict = {'2330.TW': '台積電', '2317.TW': '鴻海', '2454.TW': '聯發科', '0050.TW': '元大台灣50', '00878.TW': '國泰永續高股息', '00929.TW': '復華台灣科技優息'}
    return stock_dict

@st.cache_data(ttl=1800, show_spinner=False)
def download_stock_data(tickers):
    return yf.download(tickers, period="6mo", group_by="ticker", threads=True, progress=False)

def render_html_table(data_list):
    if not data_list: return "<div style='font-size: 16px; margin-top: 10px; color: #666;'>本日無符合條件標的（或無波動大於 3% 之標的）</div>"
    html = "<div style='overflow-x: auto;'><table style='width: 100%; min-width: 600px; border-collapse: collapse; font-size: 16px; text-align: center; font-family: sans-serif;'>"
    html += "<tr style='background-color: #f0f2f6; border-bottom: 2px solid #ddd;'><th style='padding: 10px;'>代號名稱</th><th style='padding: 10px;'>收盤價</th><th style='padding: 10px;'>漲跌幅</th><th style='padding: 10px;'>第一低</th><th style='padding: 10px;'>第二低</th><th style='padding: 10px;'>第一高</th><th style='padding: 10px;'>第二高</th></tr>"
    for row in data_list:
        color = "#ff4b4b" if "+" in row['漲跌幅'] else "#09ab3b" if "-" in row['漲跌幅'] else "black"
        html += f"<tr style='border-bottom: 1px solid #eee;'><td style='padding: 8px;'><b>{row['代號名稱']}</b></td><td style='padding: 8px;'>{row['收盤價']}</td><td style='padding: 8px; color: {color}; font-weight: bold;'>{row['漲跌幅']}</td><td style='padding: 8px;'>{row['第一低']}</td><td style='padding: 8px;'>{row['第二低']}</td><td style='padding: 8px;'>{row['第一高']}</td><td style='padding: 8px;'>{row['第二高']}</td></tr>"
    return html + "</table></div>"

# ================= 主程式區 =================
st.title("📈 台股波段多空篩選器 & AI 診斷")
st.write("條件：道氏理論波段轉折 + 突破/跌破 5MA + **當日實體動能 (漲跌幅達 3% 以上)**")

if 'calc_done' not in st.session_state:
    st.session_state['calc_done'] = False
    st.session_state['results'] = {}
    st.session_state['dates'] = []
    st.session_state['valid_count'] = 0

if st.button("🚀 開始篩選 (一鍵執行)", use_container_width=True, type="primary"):
    with st.spinner("正在獲取台股全市場代碼 (含個股與ETF)..."):
        stock_info = get_tw_stock_info()
        all_tickers = list(stock_info.keys())
        
    with st.spinner(f"正在下載或讀取 {len(all_tickers)} 檔標的歷史資料，請耐心等候..."):
        try:
            data = download_stock_data(all_tickers)
        except Exception:
            st.error("下載資料發生錯誤，請稍後再試。")
            st.stop()
            
    valid_dates = data.index.dropna().unique().sort_values()[-5:]
    date_strs = [d.strftime("%Y-%m-%d") for d in valid_dates]
    results_by_date = {d: {'up': [], 'down': []} for d in date_strs}
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    total_stocks = len(all_tickers)
    valid_stock_count = 0 
    
    for idx, ticker in enumerate(all_tickers):
        if idx % 50 == 0:
            progress_bar.progress((idx + 1) / total_stocks)
            status_text.text(f"正在運算中: {idx+1} / {total_stocks} 檔...")
            
        try:
            df_full = data[ticker].copy() if len(all_tickers) > 1 else data.copy()
            df_full = df_full.dropna()
            
            if isinstance(df_full.columns, pd.MultiIndex): df_full.columns = df_full.columns.droplevel(1)
            if len(df_full) < 15: continue
            valid_stock_count += 1 
                
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
                current_pos = df['Position'].iloc[0]
                current_high, current_low = df['High'].iloc[0], df['Low'].iloc[0]

                for i in range(1, len(df)):
                    pos, high, low = df['Position'].iloc[i], df['High'].iloc[i], df['Low'].iloc[i]
                    if pos == current_pos:
                        if high > current_high: current_high = high
                        if low < current_low: current_low = low
                    else:
                        waves.append({'type': 'above' if current_pos == 1 else 'below', 'high': current_high, 'low': current_low})
                        current_pos, current_high, current_low = pos, high, low

                waves.append({'type': 'above' if current_pos == 1 else 'below', 'high': current_high, 'low': current_low})

                today_pos, yest_pos = df['Position'].iloc[-1], df['Position'].iloc[-2]
                today_close, yest_close = df['Close'].iloc[-1], df['Close'].iloc[-2]
                
                # 計算真實漲跌幅數值
                pct_change_val = ((today_close - yest_close) / yest_close) * 100
                pct_str = f"+{pct_change_val:.2f}%" if pct_change_val > 0 else f"{pct_change_val:.2f}%"

                stock_code = ticker.split('.')[0]
                stock_name = stock_info.get(ticker, "")
                full_name = f"{stock_code} {stock_name}"
                
                # ★ 優化：加入 3% 漲跌幅過濾條件
                # 🟢 多方：向上突破 且 漲幅 >= 3%
                if today_pos == 1 and yest_pos == -1 and pct_change_val >= 3.0 and len(waves) >= 5:
                    low_2, high_2, low_1, high_1 = waves[-2]['low'], waves[-3]['high'], waves[-4]['low'], waves[-5]['high']
                    if high_2 >= high_1 and low_2 >= low_1:
                        results_by_date[date_str]['up'].append({
                            "代碼": ticker, "代號名稱": full_name, "收盤價": round(today_close, 2), "漲跌幅": pct_str,
                            "第一低": round(low_1, 2), "第二低": round(low_2, 2), "第一高": round(high_1, 2), "第二高": round(high_2, 2)
                        })

                # 🔴 空方：向下跌破 且 跌幅 <= -3%
                elif today_pos == -1 and yest_pos == 1 and pct_change_val <= -3.0 and len(waves) >= 5:
                    high_2, low_2, high_1, low_1 = waves[-2]['high'], waves[-3]['low'], waves[-4]['high'], waves[-5]['low']
                    if high_2 <= high_1 and low_2 <= low_1:
                        results_by_date[date_str]['down'].append({
                            "代碼": ticker, "代號名稱": full_name, "收盤價": round(today_close, 2), "漲跌幅": pct_str,
                            "第一低": round(low_1, 2), "第二低": round(low_2, 2), "第一高": round(high_1, 2), "第二高": round(high_2, 2)
                        })
        except Exception:
            continue
            
    st.session_state['results'] = results_by_date
    st.session_state['dates'] = date_strs[::-1]
    st.session_state['valid_count'] = valid_stock_count
    st.session_state['calc_done'] = True
    progress_bar.empty()
    status_text.empty()
    st.rerun()

# ================= 顯示結果與 AI 分析區 =================
if st.session_state.get('calc_done'):
    st.success(f"🎉 運算完成！(成功取得歷史資料: {st.session_state['valid_count']} 檔，含一般股票與ETF)")
    
    selected_date = st.radio("📅 選擇資料日期：", st.session_state['dates'], horizontal=True)
    current_data = st.session_state['results'][selected_date]
    
    tab1, tab2 = st.tabs(["🟢 多方突破 (漲幅>3%)", "🔴 空方跌破 (跌幅>3%)"])
    with tab1:
        st.markdown(render_html_table(current_data['up']), unsafe_allow_html=True)
    with tab2:
        st.markdown(render_html_table(current_data['down']), unsafe_allow_html=True)
    
    st.write("---")
    
    # ===== 🤖 AI 深度分析區 =====
    st.subheader("🤖 AI 專屬操盤助理")
    
    all_filtered_stocks = current_data['up'] + current_data['down']
    
    if not all_filtered_stocks:
        st.info("該日無符合條件的標的可供分析。")
    elif not HAS_AI:
        st.warning("⚠️ 系統未能成功連接 AI。可能是 API 鑰匙無效，或當前伺服器無可用模型。")
    else:
        st.caption(f"🧠 目前啟用的 AI 模型核心：`{AI_MODEL_NAME}`")
        stock_options = {row['代號名稱']: row for row in all_filtered_stocks}
        selected_stock_name = st.selectbox("請選擇一檔標的，讓 AI 進行深度診斷：", list(stock_options.keys()))
        
        if st.button(f"✨ 開始診斷 {selected_stock_name}", type="primary"):
            target_stock = stock_options[selected_stock_name]
            
            with st.spinner(f"AI 正在為您計算技術指標並生成報告中... (大約需要 10~15 秒)"):
                try:
                    ticker_obj = yf.Ticker(target_stock['代碼'])
                    df_tech = ticker_obj.history(period="3mo")
                    info = ticker_obj.info
                    
                    if not df_tech.empty and len(df_tech) > 26:
                        delta = df_tech['Close'].diff()
                        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                        rs = gain / loss
                        rsi_14 = 100 - (100 / (1 + rs))
                        current_rsi = round(rsi_14.iloc[-1], 2)
                        
                        exp1 = df_tech['Close'].ewm(span=12, adjust=False).mean()
                        exp2 = df_tech['Close'].ewm(span=26, adjust=False).mean()
                        macd = exp1 - exp2
                        signal = macd.ewm(span=9, adjust=False).mean()
                        macd_val = round(macd.iloc[-1], 2)
                        signal_val = round(signal.iloc[-1], 2)
                        
                        low_min = df_tech['Low'].rolling(window=9).min()
                        high_max = df_tech['High'].rolling(window=9).max()
                        rsv = 100 * ((df_tech['Close'] - low_min) / (high_max - low_min))
                        df_tech['K'] = rsv.ewm(com=2).mean()
                        df_tech['D'] = df_tech['K'].ewm(com=2).mean()
                        current_k = round(df_tech['K'].iloc[-1], 2)
                        current_d = round(df_tech['D'].iloc[-1], 2)
                        
                        tech_data_str = f"RSI(14): {current_rsi} | MACD值: {macd_val}, 訊號線: {signal_val} | K值: {current_k}, D值: {current_d}"
                    else:
                        tech_data_str = "歷史資料不足，無法計算進階指標"

                    pe_ratio = info.get('trailingPE', '無資料')
                    pb_ratio = info.get('priceToBook', '無資料')
                    volume = info.get('volume', '無資料')
                    
                    news_titles = "無最新新聞"
                    try:
                        news = ticker_obj.news
                        if news and isinstance(news, list):
                            safe_news = []
                            for n in news[:3]:
                                if isinstance(n, dict):
                                    title = n.get('title') or n.get('content', {}).get('title') or "無標題新聞"
                                    safe_news.append(f"- {title}")
                            if safe_news: news_titles = "\n".join(safe_news)
                    except Exception:
                        pass
                        
                    # ★ 優化：強力格式化 Prompt，封殺英文思考草稿，直接下令開頭格式
                    prompt = f"""請直接開始輸出繁體中文的診斷報告，你的回答【必須】以「### 1. 📊 籌碼與價量結構分析」這句話作為開頭第一行，絕對不可以包含任何英文思考過程、草稿或問候語。

                    【標的真實數據】
                    名稱：{selected_stock_name}
                    當前收盤價：{target_stock['收盤價']}
                    今日成交量：{volume}
                    波段支撐點（第一低點：{target_stock['第一低']}，第二低點：{target_stock['第二低']}）
                    波段壓力點（第一高點：{target_stock['第一高']}，第二高點：{target_stock['第二高']}）
                    本益比 (P/E)：{pe_ratio} / 股價淨值比 (P/B)：{pb_ratio}
                    今日真實技術指標：{tech_data_str}
                    近期新聞標題：\n{news_titles}

                    【排版與內容要求】：
                    ### 1. 📊 籌碼與價量結構分析
                    (請教導我如何從「今日成交量」與「價格突破波段高低點的力道」來推測主力籌碼是否安定。)
                    
                    ### 2. 📰 基本面與新聞事件解讀
                    (針對本益比與新聞，說明其對股價推升的實質幫助。若是ETF則說明其特性。)
                    
                    ### 3. 📈 精確技術指標健檢
                    (請明確使用我提供的 RSI, MACD, KD 數字，判斷目前狀態並教我這些指標現在代表的意義。)
                    
                    ### 4. 🎯 實戰交易計畫與邏輯教學
                    (請具體給出買入區間、停利點、停損點。並在每個點位後詳細說明「為什麼設定在這個價位？」，讓我學習交易知識。)
                    """
                    
                    response = model.generate_content(prompt)
                    
                    st.success("✨ 診斷完成！您的專屬操盤導師報告如下：")
                    st.markdown(response.text)
                    
                except Exception as e:
                    st.error(f"AI 診斷過程中發生未預期的錯誤。詳細原因：{e}")
