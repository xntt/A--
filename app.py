import streamlit as st
import pandas as pd
import requests
import json
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import time
import math

st.set_page_config(page_title="量化潜伏雷达 | 全市场扫描版", page_icon="📡", layout="wide")

# ================= 1. 获取全市场 A 股名单 (带清洗功能) =================
def get_full_market_pool():
    """一次性获取全市场5000多只股票，并剔除垃圾股"""
    # 东方财富全市场A股节点 (沪、深、京)
    url = "https://82.push2.eastmoney.com/api/qt/clist/get?pn=1&pz=6000&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048&fields=f12,f14"
    try:
        res = requests.get(url, timeout=10).json()
        stocks = res['data']['diff']
        pool = []
        for s in stocks:
            code = s['f12']
            name = s['f14']
            # 核心过滤逻辑：不要 ST、*ST、退市整理期
            if "ST" in name or "退" in name:
                continue
            pool.append({"代码": code, "名称": name})
        return pool
    except Exception as e:
        st.error(f"获取全市场名单失败: {e}")
        return []

# ================= 2. 腾讯财经 K 线引擎 (前复权) =================
def fetch_kline_data_tencent(symbol, days=150):
    """获取K线，至少需要150天数据以计算准确的60日均线"""
    s = str(symbol).strip().lower()
    if len(s) == 6 and s.isdigit():
        # 简单区分沪深京 (京股8或4开头，简单归入沪深处理逻辑或忽略，腾讯对bj前缀支持有限，这里兼容sh/sz)
        if s.startswith('6'): s = 'sh' + s
        elif s.startswith('8') or s.startswith('4'): s = 'bj' + s
        else: s = 'sz' + s
        
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={s},day,,,{days},qfq"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        res = requests.get(url, headers=headers, timeout=5).json()
        if res.get("code") != 0 or s not in res.get("data", {}):
            return pd.DataFrame()
            
        stock_data = res["data"][s]
        klines = stock_data.get("qfqday", stock_data.get("day", []))
        
        data = []
        for k in klines:
            data.append({
                "Date": k[0], "Open": float(k[1]), "Close": float(k[2]),
                "High": float(k[3]), "Low": float(k[4]), "Volume": float(k[5])
            })
            
        df = pd.DataFrame(data)
        df['Date'] = pd.to_datetime(df['Date'])
        df.set_index('Date', inplace=True)
        return df
    except Exception:
        return pd.DataFrame()

# ================= 3. 专业技术指标与策略计算 =================
def calculate_indicators(df):
    # 均线系统
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA60'] = df['Close'].rolling(window=60).mean()
    
    # 成交量均线
    df['VMA5'] = df['Volume'].rolling(window=5).mean()
    df['VMA20'] = df['Volume'].rolling(window=20).mean()
    
    # MACD系统
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
    fig.update_layout(title=f"{name} 走势诊断图", yaxis_title='价格', xaxis_rangeslider_visible=False, height=500, margin=dict(l=0, r=0, t=40, b=0))
    return fig

# ================= 5. 主程序与 UI =================
def main():
    st.sidebar.title("📡 量化潜伏雷达")
    st.sidebar.caption("全市场慢速扫描引擎 (杜绝追高，专做潜伏)")
    st.sidebar.markdown("---")
    
    mode = st.sidebar.radio("选择工作模式：", ["🎯 全市场潜伏雷达 (核心)", "🔍 个股形态复诊"])
    
    if mode == "🎯 全市场潜伏雷达 (核心)":
        st.title("🎯 全市场潜伏挖掘引擎")
        st.markdown("""
        **逻辑说明**：不再扫涨幅榜去接盘！本雷达将遍历A股5000多只股票，寻找**主力洗盘结束点**或**底部刚启动**的标的。
        为防封禁，每次请求间隔 0.5 秒。建议在盘后喝茶时间运行全市场扫描。
        """)
        
        c1, c2 = st.columns(2)
        with c1:
            scan_scope = st.selectbox("1. 扫描范围 (耗时预估)：", [
                "快速试运行 (随机抽100只，约 1 分钟)",
                "全市场盲扫 (约 5000只，需 40 分钟) - 推荐"
            ])
        with c2:
            strategy = st.selectbox("2. 核心潜伏策略：", [
                "【趋势低吸】60日线向上，缩量回踩20日线附近", 
                "【底部启动】长期横盘，今日放量长阳突破60日线", 
                "【稳健波段】股价在20日线上，MACD零轴附近刚金叉"
            ])
            
        if st.button("🚀 启动全市场雷达", type="primary", use_container_width=True):
            st.info("📡 正在获取全市场 A 股名单并清洗垃圾股 (ST/退市)...")
            market_stocks = get_full_market_pool()
            
            if not market_stocks:
                return
                
            if "快速试运行" in scan_scope:
                market_stocks = market_stocks[:100] # 只取前100个测试
                
            total_stocks = len(market_stocks)
            st.success(f"✅ 名单获取完毕，共 {total_stocks} 只标的进入雷达锁定。开始慢速穿透扫描...")
            
            # UI 元素占位
            progress_bar = st.progress(0)
            status_text = st.empty()
            time_text = st.empty()
            result_placeholder = st.empty()
            
            found_stocks = []
            start_time = time.time()
            
            for i, stock in enumerate(market_stocks):
                code = stock['代码']
                name = stock['名称']
                
                # 计算耗时与 ETA
                elapsed_time = time.time() - start_time
                if i > 0:
                    eta_seconds = (elapsed_time / i) * (total_stocks - i)
                    eta_mins = math.ceil(eta_seconds / 60)
                else:
                    eta_mins = "?"
                    
                status_text.text(f"🔍 正在扫描: {name} ({code}) ... [进度 {i+1}/{total_stocks}]")
                time_text.caption(f"⏱️ 已耗时: {math.ceil(elapsed_time/60)} 分钟 | 预计还需: {eta_mins} 分钟")
                
                # 拉取数据
                hist = fetch_kline_data_tencent(code)
                
                # 数据合规性检查 (上市必须大于 60 天才能算 MA60)
                if not hist.empty and len(hist) > 65:
                    hist = calculate_indicators(hist)
                    latest = hist.iloc[-1]
                    prev = hist.iloc[-2]
                    
                    is_match = False
                    reason = ""
                    
                    # =============== 核心量化策略引擎 ===============
                    
                    # 策略1: 趋势缩量回踩 (做上升趋势的洗盘结束点)
                    if strategy == "【趋势低吸】60日线向上，缩量回踩20日线附近":
                        ma60_up = latest['MA60'] > prev['MA60'] # 60日线向上
                        ma20_above_60 = latest['MA20'] > latest['MA60'] # 20日线在60日线上方
                        price_near_ma20 = abs(latest['Close'] - latest['MA20']) / latest['MA20'] < 0.02 # 股价在20日线上下2%以内
                        volume_shrink = latest['Volume'] < latest['VMA5'] # 今日成交量小于5日均量
                        
                        if ma60_up and ma20_above_60 and price_near_ma20 and volume_shrink:
                            is_match, reason = True, f"偏离MA20仅 {(abs(latest['Close'] - latest['MA20']) / latest['MA20']*100):.1f}% 且缩量"

                    # 策略2: 底部启动放量突破 (做长期横盘后的第一根大阳线)
                    elif strategy == "【底部启动】长期横盘，今日放量长阳突破60日线":
                        breakout = prev['Close'] < prev['MA60'] and latest['Close'] > latest['MA60'] # 昨天在水下，今天穿头
                        big_yang = latest['Close'] > latest['Open'] * 1.03 # 实体涨幅大于3%
                        volume_surge = latest['Volume'] > latest['VMA20'] * 2 # 成交量是20日均量的2倍以上
                        
                        if breakout and big_yang and volume_surge:
                            is_match, reason = True, "底部放巨量过60日生命线"

                    # 策略3: 稳健波段起点 (MACD在水面附近刚刚金叉)
                    elif strategy == "【稳健波段】股价在20日线上，MACD零轴附近刚金叉":
                        price_ok = latest['Close'] > latest['MA20'] # 保证不在极度弱势
                        # MACD在零轴附近 (相对值在正负1%以内)
                        near_zero = abs(latest['MACD']) / latest['Close'] * 100 < 1.0 
                        just_cross = prev['MACD'] <= prev['Signal'] and latest['MACD'] > latest['Signal'] # 刚刚金叉
                        
                        if price_ok and near_zero and just_cross:
                            is_match, reason = True, "水面(零轴)MACD初次金叉"

                    # 记录金股
                    if is_match:
                        found_stocks.append({
                            "股票代码": code,
                            "股票名称": name,
                            "最新价格": round(latest['Close'], 2),
                            "入选核心逻辑": reason
                        })
                        # 每发现一只，立刻实时更新展示表格
                        result_placeholder.dataframe(pd.DataFrame(found_stocks), use_container_width=True)
                
                # 更新进度条
                progress_bar.progress((i + 1) / total_stocks)
                
                # 核心防封锁机制：强制睡眠 0.4 秒 (模拟真人浏览)
                time.sleep(0.4)
                
            status_text.text("✅ 全市场扫描任务圆满结束！")
            time_text.empty()
            
            if found_stocks:
                st.balloons()
                st.success(f"🎉 淘金完成！在 {total_stocks} 只股票中，为你潜伏挖掘到 {len(found_stocks)} 只符合【{strategy}】形态的准牛股。请去同花顺重点加入自选观察！")
            else:
                st.warning("太苛刻了！今天全市场居然没有一只股票完美符合该策略的潜伏条件。说明今天大盘环境可能不适合该策略，建议空仓观望或更换策略。")


    elif mode == "🔍 个股形态复诊":
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
            with st.spinner('正在从云端拉取深度数据...'):
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
                    c4.metric("今日量能比", f"{vol_ratio:.1f} 倍", 
                              delta="放量" if vol_ratio > 1 else "缩量", 
                              delta_color="normal" if vol_ratio > 1 else "inverse")
                    
                    st.plotly_chart(plot_stock_chart(hist, f"个股 {symbol}"), use_container_width=True)

if __name__ == "__main__":
    main()
