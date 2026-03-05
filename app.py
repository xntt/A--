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

# ================= 1. 新浪财经引擎：获取全市场 A 股名单 =================
def get_full_market_pool():
    """使用新浪财经接口，一页一页翻取全市场A股名单，绝对防封禁"""
    pool = []
    # 沪深A股总数大概在 5100 只左右，每页 100 只，大概需要翻 55 页
    # 设定最大翻页为 65 页，遇到空数据自动停止
    for page in range(1, 65):
        url = f"http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page={page}&num=100&sort=symbol&asc=1&node=hs_a"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        try:
            res = requests.get(url, headers=headers, timeout=5).text
            if not res or res == 'null' or res == '[]':
                break # 翻到最后一页了，跳出循环
                
            # 新浪返回的JSON键值没有双引号，Python无法直接解析，需要用正则修复
            fixed_text = re.sub(r'([{,])\s*([a-zA-Z_0-9]+)\s*:', r'\1"\2":', res)
            stocks = json.loads(fixed_text)
            
            if not stocks:
                break
                
            for s in stocks:
                code = s.get("symbol", "")  # 格式如 sh600000, sz000001
                name = s.get("name", "未知")
                # 核心过滤逻辑：不要 ST、*ST、退市整理期股票
                if "ST" in name or "退" in name:
                    continue
                pool.append({"代码": code, "名称": name})
                
        except Exception as e:
            # 容错处理：如果某一页网络卡顿，忽略当前页继续
            continue
            
    return pool

# ================= 2. 腾讯财经引擎：获取极速 K 线 (自带前复权) =================
def fetch_kline_data_tencent(symbol, days=150):
    """获取K线，至少需要150天数据以计算准确的60日均线"""
    s = str(symbol).strip().lower()
    # 兼容处理：如果只输入了6位数字，自动加上sh/sz前缀
    if len(s) == 6 and s.isdigit():
        if s.startswith('6'): s = 'sh' + s
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
    fig.update_layout(title=f"个股 {name} 走势诊断图", yaxis_title='价格', xaxis_rangeslider_visible=False, height=500, margin=dict(l=0, r=0, t=40, b=0))
    return fig

# ================= 5. 主程序与 UI =================
def main():
    st.sidebar.title("📡 量化潜伏雷达")
    st.sidebar.caption("纯 新浪+腾讯 慢速扫描引擎")
    st.sidebar.markdown("---")
    
    mode = st.sidebar.radio("选择工作模式：", ["🎯 全市场潜伏雷达 (核心)", "🔍 个股形态复诊"])
    
    if mode == "🎯 全市场潜伏雷达 (核心)":
        st.title("🎯 全市场潜伏挖掘引擎")
        st.markdown("""
        **逻辑说明**：利用【新浪】获取全网名单，利用【腾讯】计算个股形态。  
        寻找**主力洗盘结束点**或**底部刚启动**的标的。建议选用全市场模式挂机运行。
        """)
        
        c1, c2 = st.columns(2)
        with c1:
            scan_scope = st.selectbox("1. 扫描范围 (耗时预估)：", [
                "快速试运行 (随机抽100只，约 1 分钟)",
                "全市场盲扫 (约 5000只，需 30~40 分钟) - 推荐"
            ])
        with c2:
            strategy = st.selectbox("2. 核心潜伏策略：", [
                "【趋势低吸】60日线向上，缩量回踩20日线附近", 
                "【底部启动】长期横盘，今日放量长阳突破60日线", 
                "【稳健波段】股价在20日线上，MACD零轴附近刚金叉"
            ])
            
        if st.button("🚀 启动全市场雷达", type="primary", use_container_width=True):
            
            with st.spinner("📡 正在呼叫新浪财经，一页页翻取全市场 A 股名单并清洗垃圾股 (大概需要5~10秒)..."):
                market_stocks = get_full_market_pool()
            
            if not market_stocks:
                st.error("数据拉取失败，请检查网络或重试。")
                return
                
            if "快速试运行" in scan_scope:
                market_stocks = market_stocks[:100] # 只取前100个测试
                
            total_stocks = len(market_stocks)
            st.success(f"✅ 名单获取完毕，共成功锁定 {total_stocks} 只标的。开始接通腾讯云端穿透扫描...")
            
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
                
                # 拉取数据 (腾讯)
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
                        # 把代码前缀sh/sz去掉，方便用户去同花顺搜
                        clean_code = code.replace("sh", "").replace("sz", "")
                        found_stocks.append({
                            "股票代码": clean_code,
                            "股票名称": name,
                            "最新价格": round(latest['Close'], 2),
                            "入选核心逻辑": reason
                        })
                        # 每发现一只，立刻实时更新展示表格
                        result_placeholder.dataframe(pd.DataFrame(found_stocks), use_container_width=True)
                
                # 更新进度条
                progress_bar.progress((i + 1) / total_stocks)
                
                # 核心防封锁机制：强制睡眠 0.4 秒 (给腾讯服务器喘息时间)
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
                    c4.metric("今日量能比", f"{vol_ratio:.1f} 倍", 
                              delta="放量" if vol_ratio > 1 else "缩量", 
                              delta_color="normal" if vol_ratio > 1 else "inverse")
                    
                    st.plotly_chart(plot_stock_chart(hist, symbol), use_container_width=True)

if __name__ == "__main__":
    main()
