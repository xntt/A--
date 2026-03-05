import streamlit as st
import pandas as pd
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import time

st.set_page_config(page_title="AI 股票全景诊断系统", page_icon="📈", layout="wide")

# ================= 核心：国内数据源获取 (替代被封禁的雅虎) =================
def fetch_stock_data(symbol, days=150):
    """使用国内数据接口获取K线数据，极速且不封IP"""
    s = symbol.upper().strip()
    
    # 智能匹配股票市场代码格式
    if s.endswith('.SS') or (s.isdigit() and s.startswith('6')):
        secid = f"1.{s.replace('.SS', '')}"
    elif s.endswith('.SZ') or (s.isdigit() and (s.startswith('0') or s.startswith('3'))):
        secid = f"0.{s.replace('.SZ', '')}"
    elif s.endswith('.HK'):
        secid = f"116.{s.replace('.HK', '')}"
    elif s.isalpha(): 
        secid = f"105.{s}" # 美股
    else:
        secid = f"1.{s}"
        
    # 请求国内极速K线接口
    url = f"https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&klt=101&fqt=1&end=20500101&lmt={days}"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        res = requests.get(url, headers=headers, timeout=5).json()
        if not res or not res.get("data") or not res["data"].get("klines"):
            return pd.DataFrame(), s
            
        klines = res["data"]["klines"]
        stock_name = res["data"].get("name", s)
        
        data = []
        for k in klines:
            parts = k.split(',')
            data.append({
                "Date": parts[0],
                "Open": float(parts[1]),
                "Close": float(parts[2]),
                "High": float(parts[3]),
                "Low": float(parts[4]),
                "Volume": float(parts[5])
            })
            
        df = pd.DataFrame(data)
        df['Date'] = pd.to_datetime(df['Date'])
        df.set_index('Date', inplace=True)
        return df, stock_name
    except:
        return pd.DataFrame(), s

# ================= 计算技术指标的函数 =================
def calculate_indicators(df):
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA50'] = df['Close'].rolling(window=50).mean()
    
    # MACD计算
    df['EMA12'] = df['Close'].ewm(span=12, adjust=False).mean()
    df['EMA26'] = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = df['EMA12'] - df['EMA26']
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    
    # RSI计算
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss.replace(0, 1e-5) # 防止除以0
    df['RSI'] = 100 - (100 / (1 + rs))
    
    return df

# ================= 画专业K线图的函数 =================
def plot_stock_chart(df, name):
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])

    # K线
    fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], 
                                 low=df['Low'], close=df['Close'], name='K线'), row=1, col=1)
    # 均线
    fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], line=dict(color='orange', width=1.5), name='MA20'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA50'], line=dict(color='blue', width=1.5), name='MA50'), row=1, col=1)

    # 成交量
    colors = ['red' if row['Close'] >= row['Open'] else 'green' for index, row in df.iterrows()]
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=colors, name='成交量'), row=2, col=1)

    fig.update_layout(title=f"{name} 近期走势分析图", yaxis_title='价格', 
                      xaxis_rangeslider_visible=False, height=600, margin=dict(l=0, r=0, t=40, b=0))
    return fig

# ================= 个股全景诊断模块 =================
def analyze_single_stock(symbol):
    st.header(f"📊 个股深度诊断报告")
    
    with st.spinner('正在从国内专线极速拉取数据...'):
        hist, name = fetch_stock_data(symbol)
        
        if hist.empty:
            st.error(f"❌ 获取不到 [{symbol}] 的数据！请检查代码是否正确（纯数字A股直接输代码即可，如: 600519）")
            return
            
        hist = calculate_indicators(hist)
        latest = hist.iloc[-1]
        prev = hist.iloc[-2]
        change_pct = (latest['Close'] - prev['Close']) / prev['Close'] * 100
        
        # 1. 基本信息面板
        c1, c2, c3 = st.columns(3)
        c1.metric("股票名称", name)
        c2.metric("最新收盘价", f"{latest['Close']:.2f}", f"{change_pct:.2f}%")
        c3.metric("RSI (14日)", f"{latest['RSI']:.1f}")
        
        # 2. 绘制专业图表
        st.plotly_chart(plot_stock_chart(hist, name), use_container_width=True)
        
        # 3. 智能诊断逻辑
        st.subheader("💡 核心技术指标诊断")
        col_tech1, col_tech2, col_tech3 = st.columns(3)
        
        with col_tech1:
            st.markdown("#### 📈 均线趋势")
            if latest['Close'] > latest['MA20'] and latest['MA20'] > latest['MA50']:
                st.success("【多头排列】：股价站稳中短期均线，趋势向上。")
            elif latest['Close'] < latest['MA20'] and latest['MA20'] < latest['MA50']:
                st.error("【空头排列】：股价受均线压制，处于下跌通道。")
            else:
                st.warning("【震荡整理】：均线纠缠，方向不明，建议观望。")
        
        with col_tech2:
            st.markdown("#### ⚡ MACD动能")
            if latest['MACD'] > latest['Signal'] and prev['MACD'] <= prev['Signal']:
                st.success("【金叉买点】：MACD刚刚形成金叉，上涨动能强劲！")
            elif latest['MACD'] > 0 and latest['MACD'] > latest['Signal']:
                st.info("【多头动能】：处于零轴上方且保持强势。")
            else:
                st.write("目前动能偏弱或处于调整期。")
                
        with col_tech3:
            st.markdown("#### ⚖️ 超买超卖")
            rsi_val = latest['RSI']
            if rsi_val > 70:
                st.error("⚠️ 【极度超买】：短期风险积聚，有回调压力。")
            elif rsi_val < 30:
                st.success("🔥 【极度超卖】：跌幅过大，随时可能反弹。")
            else:
                st.info("【区间震荡】：处于合理波动区间内。")
                
        # 4. 综合结论
        st.markdown("---")
        st.subheader("🎯 AI 综合操作建议")
        score = sum([latest['Close'] > latest['MA20'], latest['MACD'] > latest['Signal'], 30 < latest['RSI'] < 70])
        if score >= 2:
            st.success("🟢 **【积极做多】**：技术面共振向上，当前为较好的入场或持有区间。")
        else:
            st.error("🔴 **【观望为主】**：技术面整体偏弱，风险大于收益，建议空仓观望。")

# ================= 优质股批量扫描模块 =================
def batch_scan_stocks(stock_list, strategy):
    st.subheader(f"🚀 策略扫描执行中：{strategy}")
    progress_bar = st.progress(0)
    status_text = st.empty()
    good_stocks = []
    
    for i, sym in enumerate(stock_list):
        status_text.text(f"正在光速分析: {sym} ...")
        hist, name = fetch_stock_data(sym)
        
        if not hist.empty and len(hist) >= 50:
            hist = calculate_indicators(hist)
            latest = hist.iloc[-1]
            prev = hist.iloc[-2]
            
            condition_met = False
            reason = ""
            
            if strategy == "强势突破 (价格站上20日线)":
                if latest['Close'] > latest['MA20'] and prev['Close'] <= prev['MA20']:
                    condition_met, reason = True, "今日强势突破20日均线"
            elif strategy == "MACD金叉启动":
                if latest['MACD'] > latest['Signal'] and prev['MACD'] <= prev['Signal']:
                    condition_met, reason = True, "MACD形成金叉"
            elif strategy == "超跌抄底 (RSI<30)":
                if latest['RSI'] < 30:
                    condition_met, reason = True, f"RSI低至 {latest['RSI']:.1f}"

            if condition_met:
                good_stocks.append({
                    "股票名称": name,
                    "代码": sym,
                    "最新价": round(latest['Close'], 2),
                    "入选理由": reason
                })
                
        progress_bar.progress((i + 1) / len(stock_list))
        time.sleep(0.1) # 国内接口无惧封禁，极速扫描
        
    status_text.text("✅ 扫描完成！")
    if good_stocks:
        st.success(f"🎉 共发现 {len(good_stocks)} 只符合条件的股票：")
        st.dataframe(pd.DataFrame(good_stocks), use_container_width=True)
        st.balloons()
    else:
        st.warning("当前股票池中没有符合该策略的股票。")

# ================= 主程序入口 =================
def main():
    st.sidebar.title("🤖 智眸·股票诊断系统")
    mode = st.sidebar.radio("请选择核心功能：", ["🔍 个股深度诊断", "🚀 策略智能批量扫描"])
    st.sidebar.caption("💡 提示：纯数字A股直接输入即可 (如: 600519，000858)，美股输入字母 (如: AAPL)")
    
    if mode == "🔍 个股深度诊断":
        c1, c2 = st.columns([3, 1])
        with c1:
            t_input = st.text_input("请输入股票代码:", "600519")
        with c2:
            st.write("") 
            st.write("")
            btn = st.button("开始诊断", type="primary", use_container_width=True)
            
        if btn and t_input.strip():
            analyze_single_stock(t_input.strip())
                
    elif mode == "🚀 策略智能批量扫描":
        strategy = st.selectbox("选择扫描策略：", ["强势突破 (价格站上20日线)", "MACD金叉启动", "超跌抄底 (RSI<30)"])
        pool = "600519, 000858, AAPL, TSLA, 0700.HK, 300750"
        ts_input = st.text_area("输入自选股票池 (用逗号分隔):", pool)
        
        if st.button("启动量化扫描", type="primary"):
            raw_list = ts_input.split(",")
            s_list = [t.strip() for t in raw_list if t.strip()]
            if s_list:
                batch_scan_stocks(s_list, strategy)

if __name__ == "__main__":
    main()
