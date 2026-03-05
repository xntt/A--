import streamlit as st
import pandas as pd
import requests
import time
import concurrent.futures
from datetime import datetime

st.set_page_config(page_title="量化交易雷达系统", layout="wide")

if "found_stocks" not in st.session_state:
    st.session_state.found_stocks = []
if "current_strategy" not in st.session_state:
    st.session_state.current_strategy = "尚未选择"

# ================= 数据获取引擎 =================
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

def fetch_kline_data_tencent(stock_code, days=100):
    prefix = 'sh' if str(stock_code).startswith('6') else 'sz'
    full_code = f"{prefix}{stock_code}"
    url = f"http://data.gtimg.cn/flashdata/hushen/latest/daily/{full_code}.js"
    try:
        response = requests.get(url, timeout=3)
        if response.status_code == 200 and len(response.text) > 100: # 确保不是被封禁返回的空页面
            content = response.text
            lines = content.split('\n')[1:-1]
            data = []
            for line in lines[-days:]:
                parts = line.split(' ')
                if len(parts) >= 6:
                    data.append({
                        "Date": parts[0], "Open": float(parts[1]),
                        "Close": float(parts[2]), "High": float(parts[3]),
                        "Low": float(parts[4]), "Volume": float(parts[5])
                    })
            df = pd.DataFrame(data)
            return df
    except Exception:
        pass
    return pd.DataFrame()

def calculate_indicators(df):
    if df.empty or len(df) < 60: return df
    df['MA5'] = df['Close'].rolling(window=5).mean()
    df['MA10'] = df['Close'].rolling(window=10).mean()
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA60'] = df['Close'].rolling(window=60).mean()
    df['VMA5'] = df['Volume'].rolling(window=5).mean()
    df['VMA20'] = df['Volume'].rolling(window=20).mean()
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
            hist = fetch_kline_data_tencent(code, days=65)
            if hist.empty: return None
            df = calculate_indicators(hist)
            if df.empty: return None
            
            latest = df.iloc[-1]
            prev1 = df.iloc[-2]
            
            is_match = False
            if "趋势低吸" in strategy and (latest['MA20'] > latest['MA60'] and abs(latest['Close'] - latest['MA20']) / latest['MA20'] < 0.02 and latest['Volume'] < latest['VMA5'] * 0.7): is_match = True
            elif "底部启动" in strategy and (latest['Close'] > latest['MA60'] and prev1['Close'] <= prev1['MA60'] and latest['Volume'] > latest['VMA20'] * 2.5): is_match = True
            elif "稳健波段" in strategy and (latest['MA5'] > latest['MA10'] > latest['MA20'] > latest['MA60'] and latest['Close'] > latest['MA5'] and latest['Volume'] > latest['VMA5']): is_match = True
            
            if is_match: return {"股票代码": str(code).zfill(6), "股票名称": name, "当前价": latest['Close'], "入选核心逻辑": strategy}
            return None

        test_stocks = all_stocks[:1000] 
        test_total = len(test_stocks)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_stock = {executor.submit(process_stock, stock): stock for stock in test_stocks} 
            for count, future in enumerate(concurrent.futures.as_completed(future_to_stock), 1):
                res = future.result()
                if res: found_list.append(res)
                if count % 20 == 0:
                    progress_bar.progress(count / test_total)
                    status_text.text(f"📡 扫描中... 已处理 {count}/{test_total}，发现 {len(found_list)} 只")
        
        st.session_state.found_stocks = found_list
        progress_bar.progress(1.0)
        status_text.success(f"✅ 海选完成！扫出 {len(found_list)} 只标的。")
        
    if st.session_state.found_stocks:
        df_result = pd.DataFrame(st.session_state.found_stocks)
        st.dataframe(df_result, use_container_width=True)
        csv_data = df_result.to_csv(index=False).encode('utf-8-sig')
        st.download_button("💾 下载本次海选结果 (CSV文件)", data=csv_data, file_name=f"海选基础池_{datetime.now().strftime('%Y%m%d')}.csv", mime="text/csv", type="primary")

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
            st.success("已加载内存数据。")
        else:
            st.warning("⚠️ 缓存为空，请先去阶段一扫描。")

    elif data_source.startswith("2️⃣"):
        uploaded_file = st.file_uploader("📥 上传 .csv 文件", type=['csv'])
        if uploaded_file is not None:
            # 暴力清洗：直接不管列名叫什么，只要包含'代码'两个字就强行重命名为'股票代码'
            try:
                temp_df = pd.read_csv(uploaded_file, encoding='utf-8-sig')
                col_mapping = {}
                for col in temp_df.columns:
                    if '代码' in str(col): col_mapping[col] = '股票代码'
                    elif '名称' in str(col): col_mapping[col] = '股票名称'
                    elif '逻辑' in str(col): col_mapping[col] = '入选核心逻辑'
                
                temp_df.rename(columns=col_mapping, inplace=True)
                
                if '股票代码' in temp_df.columns:
                    temp_df['股票代码'] = temp_df['股票代码'].astype(str).apply(lambda x: x.split('.')[0].strip().zfill(6))
                    df_to_score = temp_df
                    st.success(f"✅ 文件解析成功！解析到 {len(df_to_score)} 条数据。")
                    strategy_for_score = st.selectbox("⚙️ 选择策略匹配权重：", ["趋势低吸", "底部启动", "稳健波段"])
                    ready_to_score = True
                    with st.expander("👀 查看内部解析后的真实数据 (检查代码是否正确)"):
                        st.dataframe(df_to_score)
                else:
                    st.error(f"❌ 找不到包含'代码'的列。当前文件的列名是: {temp_df.columns.tolist()}")
            except Exception as e:
                st.error(f"解析异常: {e}")

    st.markdown("---")
    
    if ready_to_score:
        if st.button("🚀 启动多因子深度打分", type="primary", use_container_width=True):
            scored_stocks = []
            debug_logs = [] # 用于收集失败原因
            
            progress_text = st.empty()
            progress_bar = st.progress(0)
            
            stock_list = df_to_score.to_dict('records')
            total = len(stock_list)
            
            for idx, stock in enumerate(stock_list):
                code = str(stock.get('股票代码', '')).strip().zfill(6)
                name = stock.get('股票名称', '未知')
                logic = stock.get('入选核心逻辑', '无')
                
                progress_text.text(f"🔬 请求获取: {name} | 实际发出代码: [{code}] ... [{idx+1}/{total}]")
                
                # 防御1：如果代码解析出来是000000，直接记录错误
                if code == "000000":
                    debug_logs.append(f"❌ 行 {idx+1}: 代码解析错误，变成 000000")
                    continue
                    
                hist = fetch_kline_data_tencent(code, days=80) 
                
                # 防御2：未拿到数据 (可能是网络被封，或者代码在腾讯API里查不到)
                if hist.empty:
                    debug_logs.append(f"⚠️ {name} ({code}): 接口返回空数据 (可能查无此股或IP被限流)")
                    continue
                
                # 防御3：拿到数据但天数不够算60日均线
                if len(hist) < 60:
                    debug_logs.append(f"⚠️ {name} ({code}): 停牌或上市太短，仅 {len(hist)} 天K线，不足60天")
                    continue
                    
                # ============= 正常计算逻辑 =============
                try:
                    df = calculate_indicators(hist)
                    latest = df.iloc[-1]
                    
                    price_20d_ago = df.iloc[-20]['Close']
                    gain_20d = (latest['Close'] - price_20d_ago) / price_20d_ago * 100
                    rps_score = max(0, min(100, (gain_20d + 10) * 4)) 
                    
                    vol_ratio = latest['Volume'] / latest['VMA20'] if latest['VMA20'] > 0 else 0
                    activity_score = max(0, min(100, vol_ratio * 33))
                    
                    limit_up_days = len(df[ (df['Close'] - df['Close'].shift(1))/df['Close'].shift(1) > 0.09 ])
                    if limit_up_days >= 2: stock_char_score = 100
                    elif limit_up_days == 1: stock_char_score = 60
                    else: stock_char_score = 20
                        
                    high_low_ratio = df['High'] / df['Low'] - 1
                    avg_volatility = high_low_ratio.tail(20).mean() * 100
                    steady_score = max(0, min(100, 100 - (avg_volatility - 3) * 20))
                    
                    final_score = (rps_score + activity_score + stock_char_score) / 3
                    
                    scored_stocks.append({
                        "代码": code, "名称": name,
                        "综合总分": round(final_score, 1),
                        "资金活跃分": round(activity_score, 1),
                        "趋势抗跌分": round(rps_score, 1),
                        "股性记忆分": round(stock_char_score, 1),
                    })
                except Exception as e:
                    debug_logs.append(f"❌ {name} ({code}): 指标计算抛出异常 {str(e)}")
                    
                progress_bar.progress((idx + 1) / total)
                time.sleep(0.1) # 增加延迟，防止被腾讯封IP
                
            progress_text.text("✅ 打分计算结束！")
            
            # 结果与诊断展示
            if scored_stocks:
                df_scores = pd.DataFrame(scored_stocks).sort_values(by="综合总分", ascending=False).reset_index(drop=True)
                st.success(f"🎯 提纯完成！成功为 {len(df_scores)} 只标的打分。")
                st.dataframe(df_scores.style.background_gradient(cmap='YlOrRd'), use_container_width=True)
            else:
                st.error(f"😭 全部失败！共尝试 {total} 只股票，未能产出任何结果。请看下方诊断报告：")
            
            # 显示诊断日志
            if debug_logs:
                with st.expander("🩺 深度诊断监控台 (点击查看为什么失败)", expanded=not scored_stocks):
                    st.write("以下是被跳过股票的详细原因：")
                    for log in debug_logs:
                        st.text(log)

elif mode == "🔍 阶段三：个股形态复诊":
    st.title("🔍 个股形态显微镜")
    code_input = st.text_input("📝 输入股票代码 (例如: 000001)", max_chars=6)
    if code_input and len(code_input) == 6:
        hist_data = fetch_kline_data_tencent(code_input, days=120)
        if not hist_data.empty:
            df = calculate_indicators(hist_data)
            st.line_chart(df[['Date', 'Close', 'MA10', 'MA20', 'MA60']].set_index('Date'))
        else:
            st.error("未能获取到该股票数据。")
