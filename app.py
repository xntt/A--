import streamlit as st
import pandas as pd
import requests
import json
import re
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import time

st.set_page_config(page_title="自动化量化雷达 | 腾讯新浪引擎", page_icon="📡", layout="wide")

# ================= 1. 新浪财经引擎：全自动获取股票池 =================
def get_market_stock_pool_sina(pool_type="活跃股榜"):
    """
    使用新浪财经接口获取全市场活跃股票列表（防封禁机制极佳）
    """
    if pool_type == "高换手率榜(资金活跃)":
        sort_by = "turnoverratio" # 按换手率排序
    elif pool_type == "今日强势涨幅榜":
        sort_by = "changepercent" # 按涨跌幅排序
    else:
        sort_by = "amount"        # 默认按成交额排序

    # 新浪财经节点API：获取沪深A股前150只
    url = f"http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page=1&num=150&sort={sort_by}&asc=0&node=hs_a"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
    try:
        res = requests.get(url, headers=headers, timeout=5).text
        # 新浪返回的JSON键值没有双引号，Python无法直接解析，需要用正则修复
        fixed_text = re.sub(r'([{,])\s*([a-zA-Z_0-9]+)\s*:', r'\1"\2":', res)
        stocks = json.loads(fixed_text)
        
        pool = []
        for s in stocks:
            # 新浪返回的 symbol 格式如 "sh600519", "sz000858"
            pool.append({"代码": s.get("symbol", ""), "名称": s.get("name", "未知")})
        return pool
    except Exception as e:
        st.error(f"新浪财经接口请求失败，可能网络波动: {e}")
        return []

# ================= 2. 腾讯财经引擎：获取极速 K 线数据 =================
def fetch_kline_data_tencent(symbol, days=100):
    """使用腾讯财经接口获取K线数据，极速、稳定且自带前复权"""
    s = str(symbol).strip().lower()
    
    # 智能补全腾讯所需的 sh/sz 前缀
    if len(s) == 6 and s.isdigit():
        s = 'sh' + s if s.startswith('6') else 'sz' + s
        
    # 腾讯K线接口: qfq 代表前复权，保证均线计算准确
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={s},day,,,{days},qfq"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        res = requests.get(url, headers=headers, timeout=5).json()
        if res.get("code") != 0 or s not in res.get("data", {}):
            return pd.DataFrame(), s
            
        stock_data = res["data"][s]
        # 优先获取 qfqday(前复权数据), 否则获取 day(未复权数据)
        klines = stock_data.get("qfqday", stock_data.get("day", []))
        
        # 腾讯自带的 qt 字段里含有最新股票名称
        qt_info = stock_data.get("qt", {}).get(s, [])
        name = qt_info[1] if len(qt_info) > 1 else symbol

        data = []
        for k in klines:
            # 腾讯K线数组结构: [日期, 开盘, 收盘, 最高, 最低, 成交量]
            data.append({
                "Date": k[0], "Open": float(k[1]), "Close": float(k[2]),
                "High": float(k[3]), "Low": float(k[4]), "Volume": float(k[5])
            })
            
        df = pd.DataFrame(data)
        df['Date'] = pd.to_datetime(df['Date'])
        df.set_index('Date', inplace=True)
        return df, name
    except Exception:
        return pd.DataFrame(), s

# ================= 3. 技术指标算法 =================
def calculate_indicators(df):
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA50'] = df['Close'].rolling(window=50).mean()
    
    df['EMA12'] = df['Close'].ewm(span=12, adjust=False).mean()
    df['EMA26'] = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = df['EMA12'] - df['EMA26']
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss.replace(0, 1e-5)
    df['RSI'] = 100 - (100 / (1 + rs))
    return df

# ================= 4. K线绘图引擎 =================
def plot_stock_chart(df, name):
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
    fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K线'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], line=dict(color='orange', width=1.5), name='MA20'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA50'], line=dict(color='blue', width=1.5), name='MA50'), row=1, col=1)
    colors = ['red' if row['Close'] >= row['Open'] else 'green' for index, row in df.iterrows()]
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=colors, name='成交量'), row=2, col=1)
    fig.update_layout(title=f"{name} 走势分析图", yaxis_title='价格', xaxis_rangeslider_visible=False, height=500, margin=dict(l=0, r=0, t=40, b=0))
    return fig

# ================= 5. 主程序界面逻辑 =================
def main():
    st.sidebar.title("📡 自动化挖掘雷达")
    st.sidebar.caption("底层引擎：腾讯财经 + 新浪财经 (防屏蔽极速版)")
    st.sidebar.markdown("---")
    
    mode = st.sidebar.radio("选择工作模式：", ["🎯 全网自动盲扫挖掘", "🔍 单只个股详细体检"])
    
    if mode == "🎯 全网自动盲扫挖掘":
        st.title("🎯 潜力金股全自动挖掘机")
        st.markdown("系统将自动从新浪财经获取当前A股最具活力的 150 只股票，并利用腾讯算法找出符合你策略的【潜力标的】。")
        
        c1, c2 = st.columns(2)
        with c1:
            pool_choice = st.selectbox("1. 设定扫描雷达的搜索范围：", ["高换手率榜(资金活跃)", "今日强势涨幅榜", "大盘成交活跃榜"])
        with c2:
            strategy = st.selectbox("2. 设定选股过滤策略：", [
                "MACD底部刚刚金叉 (启动信号)", 
                "均线多头排列且站上MA20 (趋势向上)", 
                "RSI极度超卖跌破30 (恐慌抄底)"
            ])
            
        if st.button(f"🚀 立即启动全网扫描", type="primary", use_container_width=True):
            st.info(f"正在接通新浪财经，获取【{pool_choice}】最新名单...")
            market_stocks = get_market_stock_pool_sina(pool_choice)
            
            if not market_stocks:
                st.error("数据获取失败，请重试。")
                return
                
            st.success(f"✅ 成功锁定 {len(market_stocks)} 只活跃股票！正在接通腾讯云端算法进行穿透扫描...")
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            found_stocks = []
            
            for i, stock in enumerate(market_stocks):
                code = stock['代码']
                name = stock['名称']
                status_text.text(f"雷达正在扫描: {name} ({code}) ... [进度 {i+1}/{len(market_stocks)}]")
                
                # 请求腾讯接口
                hist, _ = fetch_kline_data_tencent(code, days=60)
                if not hist.empty and len(hist) >= 50:
                    hist = calculate_indicators(hist)
                    latest = hist.iloc[-1]
                    prev = hist.iloc[-2]
                    
                    is_match = False
                    reason = ""
                    
                    if strategy == "MACD底部刚刚金叉 (启动信号)":
                        if latest['MACD'] > latest['Signal'] and prev['MACD'] <= prev['Signal'] and latest['MACD'] < 0:
                            is_match, reason = "水下MACD今日金叉"
                            
                    elif strategy == "均线多头排列且站上MA20 (趋势向上)":
                        if latest['Close'] > latest['MA20'] and latest['MA20'] > latest['MA50'] and latest['MA20'] > prev['MA20']:
                            is_match, reason = "站上20日线且发散向上"
                            
                    elif strategy == "RSI极度超卖跌破30 (恐慌抄底)":
                        if latest['RSI'] < 30:
                            is_match, reason = f"RSI极低: {latest['RSI']:.1f}"

                    if is_match:
                        found_stocks.append({
                            "股票代码": code.replace('sh', '').replace('sz', ''),
                            "股票名称": name,
                            "最新收盘价": round(latest['Close'], 2),
                            "入选核心原因": reason
                        })
                
                progress_bar.progress((i + 1) / len(market_stocks))
                time.sleep(0.05) # 稍微停顿，防止把腾讯接口打崩
                
            status_text.text("✅ 雷达深度扫描完成！")
            
            if found_stocks:
                st.success(f"🎉 挖掘成功！为您找出 {len(found_stocks)} 只符合【{strategy}】的潜力股：")
                st.dataframe(pd.DataFrame(found_stocks), use_container_width=True)
                st.balloons()
            else:
                st.warning("当前这批市场活跃股中，暂无符合该苛刻策略的股票。建议换个策略或换个榜单盲扫。")

    elif mode == "🔍 单只个股详细体检":
        st.title("🔍 个股详细体检中心")
        st.markdown("在这里输入你在雷达里扫描出来的六位数字代码，即可查看详细腾讯 K 线图。")
        
        col1, col2 = st.columns([3, 1])
        with col1:
            t_input = st.text_input("请输入股票代码 (如 600519, 000858):", "600519")
        with col2:
            st.write(""); st.write("")
            btn = st.button("查看腾讯图表", type="primary", use_container_width=True)
            
        if btn and t_input.strip():
            symbol = t_input.strip()
            with st.spinner('正在从腾讯主干网络拉取数据...'):
                hist, name = fetch_kline_data_tencent(symbol)
                
                if hist.empty:
                    st.error(f"❌ 查无此股，或该股已停牌 (代码: {symbol})。请确认输入的是6位数字A股代码。")
                else:
                    hist = calculate_indicators(hist)
                    latest = hist.iloc[-1]
                    
                    st.success(f"✅ 成功生成【{name} ({symbol})】的诊断报告")
                    c1, c2, c3 = st.columns(3)
                    c1.metric("最新价格", f"¥ {latest['Close']:.2f}")
                    c2.metric("20日均线 (MA20)", f"¥ {latest['MA20']:.2f}")
                    c3.metric("RSI (14日情绪)", f"{latest['RSI']:.1f}")
                    
                    st.plotly_chart(plot_stock_chart(hist, name), use_container_width=True)
                    
                    if latest['Close'] > latest['MA20'] and latest['MACD'] > latest['Signal']:
                        st.info("💡 **系统评价**：该股处于多头强势区间，MACD金叉向好，具备较好的动能。")
                    elif latest['Close'] < latest['MA20']:
                        st.warning("💡 **系统评价**：该股受制于20日均线压制，属于弱势震荡或下跌趋势，请谨慎入场。")
                    else:
                        st.info("💡 **系统评价**：该股目前趋势处于过渡期，多空博弈中，建议继续观望。")

if __name__ == "__main__":
    main()
