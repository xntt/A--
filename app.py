import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime
import concurrent.futures
import numpy as np

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
    # 均线
    df['MA5'] = df['Close'].rolling(window=5).mean()
    df['MA10'] = df['Close'].rolling(window=10).mean()
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA60'] = df['Close'].rolling(window=60).mean()
    # 量能均线
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
    st.markdown("系统将扫描全市场 5000 只股票，通过纯技术形态找出初步符合条件的标的，并缓存进入第二阶段。")
    
    strategy = st.radio("选择海选策略底层逻辑：", [
        "1️⃣ 趋势低吸 (20日线极度缩量回踩)",
        "2️⃣ 底部启动 (长期横盘后首日放量突破)",
        "3️⃣ 稳健波段 (均线多头排列，温和放量向上)"
    ])
    
    if st.button("🚀 启动全市场粗筛 (耗时约 5-10 分钟)", type="primary"):
        st.session_state.current_strategy = strategy
        st.session_state.found_stocks = [] # 清空上次记录
        
        all_stocks = fetch_all_stock_codes()
        total_stocks = len(all_stocks)
        
        if total_stocks == 0:
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
            
            # 策略1：趋势低吸 (回踩20日线 + 极度缩量)
            if "趋势低吸" in strategy:
                if (latest['MA20'] > latest['MA60'] and 
                    abs(latest['Close'] - latest['MA20']) / latest['MA20'] < 0.02 and 
                    latest['Volume'] < latest['VMA5'] * 0.7):
                    is_match = True
                    logic_reason = "均线多头，精准回踩20日线且极度缩量"
            
            # 策略2：底部启动 (放量突破)
            elif "底部启动" in strategy:
                if (latest['Close'] > latest['MA60'] and prev1['Close'] <= prev1['MA60'] and 
                    latest['Volume'] > latest['VMA20'] * 2.5):
                    is_match = True
                    logic_reason = "底部巨量突破60日生命线"
            
            # 策略3：稳健波段 (温和上行)
            elif "稳健波段" in strategy:
                if (latest['MA5'] > latest['MA10'] > latest['MA20'] > latest['MA60'] and 
                    latest['Close'] > latest['MA5'] and 
                    latest['Volume'] > latest['VMA5']):
                    is_match = True
                    logic_reason = "均线完美多头，温和放量沿5日线上涨"
            
            if is_match:
                return {"股票代码": code, "股票名称": name, "当前价": latest['Close'], "入选核心逻辑": logic_reason}
            return None

        # 多线程扫描
        processed_count = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_stock = {executor.submit(process_stock, stock): stock for stock in all_stocks[:2000]} # 测试期可把2000改小以加快速度
            for future in concurrent.futures.as_completed(future_to_stock):
                processed_count += 1
                result = future.result()
                if result:
                    found_list.append(result)
                
                if processed_count % 20 == 0:
                    progress_bar.progress(processed_count / 2000) # 若上面改了，这里也要改
                    status_text.text(f"📡 正在扫描... 已处理 {processed_count} / 2000，已发现 {len(found_list)} 只符合形态")
        
        st.session_state.found_stocks = found_list
        progress_bar.progress(1.0)
        status_text.success(f"✅ 海选完成！共扫出 {len(found_list)} 只基础标的。请前往左侧边栏进入【阶段二】进行深度打分！")
        
        if found_list:
            st.dataframe(pd.DataFrame(found_list), use_container_width=True)
            elif mode == "🏆 阶段二：深度过滤与打分 (精选)":
    st.title("🏆 量化多维打分中心 (动态权重)")
    st.markdown("基于不同策略的底层逻辑，对粗筛池中的标的进行**多因子打分**，只选 Top 10 的精华。")
    
    if not st.session_state.found_stocks:
        st.warning("⚠️ 当前缓存池为空！请先去【阶段一】运行全市场扫描，拿到基础名单后再来这里打分。")
        st.stop()
        
    df_found = pd.DataFrame(st.session_state.found_stocks)
    st.info(f"📂 当前缓存池中共有 **{len(df_found)}** 只待检标的。它们来自策略：**{st.session_state.current_strategy}**")
    
    with st.expander("👀 查看原始待检名单", expanded=False):
        st.dataframe(df_found, use_container_width=True)
        
    st.markdown("---")
    
    if st.button("🚀 启动多因子深度打分 (智能匹配当前策略权重)", type="primary", use_container_width=True):
        scored_stocks = []
        strategy = st.session_state.current_strategy
        
        progress_text = st.empty()
        progress_bar = st.progress(0)
        total = len(st.session_state.found_stocks)
        
        for idx, stock in enumerate(st.session_state.found_stocks):
            code = str(stock['股票代码']).zfill(6)
            name = stock['股票名称']
            progress_text.text(f"🔬 正在深度剖析: {name} ({code}) ... [{idx+1}/{total}]")
            
            hist = fetch_kline_data_tencent(code, days=80) 
            
            if not hist.empty and len(hist) > 60:
                df = calculate_indicators(hist)
                latest = df.iloc[-1]
                
                # ================= 1. 计算通用因子得分 (满分100) =================
                # 因子A: RPS 抗跌相对强度 (近20日涨幅)
                price_20d_ago = df.iloc[-20]['Close']
                gain_20d = (latest['Close'] - price_20d_ago) / price_20d_ago * 100
                rps_score = max(0, min(100, (gain_20d + 10) * 4)) 
                
                # 因子B: 资金活跃度 (今日量能对比 20日均量)
                vol_ratio = latest['Volume'] / latest['VMA20'] if latest['VMA20'] > 0 else 0
                activity_score = max(0, min(100, vol_ratio * 33))
                
                # 因子C: 股性与连板记忆 (近60天内是否有过 9% 以上的涨停)
                limit_up_days = len(df[ (df['Close'] - df['Close'].shift(1))/df['Close'].shift(1) > 0.09 ])
                if limit_up_days >= 2: stock_char_score = 100
                elif limit_up_days == 1: stock_char_score = 60
                else: stock_char_score = 20
                    
                # 因子D: 稳健度 (近期振幅)
                high_low_ratio = df['High'] / df['Low'] - 1
                avg_volatility = high_low_ratio.tail(20).mean() * 100
                steady_score = max(0, min(100, 100 - (avg_volatility - 3) * 20))
                
                # ================= 2. 根据策略进行动态权重分配 =================
                final_score = 0
                if "趋势低吸" in strategy:
                    final_score = rps_score * 0.5 + stock_char_score * 0.3 + activity_score * 0.2
                elif "底部启动" in strategy:
                    final_score = activity_score * 0.6 + stock_char_score * 0.3 + rps_score * 0.1
                elif "稳健波段" in strategy:
                    final_score = steady_score * 0.5 + rps_score * 0.4 + activity_score * 0.1
                else:
                    final_score = (rps_score + activity_score + stock_char_score) / 3

                scored_stocks.append({
                    "代码": code,
                    "名称": name,
                    "综合总分": round(final_score, 1),
                    "资金活跃分": round(activity_score, 1),
                    "趋势抗跌分": round(rps_score, 1),
                    "股性记忆分": round(stock_char_score, 1),
                    "入选逻辑": stock['入选核心逻辑']
                })
            
            progress_bar.progress((idx + 1) / total)
            time.sleep(0.05) # 保护接口不过载
            
        progress_text.text("✅ 打分完毕！正在生成精华战报...")
        
        # ================= 3. 结果排序与展示 =================
        if scored_stocks:
            df_scores = pd.DataFrame(scored_stocks)
            df_scores = df_scores.sort_values(by="综合总分", ascending=False).reset_index(drop=True)
            
            st.success(f"🎯 过滤完成！从 {total} 只初选股中，为你提纯出以下精华标的。")
            st.subheader("🔥 终极潜伏目标 (Top 10)")
            
            top_3 = df_scores.head(3)
            cols = st.columns(3)
            for i, row in top_3.iterrows():
                with cols[i]:
                    st.metric(label=f"🥇 Top {i+1}: {row['名称']} ({row['代码']})", 
                              value=f"{row['综合总分']} 分", 
                              delta=f"资金分: {row['资金活跃分']} | 股性分: {row['股性记忆分']}")
            
            st.markdown("---")
            st.write("📋 **完整打分排行榜 (分数越高背景越红)**")
            
            # 热力图展示机制
            try:
                st.dataframe(
                    df_scores.style.background_gradient(
                        subset=['综合总分', '资金活跃分', '趋势抗跌分', '股性记忆分'], 
                        cmap='YlOrRd'
                    ),
                    use_container_width=True
                )
            except Exception:
                # 防止由于某些pandas版本不支持样式导致的报错白屏
                st.dataframe(df_scores, use_container_width=True)
                
            st.info("💡 拿着高分股票的代码，去左侧边栏【阶段三：个股形态复诊】查看最终图形吧！")
        else:
            st.error("计算异常，未生成有效打分。可能是网络中断导致。")

elif mode == "🔍 阶段三：个股形态复诊":
    st.title("🔍 个股形态显微镜")
    st.markdown("输入在阶段二中得分较高的股票代码，进行最终的人工看图确认。")
    
    code_input = st.text_input("📝 输入股票代码 (例如: 000001)", max_chars=6)
    
    if code_input and len(code_input) == 6:
        st.write(f"正在拉取 {code_input} 的最新数据...")
        hist_data = fetch_kline_data_tencent(code_input, days=120)
        
        if not hist_data.empty:
            df = calculate_indicators(hist_data)
            
            # 使用 Streamlit 原生折线图展示 K 线趋势和均线
            st.subheader("📈 价格与均线趋势图")
            chart_data = df[['Date', 'Close', 'MA10', 'MA20', 'MA60']].set_index('Date')
            st.line_chart(chart_data)
            
            # 量能展示
            st.subheader("📊 成交量趋势")
            vol_data = df[['Date', 'Volume', 'VMA5', 'VMA20']].set_index('Date')
            st.bar_chart(df[['Date', 'Volume']].set_index('Date'))
            
            st.write("📋 **最近 5 天详细数据**")
            st.dataframe(df.tail(5)[['Date', 'Open', 'Close', 'High', 'Low', 'Volume', 'MA20']], use_container_width=True)
        else:
            st.error("未能获取到该股票的数据，请检查代码是否正确。")
