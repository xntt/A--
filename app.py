import streamlit as st
import pandas as pd
import requests
import time
import concurrent.futures
from datetime import datetime

# 必须放在所有 st 命令的最前面
st.set_page_config(page_title="量化交易雷达系统", layout="wide")

# 初始化缓存状态
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
        # 过滤掉北交所和ST股
        valid_stocks = [s for s in stocks if not s['f14'].startswith('ST') and not s['f14'].startswith('*ST')]
        return valid_stocks
    except Exception as e:
        st.error(f"获取股票列表失败: {e}")
        return []

def fetch_kline_data_tencent(stock_code, days=100):
    prefix = 'sh' if str(stock_code).startswith('6') else 'sz'
    full_code = f"{prefix}{stock_code}"
    url = f"http://data.gtimg.cn/flashdata/hushen/latest/daily/{full_code}.js"
    try:
        response = requests.get(url, timeout=3)
        if response.status_code == 200:
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
    if df.empty or len(df) < 60:
        return df
    df['MA5'] = df['Close'].rolling(window=5).mean()
    df['MA10'] = df['Close'].rolling(window=10).mean()
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA60'] = df['Close'].rolling(window=60).mean()
    df['VMA5'] = df['Volume'].rolling(window=5).mean()
    df['VMA20'] = df['Volume'].rolling(window=20).mean()
    return df

# ================= 侧边栏与导航 =================
st.sidebar.title("⚡ 智能量化交易工作流")
mode = st.sidebar.radio("选择工作流阶段：", [
    "🎯 阶段一：全市场海选 (粗筛)", 
    "🏆 阶段二：深度过滤与打分 (精选)", 
    "🔍 阶段三：个股形态复诊"
])

# ================= 主程序逻辑 =================

if mode == "🎯 阶段一：全市场海选 (粗筛)":
    st.title("🎯 全市场潜伏雷达 (阶段一：海选)")
    st.markdown("系统将扫描全市场股票，找出初步符合形态的标的。支持**扫描后下载**以便日后复用！")
    
    strategy = st.radio("选择海选策略底层逻辑：", [
        "1️⃣ 趋势低吸 (20日线极度缩量回踩)",
        "2️⃣ 底部启动 (长期横盘后首日放量突破)",
        "3️⃣ 稳健波段 (均线多头排列，温和放量向上)"
    ])
    
    if st.button("🚀 启动全市场粗筛", type="primary"):
        st.session_state.current_strategy = strategy
        st.session_state.found_stocks = [] 
        
        all_stocks = fetch_all_stock_codes()
        if not all_stocks:
            st.stop()
            
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
            
            logic_reason = ""
            is_match = False
            
            if "趋势低吸" in strategy:
                if (latest['MA20'] > latest['MA60'] and 
                    abs(latest['Close'] - latest['MA20']) / latest['MA20'] < 0.02 and 
                    latest['Volume'] < latest['VMA5'] * 0.7):
                    is_match = True
                    logic_reason = "均线多头，精准回踩20日线且极度缩量"
            
            elif "底部启动" in strategy:
                if (latest['Close'] > latest['MA60'] and prev1['Close'] <= prev1['MA60'] and 
                    latest['Volume'] > latest['VMA20'] * 2.5):
                    is_match = True
                    logic_reason = "底部巨量突破60日生命线"
            
            elif "稳健波段" in strategy:
                if (latest['MA5'] > latest['MA10'] > latest['MA20'] > latest['MA60'] and 
                    latest['Close'] > latest['MA5'] and 
                    latest['Volume'] > latest['VMA5']):
                    is_match = True
                    logic_reason = "均线完美多头，温和放量沿5日线上涨"
            
            if is_match:
                return {"股票代码": code, "股票名称": name, "当前价": latest['Close'], "入选核心逻辑": logic_reason}
            return None

        # ================= 扫描设置 =================
        # 若要测试，可以改成 test_stocks = all_stocks[:1000]
        test_stocks = all_stocks[:1000] 
        test_total = len(test_stocks)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_stock = {executor.submit(process_stock, stock): stock for stock in test_stocks} 
            for processed_count, future in enumerate(concurrent.futures.as_completed(future_to_stock), 1):
                result = future.result()
                if result:
                    found_list.append(result)
                
                if processed_count % 20 == 0:
                    progress_bar.progress(processed_count / test_total)
                    status_text.text(f"📡 正在扫描... 已处理 {processed_count} / {test_total}，已发现 {len(found_list)} 只符合形态")
        
        st.session_state.found_stocks = found_list
        progress_bar.progress(1.0)
        status_text.success(f"✅ 海选完成！共扫出 {len(found_list)} 只基础标的。")
        
    # === 新增：如果在 session 中有数据，无论是否刚扫完，都提供下载按钮 ===
    if st.session_state.found_stocks:
        df_result = pd.DataFrame(st.session_state.found_stocks)
        st.dataframe(df_result, use_container_width=True)
        
        # 将 DataFrame 转换为 utf-8-sig 的 CSV（Excel打开不乱码）
        csv_data = df_result.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="💾 下载本次海选结果 (CSV文件)",
            data=csv_data,
            file_name=f"海选基础池_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            type="primary"
        )
        st.info("💡 建议下载保存！以后可直接在【阶段二】上传此文件进行打分，无需重新扫描。")

elif mode == "🏆 阶段二：深度过滤与打分 (精选)":
    st.title("🏆 量化多维打分中心")
    st.markdown("基于不同策略的底层逻辑，对基础池进行**动态权重打分**。")
    
    # === 新增：数据来源选择器 ===
    data_source = st.radio("📂 请选择打分数据来源：", [
        "1️⃣ 使用当前系统刚扫描的缓存数据", 
        "2️⃣ 上传历史下载的海选结果文件 (.csv)"
    ], horizontal=True)
    
    # 逻辑分发：获取待打分的 DataFrame 和 策略
    df_to_score = pd.DataFrame()
    strategy_for_score = "尚未选择"
    ready_to_score = False

    if data_source.startswith("1️⃣"):
        if not st.session_state.found_stocks:
            st.warning("⚠️ 当前系统缓存为空！请先去【阶段一】运行扫描，或者选择上方【上传文件】。")
        else:
            df_to_score = pd.DataFrame(st.session_state.found_stocks)
            strategy_for_score = st.session_state.current_strategy
            ready_to_score = True
            st.success(f"已加载内存数据：共 {len(df_to_score)} 只标的。对应策略：{strategy_for_score}")

    elif data_source.startswith("2️⃣"):
        uploaded_file = st.file_uploader("📥 请上传阶段一下载的 .csv 文件", type=['csv'])
        if uploaded_file is not None:
            try:
                df_to_score = pd.read_csv(uploaded_file)
                # 兼容处理股票代码变成数字（如 1 变成 000001）
                if '股票代码' in df_to_score.columns:
                    df_to_score['股票代码'] = df_to_score['股票代码'].apply(lambda x: str(x).zfill(6))
                
                st.success(f"文件读取成功！共解析出 {len(df_to_score)} 只标的。")
                
                # 重新选择这批数据的策略
                strategy_for_score = st.selectbox("⚙️ 请选择这批股票原本对应的策略（用于精准匹配打分权重）：", [
                    "趋势低吸", "底部启动", "稳健波段"
                ])
                ready_to_score = True
                
                with st.expander("👀 查看上传的数据", expanded=False):
                    st.dataframe(df_to_score, use_container_width=True)
            except Exception as e:
                st.error(f"文件解析失败，请确保上传的是阶段一下载的源文件。错误详情：{e}")

    st.markdown("---")
    
    # === 打分引擎 ===
    if ready_to_score:
        if st.button("🚀 启动多因子深度打分 (智能匹配权重)", type="primary", use_container_width=True):
            scored_stocks = []
            progress_text = st.empty()
            progress_bar = st.progress(0)
            
            # 将 DataFrame 转回字典列表便于遍历
            stock_list = df_to_score.to_dict('records')
            total = len(stock_list)
            
            for idx, stock in enumerate(stock_list):
                code = str(stock.get('股票代码', '')).zfill(6)
                name = stock.get('股票名称', '未知')
                logic = stock.get('入选核心逻辑', '无')
                
                progress_text.text(f"🔬 正在深度剖析: {name} ({code}) ... [{idx+1}/{total}]")
                hist = fetch_kline_data_tencent(code, days=80) 
                
                if not hist.empty and len(hist) > 60:
                    df = calculate_indicators(hist)
                    latest = df.iloc[-1]
                    
                    # 因子A: RPS 抗跌
                    price_20d_ago = df.iloc[-20]['Close']
                    gain_20d = (latest['Close'] - price_20d_ago) / price_20d_ago * 100
                    rps_score = max(0, min(100, (gain_20d + 10) * 4)) 
                    
                    # 因子B: 资金活跃度
                    vol_ratio = latest['Volume'] / latest['VMA20'] if latest['VMA20'] > 0 else 0
                    activity_score = max(0, min(100, vol_ratio * 33))
                    
                    # 因子C: 股性与连板记忆
                    limit_up_days = len(df[ (df['Close'] - df['Close'].shift(1))/df['Close'].shift(1) > 0.09 ])
                    if limit_up_days >= 2: stock_char_score = 100
                    elif limit_up_days == 1: stock_char_score = 60
                    else: stock_char_score = 20
                        
                    # 因子D: 稳健度
                    high_low_ratio = df['High'] / df['Low'] - 1
                    avg_volatility = high_low_ratio.tail(20).mean() * 100
                    steady_score = max(0, min(100, 100 - (avg_volatility - 3) * 20))
                    
                    # 动态权重分配
                    final_score = 0
                    if "趋势低吸" in strategy_for_score:
                        final_score = rps_score * 0.5 + stock_char_score * 0.3 + activity_score * 0.2
                    elif "底部启动" in strategy_for_score:
                        final_score = activity_score * 0.6 + stock_char_score * 0.3 + rps_score * 0.1
                    elif "稳健波段" in strategy_for_score:
                        final_score = steady_score * 0.5 + rps_score * 0.4 + activity_score * 0.1
                    else:
                        final_score = (rps_score + activity_score + stock_char_score) / 3

                    scored_stocks.append({
                        "代码": code, "名称": name,
                        "综合总分": round(final_score, 1),
                        "资金活跃分": round(activity_score, 1),
                        "趋势抗跌分": round(rps_score, 1),
                        "股性记忆分": round(stock_char_score, 1),
                        "入选逻辑": logic
                    })
                
                progress_bar.progress((idx + 1) / total)
                time.sleep(0.05)
                
            progress_text.text("✅ 打分完毕！")
            
            # === 展示打分结果 ===
            if scored_stocks:
                df_scores = pd.DataFrame(scored_stocks).sort_values(by="综合总分", ascending=False).reset_index(drop=True)
                st.success(f"🎯 提纯完成！Top 10 精华标的如下：")
                
                cols = st.columns(3)
                for i, row in df_scores.head(3).iterrows():
                    with cols[i]:
                        st.metric(label=f"🥇 Top {i+1}: {row['名称']} ({row['代码']})", 
                                  value=f"{row['综合总分']} 分", 
                                  delta=f"资金分: {row['资金活跃分']} | 股性分: {row['股性记忆分']}")
                
                st.write("📋 **完整打分排行榜**")
                try:
                    st.dataframe(df_scores.style.background_gradient(subset=['综合总分', '资金活跃分', '趋势抗跌分', '股性记忆分'], cmap='YlOrRd'), use_container_width=True)
                except:
                    st.dataframe(df_scores, use_container_width=True)
            else:
                st.error("计算异常，未生成有效打分。")

elif mode == "🔍 阶段三：个股形态复诊":
    st.title("🔍 个股形态显微镜")
    st.markdown("输入在阶段二中得分较高的股票代码，进行最终的人工确认。")
    
    code_input = st.text_input("📝 输入股票代码 (例如: 000001)", max_chars=6)
    
    if code_input and len(code_input) == 6:
        hist_data = fetch_kline_data_tencent(code_input, days=120)
        if not hist_data.empty:
            df = calculate_indicators(hist_data)
            st.subheader("📈 价格与均线趋势")
            st.line_chart(df[['Date', 'Close', 'MA10', 'MA20', 'MA60']].set_index('Date'))
            st.subheader("📊 成交量趋势")
            st.bar_chart(df[['Date', 'Volume']].set_index('Date'))
        else:
            st.error("未能获取到该股票数据。")
