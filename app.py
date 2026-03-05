import streamlit as st
import pandas as pd
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import time

st.set_page_config(page_title="自动化选股雷达", page_icon="📡", layout="wide")

# ================= 1. 全自动获取市场股票池 (你的核心需求) =================
def get_market_stock_pool(pool_type="活跃股榜"):
    """
    不需要用户输入代码，直接从东方财富抓取全市场实时股票列表
    """
    # 东方财富实时行情接口：抓取沪深A股数据
    # f62: 主力净流入, f3: 涨幅, f8: 换手率, f12: 代码, f14: 名称
    if pool_type == "高换手率榜(资金最活跃)":
        url = "https://82.push2.eastmoney.com/api/qt/clist/get?pn=1&pz=150&po=1&np=1&fltt=2&invt=2&fid=f8&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048&fields=f12,f14,f3"
    elif pool_type == "今日涨幅榜(强势股)":
        url = "https://82.push2.eastmoney.com/api/qt/clist/get?pn=1&pz=150&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048&fields=f12,f14,f3"
    else: # 默认大盘股
        url = "https://82.push2.eastmoney.com/api/qt/clist/get?pn=1&pz=150&po=1&np=1&fltt=2&invt=2&fid=f20&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048&fields=f12,f14,f3"

    try:
        res = requests.get(url, timeout=5).json()
        stocks = res['data']['diff']
        pool = []
        for s in stocks:
            code = s['f12']
            name = s['f14']
            pool.append({"代码": code, "名称": name})
        return pool
    except Exception as e:
        st.error(f"获取市场股票池失败: {e}")
        return []

# ================= 2. 底层 K 线数据获取 =================
def fetch_kline_data(symbol, days=100):
    """获取单只股票的K线数据用于计算指标"""
    s = str(symbol).strip()
    # 判断深市还是沪市
    if s.startswith('6'):
        secid = f"1.{s}"
    else:
        secid = f"0.{s}"
        
    url = f"https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&klt=101&fqt=1&end=20500101&lmt={days}"
    try:
        res = requests.get(url, timeout=3).json()
        if not res or "data" not in res or not res["data"] or not res["data"].get("klines"):
            return pd.DataFrame(), s
            
        klines = res["data"]["klines"]
        name = res["data"].get("name", s)
        
        data = []
        for k in klines:
            parts = k.split(',')
            data.append({
                "Date": parts[0], "Open": float(parts[1]), "Close": float(parts[2]),
                "High": float(parts[3]), "Low": float(parts[4]), "Volume": float(parts[5])
            })
            
        df = pd.DataFrame(data)
        df['Date'] = pd.to_datetime(df['Date'])
        df.set_index('Date', inplace=True)
        return df, name
    except:
        return pd.DataFrame(), s

# ================= 3. 技术指标算法 =================
def calculate_indicators(df):
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA50'] = df['Close'].rolling(window=50).mean()
    
    # MACD
    df['EMA12'] = df['Close'].ewm(span=12, adjust=False).mean()
    df['EMA26'] = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = df['EMA12'] - df['EMA26']
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    
    # RSI
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss.replace(0, 1e-5)
    df['RSI'] = 100 - (100 / (1 + rs))
    return df

# ================= 4. 个股绘图引擎 =================
def plot_stock_chart(df, name):
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
    fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K线'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], line=dict(color='orange', width=1.5), name='MA20'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA50'], line=dict(color='blue', width=1.5), name='MA50'), row=1, col=1)
    colors = ['red' if row['Close'] >= row['Open'] else 'green' for index, row in df.iterrows()]
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=colors, name='成交量'), row=2, col=1)
    fig.update_layout(title=f"{name} 走势分析图", yaxis_title='价格', xaxis_rangeslider_visible=False, height=500, margin=dict(l=0, r=0, t=40, b=0))
    return fig

# ================= 界面与主逻辑 =================
def main():
    st.sidebar.title("📡 全自动量化选股雷达")
    st.sidebar.markdown("---")
    
    # 将批量扫描作为默认的第一个功能，因为它才是核心！
    mode = st.sidebar.radio("选择工作模式：", ["🎯 全市场自动挖掘潜力股", "🔍 单只个股详细体检"])
    
    if mode == "🎯 全市场自动挖掘潜力股":
        st.title("🎯 全网智能挖掘引擎")
        st.markdown("不用再手动输入代码！系统将自动抓取当前A股最具活力的几百只股票，并从中找出符合你策略的【潜力金股】。")
        
        c1, c2 = st.columns(2)
        with c1:
            pool_choice = st.selectbox("1. 设定扫描雷达的搜索范围：", ["高换手率榜(资金最活跃)", "今日涨幅榜(强势股)", "大盘蓝筹(主力股)"])
        with c2:
            strategy = st.selectbox("2. 设定选股过滤策略：", [
                "MACD底部刚刚金叉 (启动信号)", 
                "均线多头排列且站上MA20 (趋势向上)", 
                "RSI极度超卖跌破30 (恐慌抄底)"
            ])
            
        if st.button(f"🚀 立即开始全网自动化扫描", type="primary", use_container_width=True):
            st.info(f"正在向东方财富请求【{pool_choice}】的最新名单...")
            market_stocks = get_market_stock_pool(pool_choice)
            
            if not market_stocks:
                st.error("无法获取市场数据，请稍后再试。")
                return
                
            st.success(f"✅ 成功获取 {len(market_stocks)} 只活跃股票作为样本池，开始逐一穿透扫描...")
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            found_stocks = []
            
            # 开始自动化扫描
            for i, stock in enumerate(market_stocks):
                code = stock['代码']
                name = stock['名称']
                status_text.text(f"正在计算: {name} ({code}) ... [进度 {i+1}/{len(market_stocks)}]")
                
                hist, _ = fetch_kline_data(code, days=60)
                if not hist.empty and len(hist) >= 50:
                    hist = calculate_indicators(hist)
                    latest = hist.iloc[-1]
                    prev = hist.iloc[-2]
                    
                    is_match = False
                    reason = ""
                    
                    # 策略判断引擎
                    if strategy == "MACD底部刚刚金叉 (启动信号)":
                        if latest['MACD'] > latest['Signal'] and prev['MACD'] <= prev['Signal'] and latest['MACD'] < 0:
                            is_match, reason = True, "水下MACD今日金叉"
                            
                    elif strategy == "均线多头排列且站上MA20 (趋势向上)":
                        if latest['Close'] > latest['MA20'] and latest['MA20'] > latest['MA50'] and latest['MA20'] > prev['MA20']:
                            is_match, reason = True, "站上20日线且均线发散向上"
                            
                    elif strategy == "RSI极度超卖跌破30 (恐慌抄底)":
                        if latest['RSI'] < 30:
                            is_match, reason = True, f"RSI低至 {latest['RSI']:.1f}"

                    # 如果这只股票符合条件，把它塞进聚宝盆
                    if is_match:
                        found_stocks.append({
                            "股票代码": code,
                            "股票名称": name,
                            "最新收盘价": round(latest['Close'], 2),
                            "入选核心原因": reason
                        })
                
                progress_bar.progress((i + 1) / len(market_stocks))
                
            status_text.text("✅ 雷达扫描完成！")
            
            if found_stocks:
                st.success(f"🎉 挖掘成功！在 {len(market_stocks)} 只股票中，为你找出 {len(found_stocks)} 只符合【{strategy}】的潜力股：")
                st.dataframe(pd.DataFrame(found_stocks), use_container_width=True)
                st.balloons()
            else:
                st.warning("非常遗憾，当前市场池中没有符合该苛刻策略的股票。建议更换股票池或策略。")

    elif mode == "🔍 单只个股详细体检":
        st.title("🔍 个股详细体检中心")
        st.markdown("当你在“自动化雷达”里发现了潜力代码，可以输入到这里查看具体的专业K线图和多维度诊断。")
        
        col1, col2 = st.columns([3, 1])
        with col1:
            # 默认给个代码防空白
            t_input = st.text_input("请输入股票代码 (纯数字即可，如 000858):", "000858")
        with col2:
            st.write(""); st.write("")
            btn = st.button("查看诊断报告", type="primary", use_container_width=True)
            
        # 只要点击按钮，必定显示内容！不再隐藏！
        if btn and t_input.strip():
            symbol = t_input.strip()
            with st.spinner('正在拉取数据...'):
                hist, name = fetch_kline_data(symbol)
                
                # 如果拿到空数据，明确报错，绝不默默隐藏
                if hist.empty:
                    st.error(f"❌ 查无此股，或者该股停牌获取不到数据 (你输入的代码是: {symbol})")
                else:
                    hist = calculate_indicators(hist)
                    latest = hist.iloc[-1]
                    
                    st.success(f"✅ 成功生成【{name} ({symbol})】的诊断报告")
                    c1, c2, c3 = st.columns(3)
                    c1.metric("最新价格", f"{latest['Close']:.2f}")
                    c2.metric("20日均线", f"{latest['MA20']:.2f}")
                    c3.metric("RSI情绪指标", f"{latest['RSI']:.1f}")
                    
                    # 画图
                    st.plotly_chart(plot_stock_chart(hist, name), use_container_width=True)
                    
                    # 强行给结论
                    if latest['Close'] > latest['MA20'] and latest['MACD'] > latest['Signal']:
                        st.info("💡 综合诊断：当前属于多头强势区间，MACD向好，趋势不错。")
                    elif latest['Close'] < latest['MA20']:
                        st.warning("💡 综合诊断：当前处于均线下方，属于弱势震荡或下跌趋势，注意风险。")
                    else:
                        st.info("💡 综合诊断：当前趋势不明显，处于过渡期。")

if __name__ == "__main__":
    main()
