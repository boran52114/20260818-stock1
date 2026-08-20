import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import google.generativeai as genai

# ================= 網頁設定 =================
st.set_page_config(page_title="台股波段多空篩選器", page_icon="📈", layout="wide")

# ================= AI 設定 =================
# 嘗試從保險箱讀取鑰匙並設定 Gemini AI
HAS_AI = False
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    # 使用最新的 gemini-1.5-flash 模型，速度快且免費額度高
    model = genai.GenerativeModel('gemini-1.5-flash')
    HAS_AI = True

# ================= 輔助函式區 =================
@st.cache_data(ttl=86400)
def get_tw_stock_info():
    stock_dict = {}
    try:
        res_twse = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL")
        if res_twse.status_code == 200:
            for item in res_twse.json():
                if len(item['Code']) == 4:
                    stock_dict[item['Code'] + '.TW'] = item['Name']
        
        res_tpex = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes")
        if res_tpex.status_code == 200:
            for item in res_tpex.json():
                if len(item['SecuritiesCompanyCode']) == 4:
                    stock_dict[item['SecuritiesCompanyCode'] + '.TWO'] = item['CompanyName']
    except Exception:
        stock_dict = {'2330.TW': '台積電', '2317.TW': '鴻海', '2891.TW': '中信金'}
    return stock_dict

def render_html_table(data_list):
    if not data_list:
        return "<div style='font-size: 16px; margin-top: 10px;'>本日無符合條件標的</div>"
    
    html = "<div style='overflow-x: auto;'>"
    html += "<table style='width: 100%; min-width: 600px; border-collapse: collapse; font-size: 16px; text-align: center; font-family: sans-serif;'>"
    html += "<tr style='background-color: #f0f2f6; border-bottom: 2px solid #ddd;'>"
    html += "<th style='padding: 10px;'>代號名稱</th><th style='padding: 10px;'>收盤價</th>"
    html += "<th style='padding: 10px;'>漲跌幅</th><th style='padding: 10px;'>第一低</th>"
    html += "<th style='padding: 10px;'>第二低</th><th style='padding: 10px;'>第一高</th>"
    html += "<th style='padding: 10px;'>第二高</th></tr>"
    
    for row in data_list:
        color = "#ff4b4b" if "+" in row['漲跌幅'] else "#09ab3b" if "-" in row['漲跌幅'] else "black"
        html += "<tr style='border-bottom: 1px solid #eee;'>"
        html += f"<td style='padding: 8px;'><b>{row['代號名稱']}</b></td><td style='padding: 8px;'>{row['收盤價']}</td>"
        html += f"<td style='padding: 8px; color: {color}; font-weight: bold;'>{row['漲跌幅']}</td>"
        html += f"<td style='padding: 8px;'>{row['第一低']}</td><td style='padding: 8px;'>{row['第二低']}</td>"
        html += f"<td style='padding: 8px;'>{row['第一高']}</td><td style='padding: 8px;'>{row['第二高']}</td></tr>"
        
    html += "</table></div>"
    return html

# ================= 主程式區 =================
st.title("📈 台股波段多空篩選器 & AI 診斷")

if 'calc_done' not in st.session_state:
    st.session_state['calc_done'] = False
    st.session_state['results'] = {}
    st.session_state['dates'] = []

st.write("點擊下方按鈕，系統將自動抓取全市場資料並運算（約需 1~3 分鐘）。")

if st.button("🚀 開始篩選 (一鍵執行)", use_container_width=True, type="primary"):
    with st.spinner("正在獲取台股全市場代碼與名稱..."):
        stock_info = get_tw_stock_info()
        all_tickers = list(stock_info.keys())
        
    with st.spinner(f"正在下載 {len(all_tickers)} 檔股票歷史資料，請耐心等候..."):
        try:
            data = yf.download(all_tickers, period="6mo", group_by="ticker", threads=True, progress=False)
        except Exception:
            st.error("下載資料發生錯誤，請稍後再試。")
            st.stop()
            
    valid_dates = data.index.dropna().unique().sort_values()[-5:]
    date_strs = [d.strftime("%Y-%m-%d") for d in valid_dates]
    results_by_date = {d: {'up': [], 'down': []} for d in date_strs}
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    total_stocks = len(all_tickers)
    
    for idx, ticker in enumerate(all_tickers):
        if idx % 50 == 0:
            progress_bar.progress((idx + 1) / total_stocks)
            status_text.text(f"正在運算中: {idx+1} / {total_stocks} 檔...")
            
        try:
            df_full = data[ticker].copy() if len(all_tickers) > 1 else data.copy()
            df_full = df_full.dropna()
            
            if isinstance(df_full.columns, pd.MultiIndex):
                df_full.columns = df_full.columns.droplevel(1)
                
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
                pct_change = ((today_close - yest_close) / yest_close) * 100
                pct_str = f"+{pct_change:.2f}%" if pct_change > 0 else f"{pct_change:.2f}%"

                stock_code = ticker.split('.')[0]
                stock_name = stock_info.get(ticker, "")
                full_name = f"{stock_code} {stock_name}"
                
                if today_pos == 1 and yest_pos == -1 and len(waves) >= 5:
                    low_2, high_2, low_1, high_1 = waves[-2]['low'], waves[-3]['high'], waves[-4]['low'], waves[-5]['high']
                    if high_2 >= high_1 and low_2 >= low_1:
                        results_by_date[date_str]['up'].append({
                            "代碼": ticker, "代號名稱": full_name, "收盤價": round(today_close, 2), "漲跌幅": pct_str,
                            "第一低": round(low_1, 2), "第二低": round(low_2, 2), "第一高": round(high_1, 2), "第二高": round(high_2, 2)
                        })

                elif today_pos == -1 and yest_pos == 1 and len(waves) >= 5:
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
    st.session_state['calc_done'] = True
    progress_bar.empty()
    status_text.empty()
    st.rerun()

# ================= 顯示結果與 AI 分析區 =================
if st.session_state.get('calc_done'):
    st.success("🎉 運算完成！")
    selected_date = st.radio("📅 選擇資料日期：", st.session_state['dates'], horizontal=True)
    current_data = st.session_state['results'][selected_date]
    
    tab1, tab2 = st.tabs(["🟢 多方突破", "🔴 空方跌破"])
    with tab1:
        st.markdown(render_html_table(current_data['up']), unsafe_allow_html=True)
    with tab2:
        st.markdown(render_html_table(current_data['down']), unsafe_allow_html=True)
    
    st.write("---")
    
    # ===== 🤖 AI 深度分析區 =====
    st.subheader("🤖 AI 專屬操盤助理")
    
    # 將所有符合條件的股票整理成一個下拉選單
    all_filtered_stocks = current_data['up'] + current_data['down']
    
    if not all_filtered_stocks:
        st.info("本日無符合條件的股票可供分析。")
    elif not HAS_AI:
        st.warning("⚠️ 系統尚未偵測到 AI 鑰匙 (API Key)，請確認是否已將鑰匙存入 Streamlit Secrets。")
    else:
        # 製作下拉選單的選項
        stock_options = {row['代號名稱']: row for row in all_filtered_stocks}
        selected_stock_name = st.selectbox("請選擇一檔您有興趣的股票，讓 AI 為您進行四大面向深度診斷：", list(stock_options.keys()))
        
        if st.button(f"✨ 開始診斷 {selected_stock_name}", type="primary"):
            target_stock = stock_options[selected_stock_name]
            
            with st.spinner(f"AI 正在為您收集 {selected_stock_name} 的資料並思考中... (大約需要 10 秒鐘)"):
                try:
                    # 1. 自動去 Yahoo Finance 抓取最新基本面與新聞
                    ticker_obj = yf.Ticker(target_stock['代碼'])
                    info = ticker_obj.info
                    news = ticker_obj.news
                    
                    pe_ratio = info.get('trailingPE', '無資料')
                    pb_ratio = info.get('priceToBook', '無資料')
                    volume = info.get('volume', '無資料')
                    
                    news_titles = "無最新新聞"
                    if news:
                        news_titles = "\n".join([f"- {n['title']}" for n in news[:3]]) # 只取最近3篇
                        
                    # 2. 撰寫給 AI 的指令 (Prompt)
                    prompt = f"""
                    你是一位精通台股的專業操盤手與分析師。
                    我目前使用「波段高低點與5日均線」策略篩選出了這檔股票，請根據以下提供的資料，幫我撰寫一份給散戶看的「四大面向」診斷報告。

                    【股票基本資料】
                    股票名稱：{selected_stock_name}
                    當前收盤價：{target_stock['收盤價']}
                    今日成交量：{volume}
                    波段第一低點：{target_stock['第一低']}，第二低點：{target_stock['第二低']}
                    波段第一高點：{target_stock['第一高']}，第二高點：{target_stock['第二高']}
                    本益比 (P/E)：{pe_ratio}
                    股價淨值比 (P/B)：{pb_ratio}
                    
                    【近期新聞標題】
                    {news_titles}

                    請務必嚴格按照以下 4 個區塊來排版回答，使用繁體中文，語氣客觀專業，並善用重點列點：
                    1. 📊 籌碼與主力動向 (依據成交量與波段漲跌推測籌碼穩定度)
                    2. 📰 基本面與新聞總結 (評估本益比與上述新聞對股價的影響)
                    3. 📈 技術指標健檢 (評估目前價格距離波段低點的防守空間，乖離率是否過高)
                    4. 🎯 AI 交易計畫建議 (請具體給出建倉建議、停損防守價位、以及風險獲利比的評估)
                    """
                    
                    # 3. 呼叫 AI 產生報告
                    response = model.generate_content(prompt)
                    
                    # 4. 顯示報告
                    st.success("✨ 診斷完成！請參考以下 AI 分析報告：")
                    
                    # 用 Markdown 將 AI 的回答漂亮地印出來
                    st.markdown(response.text)
                    
                except Exception as e:
                    st.error(f"AI 診斷過程中發生錯誤。原因：{e}")
