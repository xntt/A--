import streamlit as st
import pandas as pd
import requests
import time
import concurrent.futures
from datetime import datetime
import re
import json

# ================= 页面配置 =================
st.set_page_config(page_title="量化交易雷达系统", layout="wide")

if "found_stocks" not in st.session_state:
    st.session_state.found_stocks = []
if "current_strategy" not in st.session_state:
    st.session_state.current_strategy = "尚未选择"

# ================= 数据获取引擎 =================

# 股票列表依然用一次性接口拉取全市场（这个只请求1次，不会封）
def fetch_all_stock_codes():
    url = "https://75.push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1", "pz": "5000", "po": "1", "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281", "fltt": "2", "invt": "2",
        "fid": "f3", "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
        "fields": "f12,f14"
    }
    try:
        response = requests.get(url, params=params, timeout=5)
        data = response.json()
        stocks = data['data']['diff']
        valid_stocks = [s for s in stocks if not s['f14'].startswith('ST') and not s['f14'].startswith('*ST')]
        return valid_stocks
    except Exception as e:
        return []

# 【核心替换】：纯血新浪财经 K线接口 (VIP JSON V2 API)
def fetch_kline_data_sina(stock_code, days=100):
    code_str = str(stock_code).strip().zfill(6)
    prefix = 'sh' if code_str.startswith(('6', '9')) else 'sz'
    symbol = f"{prefix}{code_str}"
    
    url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {
        "symbol": symbol,
        "scale": "240",  # 240分钟 = 日线
        "ma": "no",
        "datalen": str(days)
    }
    
    try:
        response = requests.get(url, params=params, timeout=5)
        text = response.text
        
        # 新浪返回的 JSON 键值没有引号（例如 {day:"2023", open:"10"}），直接 loads 会报错
        # 这里用正则强行给 key 加上双引号，修复为标准 JSON
        text = re.sub(r'([{,])\s*([a-zA-Z_]+)\s*:', r'\1"\2":', text)
        data = json.loads(text)
        
        if data and isinstance(data, list):
            parsed_data = []
            for k in data:
                parsed_data.append({
                    "Date": k.get("day"),
                    "Open": float(k.get("open", 0)),
                    "Close": float(k.get("close", 0)),
                    "High": float(k.get("high", 0)),
                    "Low": float(k.get("low", 0)),
                    "Volume": float(k.get("volume", 0))
                })
            df = pd.DataFrame(parsed_data)
            return df
    except Exception as e:
        pass
    
    return pd.DataFrame()

def calculate_indicators(df):
    if df.empty: return df
    df['MA5'] = df['Close'].rolling(window=5, min_periods=1).mean()
    df['MA10'] = df['Close'].rolling(window=10, min_periods=1).mean()
    df['MA20'] = df['Close'].rolling(window=20, min_periods=1).mean()
    df['MA60'] = df['Close'].rolling(window=60, min_periods=1).mean()
    df['VMA5'] = df['Volume'].rolling(window=5, min_periods=1).mean()
    df['VMA20'] = df['Volume'].rolling(window=20, min_periods=1).mean()
    return df

# ================= 侧边栏 =================
st.sidebar.title("⚡ 智能量化交易工作流")
mode = st.sidebar.radio("选择工作流阶段：", [
    "🎯 阶段一：全市场海选 (粗筛)", 
    "🏆 阶段二：深度过滤与打分 (精选)", 
    "🔍 阶段三：个股形态复诊"
])

# ================= 主程序 =================
if mode == "🎯 阶段一：全市场海选 (粗筛)":
    st.title("🎯 全市场潜伏雷达 (阶段一：海选)")
    strategy = st.radio("选择海选策略：", ["趋势低吸", "底部启动", "稳健波段"])
    
    if st.button("🚀 启动全市场粗筛", type="primary"):
        st.session_state.current_strategy = strategy
        st.session_state.found_stocks = [] 
        
        all_stocks = fetch_all_stock_codes()
        progress_bar = st.progress(0)
        status_text = st.empty()
        found_list = []
        
        def process_stock(stock_info):
            code = stock_info['f12']
            name = stock_info['f14']
            hist = fetch_kline_data_sina(code, days=65) # 全面换用新浪接口
            if hist.empty or len(hist) < 2: return None
            
            df = calculate_indicators(hist)
            latest = df.iloc[-1]
            prev1 = df.iloc[-2]
            
            is_match = False
            if "趋势低吸" in strategy and (latest['MA20'] > latest['MA60'] and abs(latest['Close'] - latest['MA20']) / latest['MA20'] < 0.02 and latest['Volume'] < latest['VMA5'] * 0.7): is_match = True
            elif "底部启动" in strategy and (latest['Close'] > latest['MA60'] and prev1['Close'] <= prev1['MA60'] and latest['Volume'] > latest['VMA20'] * 2.5): is_match = True
            elif "稳健波段" in strategy and (latest['MA5'] > latest['MA10'] > latest['MA20'] > latest['MA60'] and latest['Close'] > latest['MA5'] and latest['Volume'] > latest['VMA5']): is_match = True
            
            if is_match: return {"股票代码": str(code).zfill(6), "股票名称": name, "当前价": latest['Close'], "入选核心逻辑": strategy}
            return None

        # 如果你要跑全市场，改成 all_stocks，当前为了防止新浪把你限流，先测 1000 只
        test_stocks = all_stocks[:1000] 
        test_total = len(test_stocks)
        
        # 新浪接口并发稍微降一点，保证稳如老狗
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_stock = {executor.submit(process_stock, stock): stock for stock in test_stocks} 
            for count, future in enumerate(concurrent.futures.as_completed(future_to_stock), 1):
                res = future.result()
                if res: found_list.append(res)
                if count % 10 == 0:
                    progress_bar.progress(count / test_total)
                    status_text.text(f"📡 新浪数据扫描中... 已处理 {count}/{test_total}，发现 {len(found_list)} 只")
        
        st.session_state.found_stocks = found_list
        progress_bar.progress(1.0)
        status_text.success(f"✅ 海选完成！扫出 {len(found_list)} 只标的。")
        
    if st.session_state.found_stocks:
        df_result = pd.DataFrame(st.session_state.found_stocks)
        st.dataframe(df_result, use_container_width=True)
        csv_data = df_result.to_csv(index=False).encode('utf-8-sig')
        st.download_button("💾 下载本次海选结果 (CSV文件)", data=csv_data, file_name=f"海选结果_{datetime.now().strftime('%Y%m%d')}.csv", mime="text/csv", type="primary")

elif mode == "🏆 阶段二：深度过滤与打分 (精选)":
    st.title("🏆 量化多维打分中心")
    data_source = st.radio("📂 选择数据来源：", ["1️⃣ 当前系统缓存", "2️⃣ 上传历史CSV"], horizontal=True)
    
    df_to_score = pd.DataFrame()
    strategy_for_score = "尚未选择"
    ready_to_score = False

    if data_source.startswith("1️⃣"):
        if st.session_state.found_stocks:
            df_to_score = pd.DataFrame(st.session_state.found_stocks)
            strategy_for_score = st.session_state.current_strategy
            ready_to_score = True
        else:
            st.warning("⚠️ 缓存为空，请先去阶段一扫描或选择上传CSV。")

    elif data_source.startswith("2️⃣"):
        uploaded_file = st.file_uploader("📥 上传阶段一下载的 .csv 文件", type=['csv'])
        if uploaded_file is not None:
            try:
                # 强行全文本读取，保住所有的 0
                temp_df = pd.read_csv(uploaded_file, dtype=str, encoding='utf-8-sig')
                
                code_col = None
                for col in temp_df.columns:
                    if '代码' in str(col): 
                        code_col = col
                        break
                
                if code_col:
                    temp_df['股票代码'] = temp_df[code_col].apply(lambda x: str(x).strip().zfill(6))
                    df_to_score = temp_df
                    st.success(f"✅ 文件解析成功！解析到 {len(df_to_score)} 条数据。")
                    strategy_for_score = st.selectbox("⚙️ 这批股票用的是什么策略？", ["趋势低吸", "底部启动", "稳健波段"])
                    ready_to_score = True
                else:
                    st.error(f"❌ 解析失败，CSV中未找到包含'代码'的列。当前列名: {temp_df.columns.tolist()}")
            except Exception as e:
                st.error(f"文件异常: {e}")

    st.markdown("---")
    
    if ready_to_score:
        if st.button("🚀 启动新浪多因子深度打分", type="primary", use_container_width=True):
            scored_stocks = []
            progress_text = st.empty()
            progress_bar = st.progress(0)
            
            stock_list = df_to_score.to_dict('records')
            total = len(stock_list)
            
            for idx, stock in enumerate(stock_list):
                code = str(stock.get('股票代码', '')).zfill(6)
                
                name = "未知名称"
                for k in stock.keys():
                    if '名称' in str(k):
                        name = stock[k]
                        break
                
                progress_text.text(f"🔬 正在请求新浪K线: {name} ({code}) ... [{idx+1}/{total}]")
                
                # 请求新浪接口
                hist = fetch_kline_data_sina(code, days=80) 
                
                # 就算新浪挂了没拉到数据，也强行保底输出，彻底终结“没结果”的魔咒
                if hist.empty:
                    scored_stocks.append({
                        "代码": code, "名称": name, "综合总分": 0, "资金活跃分": 0, "趋势抗跌分": 0, "股性记忆分": 0, "备注": "新浪接口返回空"
                    })
                    continue
                
                try:
                    df = calculate_indicators(hist)
                    latest = df.iloc[-1]
                    
                    if len(df) > 20:
                        price_20d_ago = df.iloc[-20]['Close']
                        gain_20d = (latest['Close'] - price_20d_ago) / price_20d_ago * 100
                        rps_score = max(0, min(100, (gain_20d + 10) * 4)) 
                    else:
                        rps_score = 50 
                    
                    vol_ratio = latest['Volume'] / latest['VMA20'] if latest['VMA20'] > 0 else 1
                    activity_score = max(0, min(100, vol_ratio * 33))
                    
                    limit_up_days = len(df[ (df['Close'] - df['Close'].shift(1))/df['Close'].shift(1) > 0.09 ])
                    if limit_up_days >= 2: stock_char_score = 100
                    elif limit_up_days == 1: stock_char_score = 60
                    else: stock_char_score = 20
                        
                    final_score = (rps_score + activity_score + stock_char_score) / 3
                    
                    scored_stocks.append({
                        "代码": code, "名称": name,
                        "综合总分": round(final_score, 1),
                        "资金活跃分": round(activity_score, 1),
                        "趋势抗跌分": round(rps_score, 1),
                        "股性记忆分": round(stock_char_score, 1),
                        "备注": "打分成功"
                    })
                except Exception as e:
                    scored_stocks.append({
                        "代码": code, "名称": name, "综合总分": 0, "资金活跃分": 0, "趋势抗跌分": 0, "股性记忆分": 0, "备注": "指标计算异常"
                    })
                    
                progress_bar.progress((idx + 1) / total)
                time.sleep(0.1) # 微微加个延迟，防止新浪拦截
                
            progress_text.text("✅ 打分计算全部结束！")
            
            # 只要进了循环，这个表格绝对出得来！
            if scored_stocks:
                df_scores = pd.DataFrame(scored_stocks).sort_values(by="综合总分", ascending=False).reset_index(drop=True)
                st.success(f"🎯 基于新浪数据的打分提纯完成！")
                st.dataframe(df_scores.style.background_gradient(subset=['综合总分', '资金活跃分'], cmap='YlOrRd'), use_container_width=True)
            else:
                st.error("天呐，不可思议的错误！数组居然是空的，请截图发给技术支持。")

elif mode == "🔍 阶段三：个股形态复诊":
    st.title("🔍 个股形态显微镜")
    code_input = st.text_input("📝 输入股票代码 (例如: 000001)", max_chars=6)
    if code_input and len(code_input) == 6:
        hist_data = fetch_kline_data_sina(code_input, days=120) 
        if not hist_data.empty:
            df = calculate_indicators(hist_data)
            st.line_chart(df[['Date', 'Close', 'MA10', 'MA20', 'MA60']].set_index('Date'))
        else:
            st.error("新浪接口未能获取到该股票数据。")
