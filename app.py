import streamlit as st
import pandas as pd
import requests
import json
import re
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import time
import math

st.set_page_config(page_title="量化潜伏雷达 | 全市场扫描版", page_icon="📡", layout="wide")

# ================= 0. 初始化全局记忆状态 (核心断点续传机制) =================
if "scan_status" not in st.session_state:
    st.session_state.scan_status = "idle"  # 状态: idle, running, paused, completed
if "current_index" not in st.session_state:
    st.session_state.current_index = 0     # 当前扫描到的索引位置
if "market_stocks" not in st.session_state:
    st.session_state.market_stocks = []    # 全市场股票池缓存
if "found_stocks" not in st.session_state:
    st.session_state.found_stocks = []     # 已挖掘到的牛股缓存
if "current_strategy" not in st.session_state:
    st.session_state.current_strategy = "" # 缓存当前正在执行的策略

# ================= 1. 新浪财经引擎：获取全市场 A 股名单 =================
def get_full_market_pool():
    """使用新浪财经接口，一页一页翻取全市场A股名单，绝对防封禁"""
    pool = []
    for page in range(1, 65):
        url = f"http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page={page}&num=100&sort=symbol&asc=1&node=hs_a"
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            res = requests.get(url, headers=headers, timeout=5).text
            if not res or res == 'null' or res == '[]':
                break
                
            fixed_text = re.sub(r'([{,])\s*([a-zA-Z_0-9]+)\s*:', r'\1"\2":', res)
            stocks = json.loads(fixed_text)
            
            if not stocks: break
                
            for s in stocks:
                code = s.get("symbol", "")
                name = s.get("name", "未知")
                if "ST" in name or "退" in name:
                    continue
                pool.append({"代码": code, "名称": name})
        except Exception:
            continue # 遇到单页报错忽略，继续下一页
    return pool

# ================= 2. 腾讯财经引擎：获取极速 K 线 =================
def fetch_kline_data_tencent(symbol, days=150):
    s = str(symbol).strip().lower()
    if len(s) == 6 and s.isdigit():
        if s.startswith('6'): s = 'sh' + s
        else: s = 'sz' + s
        
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={s},day,,,{days},qfq"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        res = requests.get(url, headers=headers, timeout=5).json()
        if res.get("code") != 0 or s not in res.get("data", {}): return pd.DataFrame()
        stock_data = res["data"][s]
        klines = stock_data.get("qfqday", stock_data.get("day", []))
        
        data = [{"Date": k[0], "Open": float(k[1]), "Close": float(k[2]), "High": float(k[3]), "Low": float(k[4]), "Volume": float(k[5])} for k in klines]
        df = pd.DataFrame(data)
        df['Date'] = pd.to_datetime(df['Date'])
        df.set_index('Date', inplace=True)
        return df
    except Exception:
        return pd.DataFrame()

# ================= 3. 技术指标计算 =================
def calculate_indicators(df):
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA60'] = df['Close'].rolling(window=60).mean()
    df['VMA5'] = df['Volume'].rolling(window=5).mean()
    df['VMA20'] = df['Volume'].rolling(window=20).mean()
    df['EMA12'] = df['Close'].ewm(span=12, adjust=False).mean()
    df['EMA26'] = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = df['EMA12'] - df['EMA26']
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    return df

# ================= 4. 个股绘图引擎 =================
def plot_stock_chart(df, name):
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
    fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K线'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], line=dict(color='orange', width=1.5), name='MA20'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA60'], line=dict(color='blue', width=1.5), name='MA60(生命线)'), row=1, col=1)
    colors = ['red' if row['Close'] >= row['Open'] else 'green' for index, row in df.iterrows()]
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=colors, name='成交量'), row=2, col=1)
    fig.update_layout(title=f"个股 {name} 走势诊断图", yaxis_title='价格', xaxis_rangeslider_visible=False, height=500, margin=dict(l=0, r=0, t=40, b=0))
    return fig

# ================= 5. 主程序与 UI =================
def main():
    st.sidebar.title("📡 量化潜伏雷达")
    st.sidebar.caption("纯 新浪+腾讯 | 支持断点续传")
    st.sidebar.markdown("---")
    
    mode = st.sidebar.radio("选择工作模式：", ["🎯 全市场潜伏雷达 (核心)", "🔍 个股形态复诊"])
    
    if mode == "🎯 全市场潜伏雷达 (核心)":
        st.title("🎯 全市场潜伏挖掘引擎")
        st.markdown("**具备断点续传能力**：即使网络中断或手动暂停，进度与结果绝不丢失！")
        
        # 顶部控制面板
        with st.container():
            c1, c2 = st.columns(2)
            with c1:
                scan_scope = st.selectbox("1. 扫描范围 (启动全新扫描时生效)：", ["全市场盲扫 (约 5000只)", "快速试运行 (随机抽100只)"])
            with c2:
                strategy = st.selectbox("2. 核心潜伏策略：", [
                    "【趋势低吸】60日线向上，缩量回踩20日线附近", 
                    "【底部启动】长期横盘，今日放量长阳突破60日线", 
                    "【稳健波段】股价在20日线上，MACD零轴附近刚金叉"
                ])
                
            # 按钮控制区
            col_start, col_resume, col_stop = st.columns(3)
            
            btn_start = col_start.button("🚀 启动全新扫描", type="primary", use_container_width=True)
            
            # 判断是否显示"继续扫描"按钮
            can_resume = len(st.session_state.market_stocks) > 0 and st.session_state.current_index < len(st.session_state.market_stocks)
            btn_resume = col_resume.button("▶️ 继续上次扫描", type="secondary", use_container_width=True, disabled=not can_resume)
            
            # 暂停按钮 (其实Streamlit的任何按钮点击都会强制rerun，从而安全中断当前循环)
            btn_stop = col_stop.button("⏸ 暂停当前扫描", use_container_width=True)
        
        st.markdown("---")

        # 状态指示器
        total = len(st.session_state.market_stocks)
        curr = st.session_state.current_index
        found_cnt = len(st.session_state.found_stocks)
        
        if total > 0:
            st.info(f"📊 当前任务库状态: 已扫描 {curr} / {total} 只标的 | 💡 已挖掘到 {found_cnt} 黄金坑标的 | 策略: {st.session_state.current_strategy}")
            st.progress(curr / total if total > 0 else 0)
            
        # 结果持久化展示区 (无论是否在扫描，始终显示结果)
        st.subheader("🏆 黄金坑标的池 (扫描结果安全缓存)")
        result_placeholder = st.empty()
        if found_cnt > 0:
            result_placeholder.dataframe(pd.DataFrame(st.session_state.found_stocks), use_container_width=True)
        else:
            result_placeholder.info("当前记忆库中暂无结果。请启动扫描...")

        # 动作逻辑处理
        if btn_stop:
            st.session_state.scan_status = "paused"
            st.warning("⚠️ 扫描已安全暂停！进度和结果已保存，可随时点击【继续上次扫描】恢复。")
            st.stop() # 终止代码继续执行

        if btn_start:
            st.session_state.scan_status = "running"
            st.session_state.current_index = 0
            st.session_state.found_stocks = []
            st.session_state.current_strategy = strategy
            
            with st.spinner("📡 正在获取全新全市场 A 股名单..."):
                market_stocks = get_full_market_pool()
                if "快速试运行" in scan_scope: market_stocks = market_stocks[:100]
                st.session_state.market_stocks = market_stocks
            
            if not st.session_state.market_stocks:
                st.error("数据拉取失败，请检查网络或重试。")
                st.stop()
                
            # 触发重新渲染，进入扫描阶段
            st.rerun()

        if btn_resume:
            st.session_state.scan_status = "running"
            st.rerun()

        # 核心扫描循环 (只在状态为 running 时执行)
        if st.session_state.scan_status == "running":
            total_stocks = len(st.session_state.market_stocks)
            strategy_to_run = st.session_state.current_strategy
            
            status_text = st.empty()
            
            # 从记忆的断点位置开始循环
            for i in range(st.session_state.current_index, total_stocks):
                stock = st.session_state.market_stocks[i]
                code = stock['代码']
                name = stock['名称']
                
                status_text.text(f"🔍 正在雷达扫描: {name} ({code}) ... [进度 {i+1}/{total_stocks}]")
                
                try:
                    hist = fetch_kline_data_tencent(code)
                    
                    if not hist.empty and len(hist) > 65:
                        hist = calculate_indicators(hist)
                        latest = hist.iloc[-1]
                        prev = hist.iloc[-2]
                        
                        is_match = False
                        reason = ""
                        
                        # ================= 策略引擎 =================
                        if strategy_to_run == "【趋势低吸】60日线向上，缩量回踩20日线附近":
                            ma60_up = latest['MA60'] > prev['MA60']
                            ma20_above_60 = latest['MA20'] > latest['MA60']
                            price_near_ma20 = abs(latest['Close'] - latest['MA20']) / latest['MA20'] < 0.02
                            volume_shrink = latest['Volume'] < latest['VMA5']
                            if ma60_up and ma20_above_60 and price_near_ma20 and volume_shrink:
                                is_match, reason = True, f"偏离MA20仅 {(abs(latest['Close']-latest['MA20'])/latest['MA20']*100):.1f}% 且缩量"

                        elif strategy_to_run == "【底部启动】长期横盘，今日放量长阳突破60日线":
                            breakout = prev['Close'] < prev['MA60'] and latest['Close'] > latest['MA60']
                            big_yang = latest['Close'] > latest['Open'] * 1.03
                            volume_surge = latest['Volume'] > latest['VMA20'] * 2
                            if breakout and big_yang and volume_surge:
                                is_match, reason = True, "底部放巨量过60日生命线"

                        elif strategy_to_run == "【稳健波段】股价在20日线上，MACD零轴附近刚金叉":
                            price_ok = latest['Close'] > latest['MA20']
                            near_zero = abs(latest['MACD']) / latest['Close'] * 100 < 1.0 
                            just_cross = prev['MACD'] <= prev['Signal'] and latest['MACD'] > latest['Signal']
                            if price_ok and near_zero and just_cross:
                                is_match, reason = True, "水面(零轴)MACD初次金叉"

                        # 命中记录存入全局记忆
                        if is_match:
                            clean_code = code.replace("sh", "").replace("sz", "")
                            st.session_state.found_stocks.append({
                                "股票代码": clean_code, "股票名称": name, 
                                "最新价格": round(latest['Close'], 2), "入选核心逻辑": reason
                            })
                            # 实时刷新下方表格
                            result_placeholder.dataframe(pd.DataFrame(st.session_state.found_stocks), use_container_width=True)
                
                except Exception as e:
                    # 如果腾讯接口因为网络抖动报错，安全暂停，不丢失进度
                    st.session_state.scan_status = "paused"
                    st.error(f"⚠️ 网络连接异常打断 ({name})，进度已保存。请稍后点击【继续上次扫描】恢复。")
                    st.stop()

                # 每成功扫完一只，记忆下标位置 +1
                st.session_state.current_index = i + 1
                
                # 防封锁休息机制
                time.sleep(0.4)
                
            # 循环全部顺利结束
            st.session_state.scan_status = "completed"
            status_text.text("✅ 全市场扫描任务圆满结束！所有数据均已保留在下方表格中。")
            st.balloons()
            st.success(f"🎉 淘金彻底完成！本次共为你挖掘到 {len(st.session_state.found_stocks)} 只牛股。")
            st.rerun() # 最后刷新一下UI状态隐藏"继续"按钮

    elif mode == "🔍 个股形态复诊":
        # ... (保持原样的复诊代码)
        st.title("🔍 个股复诊中心 (含60日生命线)")
        st.markdown("将雷达扫出来的代码输入到这里，验证其技术形态是否真的符合你的眼缘。")
        col1, col2 = st.columns([3, 1])
        with col1:
            t_input = st.text_input("请输入 6 位纯数字代码 (如 600519):", "000001")
        with col2:
            st.write(""); st.write("")
            btn = st.button("查看个股诊断图", type="primary", use_container_width=True)
            
        if btn and t_input.strip():
            symbol = t_input.strip()
            with st.spinner('正在从腾讯云端拉取深度数据...'):
                hist = fetch_kline_data_tencent(symbol)
                if hist.empty or len(hist) < 65:
                    st.error(f"❌ 查无此股，或该股上市不足 60 天无足够数据。")
                else:
                    hist = calculate_indicators(hist)
                    latest = hist.iloc[-1]
                    st.success(f"✅ 成功生成【代码: {symbol}】的诊断报告")
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("最新价", f"¥ {latest['Close']:.2f}")
                    c2.metric("20日线 (波段线)", f"¥ {latest['MA20']:.2f}")
                    c3.metric("60日线 (生命线)", f"¥ {latest['MA60']:.2f}")
                    vol_ratio = latest['Volume'] / latest['VMA5']
                    c4.metric("今日量能比", f"{vol_ratio:.1f} 倍", delta="放量" if vol_ratio > 1 else "缩量", delta_color="normal" if vol_ratio > 1 else "inverse")
                    st.plotly_chart(plot_stock_chart(hist, symbol), use_container_width=True)

if __name__ == "__main__":
    main()
