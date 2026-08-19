import streamlit as st
import yfinance as yf
import pandas as pd
import requests

# 設定網頁標題與外觀 (layout="wide" 讓表格在手機上更好看)
st.set_page_config(page_title="台股波段多空篩選器", page_icon="📈", layout="wide")
st.title("📈 台股波段多空篩選器")
st.write("點擊下方按鈕，系統將自動抓取上市/上櫃全市場資料並運算（約需 1~3 分鐘）。")

# 獲取台股股票代碼與名稱的字典
@st.cache_data(ttl=86400)
def get_tw_stock_info():
    stock_dict = {}
    try:
        # 上市
        res_twse = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL")
        if res_twse.status_code == 200:
            for item in res_twse.json():
                if len(item['Code']) == 4:
                    stock_dict[item['Code'] + '.TW'] = item['Name']
        
        # 上櫃
        res_tpex = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes")
        if res_tpex.status_code == 200:
            for item in res_tpex.json():
                if len(item['SecuritiesCompanyCode']) == 4:
                    stock_dict[item['SecuritiesCompanyCode'] + '.TWO'] = item['CompanyName']
    except Exception:
        # 如果政府 API 當機，提供備用測試名單
        stock_dict = {'2330.TW': '台積電', '2317.TW': '鴻海', '2891.TW': '中信金'}
        
    return stock_dict

# 格式化漲跌幅
def format_pct(val):
    if val > 0:
        return f"+{val:.2f}%"
    elif val < 0:
        return f"{val:.2f}%"
    else:
        return "0.00%"

# 台股專屬配色：紅漲綠跌
def highlight_taiwan_colors(val):
    if isinstance(val, str) and '%' in val:
        if '+' in val:
            return 'color: #ff4b4b;' # Streamlit 內建紅色
        elif '-' in val:
            return 'color: #09ab3b;' # Streamlit 內建綠色
    return ''

# ====== 網頁上的【一鍵執行】按鈕 ======
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
            
    up_trend_list = []
    down_trend_list = []
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    total_stocks = len(all_tickers)
    
    for idx, ticker in enumerate(all_tickers):
        if idx % 50 == 0:
            progress_bar.progress((idx + 1) / total_stocks)
            status_text.text(f"正在運算中: {idx+1} / {total_stocks} 檔...")
            
        try:
            df = data[ticker].copy() if len(all_tickers) > 1 else data.copy()
            df = df.dropna()
            
            if df.empty or len(df) < 10:
                continue
                
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)
                
            df['5MA'] = df['Close'].rolling(window=5).mean()
            df = df.dropna()
            
            df['Position'] = df.apply(lambda row: 1 if row['Close'] > row['5MA'] else -1, axis=1)
            
            waves = []
            current_pos = df['Position'].iloc[0]
            current_high = df['High'].iloc[0]
            current_low = df['Low'].iloc[0]

            for i in range(1, len(df)):
                pos = df['Position'].iloc[i]
                high = df['High'].iloc[i]
                low = df['Low'].iloc[i]

                if pos == current_pos:
                    if high > current_high: current_high = high
                    if low < current_low: current_low = low
                else:
                    waves.append({'type': 'above' if current_pos == 1 else 'below', 'high': current_high, 'low': current_low})
                    current_pos = pos
                    current_high = high
                    current_low = low

            waves.append({'type': 'above' if current_pos == 1 else 'below', 'high': current_high, 'low': current_low})

            today_pos = df['Position'].iloc[-1]
            yest_pos = df['Position'].iloc[-2]
            
            # 計算今日價格與漲跌幅
            today_close = df['Close'].iloc[-1]
            yest_close = df['Close'].iloc[-2]
            pct_change = ((today_close - yest_close) / yest_close) * 100

            # 組合股票名稱
            stock_code = ticker.split('.')[0]
            stock_name = stock_info.get(ticker, "")
            full_name = f"{stock_code} {stock_name}"
            
            # 準備存入表格的資料格式
            result_dict = {
                "代號名稱": full_name,
                "收盤價": round(today_close, 2),
                "漲跌幅": format_pct(pct_change),
                "第一低": 0.0, "第二低": 0.0, "第一高": 0.0, "第二高": 0.0
            }

            # 🟢 【趨勢多】判斷邏輯
            if today_pos == 1 and yest_pos == -1:
                if len(waves) >= 5:
                    low_2 = waves[-2]['low']
                    high_2 = waves[-3]['high']
                    low_1 = waves[-4]['low']
                    high_1 = waves[-5]['high']

                    if high_2 >= high_1 and low_2 >= low_1:
                        result_dict.update({
                            "第一低": round(low_1, 2), "第二低": round(low_2, 2), 
                            "第一高": round(high_1, 2), "第二高": round(high_2, 2)
                        })
                        up_trend_list.append(result_dict)

            # 🔴 【趨勢空】判斷邏輯
            elif today_pos == -1 and yest_pos == 1:
                if len(waves) >= 5:
                    high_2 = waves[-2]['high']
                    low_2 = waves[-3]['low']
                    high_1 = waves[-4]['high']
                    low_1 = waves[-5]['low']

                    if high_2 <= high_1 and low_2 <= low_1:
                        result_dict.update({
                            "第一低": round(low_1, 2), "第二低": round(low_2, 2), 
                            "第一高": round(high_1, 2), "第二高": round(high_2, 2)
                        })
                        down_trend_list.append(result_dict)

        except Exception:
            continue
            
    progress_bar.progress(1.0)
    status_text.text("運算完成！")
    st.success("🎉 篩選完畢！您可以點擊下方頁籤切換查看：")
    
    # 建立兩個頁籤
    tab1, tab2 = st.tabs(["🟢 多方突破名單", "🔴 空方跌破名單"])
    
    with tab1:
        if up_trend_list:
            df_up = pd.DataFrame(up_trend_list)
            # 顯示表格並自動上色
            st.dataframe(df_up.style.map(highlight_taiwan_colors, subset=['漲跌幅']), use_container_width=True, hide_index=True)
        else:
            st.info("今日無符合多方突破的標的")
            
    with tab2:
        if down_trend_list:
            df_down = pd.DataFrame(down_trend_list)
            st.dataframe(df_down.style.map(highlight_taiwan_colors, subset=['漲跌幅']), use_container_width=True, hide_index=True)
        else:
            st.info("今日無符合空方跌破的標的")
