import streamlit as st
import yfinance as yf
import pandas as pd
import requests

# 設定網頁標題與外觀
st.set_page_config(page_title="台股波段多空篩選器", page_icon="📈")
st.title("📈 台股波段多空篩選器")
st.write("點擊下方按鈕，系統將自動抓取上市/上櫃全市場資料並運算（約需 1~3 分鐘，請耐心等候轉圈圈結束）。")

# 獲取台股上市與上櫃股票代碼的函數
@st.cache_data(ttl=86400) # 每天快取一次即可
def get_tw_stock_tickers():
    tickers = []
    try:
        # 抓取上市股票代碼 (透過政府開放資料)
        res_twse = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL")
        if res_twse.status_code == 200:
            for item in res_twse.json():
                if len(item['Code']) == 4: # 過濾掉權證，只保留4碼一般股票
                    tickers.append(item['Code'] + '.TW')
        
        # 抓取上櫃股票代碼
        res_tpex = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes")
        if res_tpex.status_code == 200:
            for item in res_tpex.json():
                if len(item['SecuritiesCompanyCode']) == 4:
                    tickers.append(item['SecuritiesCompanyCode'] + '.TWO')
    except Exception as e:
        st.error("獲取全市場代碼失敗，將使用預設權值股測試。")
        tickers = ['2330.TW', '2317.TW', '2454.TW']
        
    return tickers

# ====== 網頁上的【一鍵執行】按鈕 ======
if st.button("🚀 開始篩選 (一鍵執行)", use_container_width=True, type="primary"):
    
    # 1. 抓取代碼
    with st.spinner("正在獲取台股全市場代碼..."):
        all_tickers = get_tw_stock_tickers()
        
    # 2. 大量下載歷史股價 (使用 yfinance 批次下載提速)
    with st.spinner(f"正在下載 {len(all_tickers)} 檔股票歷史資料，這需要一點時間..."):
        try:
            # 抓取過去 6 個月資料
            data = yf.download(all_tickers, period="6mo", group_by="ticker", threads=True, progress=False)
        except Exception as e:
            st.error("下載資料發生錯誤，請稍後再試。")
            st.stop()
            
    up_trend_list = []
    down_trend_list = []
    
    # 準備進度條
    progress_bar = st.progress(0)
    status_text = st.empty()
    total_stocks = len(all_tickers)
    
    # 3. 逐一運算多空邏輯
    for idx, ticker in enumerate(all_tickers):
        # 更新進度條
        if idx % 50 == 0:
            progress_bar.progress((idx + 1) / total_stocks)
            status_text.text(f"正在運算中: {idx+1} / {total_stocks} 檔...")
            
        try:
            # 提取單一股票資料
            df = data[ticker].copy() if len(all_tickers) > 1 else data.copy()
            df = df.dropna()
            
            # 若資料不足則跳過
            if df.empty or len(df) < 10:
                continue
                
            # 修正資料格式
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)
                
            # 計算 5 日均線
            df['5MA'] = df['Close'].rolling(window=5).mean()
            df = df.dropna()
            
            # 判斷每天是在 5MA 之上(1) 還是 之下(-1)
            df['Position'] = df.apply(lambda row: 1 if row['Close'] > row['5MA'] else -1, axis=1)
            
            waves = []
            current_pos = df['Position'].iloc[0]
            current_high = df['High'].iloc[0]
            current_low = df['Low'].iloc[0]

            # 歷史回溯：切分波段並找出最高與最低價
            for i in range(1, len(df)):
                pos = df['Position'].iloc[i]
                high = df['High'].iloc[i]
                low = df['Low'].iloc[i]

                if pos == current_pos:
                    if high > current_high: current_high = high
                    if low < current_low: current_low = low
                else:
                    waves.append({
                        'type': 'above' if current_pos == 1 else 'below',
                        'high': current_high,
                        'low': current_low
                    })
                    current_pos = pos
                    current_high = high
                    current_low = low

            waves.append({
                'type': 'above' if current_pos == 1 else 'below',
                'high': current_high,
                'low': current_low
            })

            # 觀察「昨天」與「今天」的狀態
            today_pos = df['Position'].iloc[-1]
            yest_pos = df['Position'].iloc[-2]

            stock_name = ticker.split('.')[0] # 只保留數字代碼

            # 🟢 【趨勢多】判斷邏輯
            if today_pos == 1 and yest_pos == -1:
                if len(waves) >= 5:
                    low_2 = waves[-2]['low']
                    high_2 = waves[-3]['high']
                    low_1 = waves[-4]['low']
                    high_1 = waves[-5]['high']

                    if high_2 >= high_1 and low_2 >= low_1:
                        up_trend_list.append(stock_name)

            # 🔴 【趨勢空】判斷邏輯
            elif today_pos == -1 and yest_pos == 1:
                if len(waves) >= 5:
                    high_2 = waves[-2]['high']
                    low_2 = waves[-3]['low']
                    high_1 = waves[-4]['high']
                    low_1 = waves[-5]['low']

                    if high_2 <= high_1 and low_2 <= low_1:
                        down_trend_list.append(stock_name)

        except Exception as e:
            continue
            
    # 運算結束，完成進度條
    progress_bar.progress(1.0)
    status_text.text("運算完成！")
    
    # 4. 顯示結果
    st.success("🎉 篩選完畢！以下是今日符合條件的股票：")
    
    # 左右兩排顯示
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("🟢 趨勢多")
        if up_trend_list:
            for s in up_trend_list:
                st.code(s)
        else:
            st.write("今日無符合標的")
            
    with col2:
        st.subheader("🔴 趨勢空")
        if down_trend_list:
            for s in down_trend_list:
                st.code(s)
        else:
            st.write("今日無符合標的")
