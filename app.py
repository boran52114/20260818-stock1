import streamlit as st
import yfinance as yf
import pandas as pd
import requests

# 設定網頁標題與外觀 (手機友善)
st.set_page_config(page_title="台股波段多空篩選器", page_icon="📈", layout="wide")

# ================= 輔助函式區 =================

@st.cache_data(ttl=86400)
def get_tw_stock_info():
    """獲取全市場股票代碼與名稱"""
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
    """自訂 HTML 表格：放大字體、手機左右滑動、台股專屬紅綠配色"""
    if not data_list:
        return "<div style='font-size: 16px; margin-top: 10px;'>本日無符合條件標的</div>"
    
    # 外層 div 允許左右滾動，適合手機
    html = "<div style='overflow-x: auto;'>"
    html += "<table style='width: 100%; min-width: 600px; border-collapse: collapse; font-size: 16px; text-align: center; font-family: sans-serif;'>"
    
    # 標題列
    html += "<tr style='background-color: #f0f2f6; border-bottom: 2px solid #ddd;'>"
    html += "<th style='padding: 10px;'>代號名稱</th>"
    html += "<th style='padding: 10px;'>收盤價</th>"
    html += "<th style='padding: 10px;'>漲跌幅</th>"
    html += "<th style='padding: 10px;'>第一低</th>"
    html += "<th style='padding: 10px;'>第二低</th>"
    html += "<th style='padding: 10px;'>第一高</th>"
    html += "<th style='padding: 10px;'>第二高</th>"
    html += "</tr>"
    
    # 填入資料
    for row in data_list:
        # 判斷顏色：紅漲綠跌
        color = "#ff4b4b" if "+" in row['漲跌幅'] else "#09ab3b" if "-" in row['漲跌幅'] else "black"
        
        html += "<tr style='border-bottom: 1px solid #eee;'>"
        html += f"<td style='padding: 8px;'><b>{row['代號名稱']}</b></td>"
        html += f"<td style='padding: 8px;'>{row['收盤價']}</td>"
        html += f"<td style='padding: 8px; color: {color}; font-weight: bold;'>{row['漲跌幅']}</td>"
        html += f"<td style='padding: 8px;'>{row['第一低']}</td>"
        html += f"<td style='padding: 8px;'>{row['第二低']}</td>"
        html += f"<td style='padding: 8px;'>{row['第一高']}</td>"
        html += f"<td style='padding: 8px;'>{row['第二高']}</td>"
        html += "</tr>"
        
    html += "</table></div>"
    return html

# ================= 主程式區 =================

st.title("📈 台股波段多空篩選器")

# 利用 session_state 保存運算結果，避免切換日期時重新下載
if 'calc_done' not in st.session_state:
    st.session_state['calc_done'] = False
    st.session_state['results'] = {}
    st.session_state['dates'] = []

st.write("點擊下方按鈕，系統將自動抓取全市場資料，並**一次運算最近 5 個交易日**的結果（約需 1~3 分鐘）。")

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
            
    # 取得最近的 5 個交易日日期
    valid_dates = data.index.dropna().unique().sort_values()[-5:]
    date_strs = [d.strftime("%Y-%m-%d") for d in valid_dates]
    
    # 準備一個字典來存 5 天的結果
    results_by_date = {d: {'up': [], 'down': []} for d in date_strs}
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    total_stocks = len(all_tickers)
    
    # 迴圈運算每檔股票
    for idx, ticker in enumerate(all_tickers):
        if idx % 50 == 0:
            progress_bar.progress((idx + 1) / total_stocks)
            status_text.text(f"正在運算中: {idx+1} / {total_stocks} 檔...")
            
        try:
            # 取得單檔股票並計算均線
            df_full = data[ticker].copy() if len(all_tickers) > 1 else data.copy()
            df_full = df_full.dropna()
            
            if isinstance(df_full.columns, pd.MultiIndex):
                df_full.columns = df_full.columns.droplevel(1)
                
            if len(df_full) < 15:
                continue
                
            df_full['5MA'] = df_full['Close'].rolling(window=5).mean()
            df_full = df_full.dropna()
            df_full['Position'] = df_full.apply(lambda row: 1 if row['Close'] > row['5MA'] else -1, axis=1)
            
            # --- 核心：時光機迴圈 (針對最近5天，分別看當下的波段) ---
            for d_idx, target_date in enumerate(valid_dates):
                date_str = date_strs[d_idx]
                
                if target_date not in df_full.index:
                    continue
                    
                # 切割到「該日期」為止的資料，模擬當時的情境
                loc = df_full.index.get_loc(target_date)
                if isinstance(loc, slice) or isinstance(loc, pd.Series):
                    loc = df_full.index.get_indexer([target_date])[0]
                    
                df = df_full.iloc[:loc+1]
                
                if len(df) < 10:
                    continue
                
                # 計算該時光點的波段轉折
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
                
                today_close = df['Close'].iloc[-1]
                yest_close = df['Close'].iloc[-2]
                pct_change = ((today_close - yest_close) / yest_close) * 100
                pct_str = f"+{pct_change:.2f}%" if pct_change > 0 else f"{pct_change:.2f}%"

                stock_code = ticker.split('.')[0]
                stock_name = stock_info.get(ticker, "")
                
                # 判斷多空
                if today_pos == 1 and yest_pos == -1 and len(waves) >= 5:
                    low_2, high_2 = waves[-2]['low'], waves[-3]['high']
                    low_1, high_1 = waves[-4]['low'], waves[-5]['high']

                    if high_2 >= high_1 and low_2 >= low_1:
                        results_by_date[date_str]['up'].append({
                            "代號名稱": f"{stock_code} {stock_name}", "收盤價": round(today_close, 2), "漲跌幅": pct_str,
                            "第一低": round(low_1, 2), "第二低": round(low_2, 2), "第一高": round(high_1, 2), "第二高": round(high_2, 2)
                        })

                elif today_pos == -1 and yest_pos == 1 and len(waves) >= 5:
                    high_2, low_2 = waves[-2]['high'], waves[-3]['low']
                    high_1, low_1 = waves[-4]['high'], waves[-5]['low']

                    if high_2 <= high_1 and low_2 <= low_1:
                        results_by_date[date_str]['down'].append({
                            "代號名稱": f"{stock_code} {stock_name}", "收盤價": round(today_close, 2), "漲跌幅": pct_str,
                            "第一低": round(low_1, 2), "第二低": round(low_2, 2), "第一高": round(high_1, 2), "第二高": round(high_2, 2)
                        })
                        
        except Exception as e:
            continue
            
    # 存入暫存並完成
    st.session_state['results'] = results_by_date
    st.session_state['dates'] = date_strs[::-1] # 反轉，讓最新的日期排在最前面
    st.session_state['calc_done'] = True
    
    progress_bar.empty()
    status_text.empty()
    st.rerun() # 重新整理畫面以顯示結果

# ================= 顯示結果區 =================
if st.session_state.get('calc_done'):
    st.success("🎉 運算完成！資料已儲存於系統中。")
    
    # 選擇要查看的日期
    selected_date = st.radio("📅 選擇想查看的資料日期 (近5日)：", st.session_state['dates'], horizontal=True)
    
    # 根據選擇的日期提取資料
    current_data = st.session_state['results'][selected_date]
    
    # 分頁顯示
    tab1, tab2 = st.tabs(["🟢 多方突破名單", "🔴 空方跌破名單"])
    
    with tab1:
        html_up = render_html_table(current_data['up'])
        st.markdown(html_up, unsafe_allow_html=True)
        
    with tab2:
        html_down = render_html_table(current_data['down'])
        st.markdown(html_down, unsafe_allow_html=True)

st.write("---")
st.caption("提示：表格若超過手機螢幕寬度，可用手指在表格上「左右滑動」查看高低點資料。")
