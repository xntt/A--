import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import time

st.set_page_config(page_title="AI 股票全景诊断系统", page_icon="📈", layout="wide")

# ================= 计算技术指标的函数 =================
def calculate_indicators(df):
    # 移动均线
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA50'] = df['Close'].rolling(window=50).mean()
    
    # MACD
    df['EMA12'] = df['Close'].ewm(span=12, adjust=False).mean()
    df['EMA26'] = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = df['EMA12'] - df['EMA26']
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['MACD'] - df['Signal']
    
    # RSI (14天)
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # 布林带 (20日)
    df['STD20'] = df['Close'].rolling(window=20).std()
    df['Upper'] = df['MA20'] + (df['STD20'] * 2)
    df['Lower'] = df['MA20'] - (df['STD20'] * 2)
    
    return df

# ================= 画专业K线图的函数 =================
def plot_stock_chart(df, symbol):
    # 创建带有两个子图的画布 (K线图 + 成交量)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                        vertical_spacing=0.03, row_heights=[0.7, 0.3])

    # K线图
    fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], 
                                 low=df['Low'], close=df['Close'], name='K线'), row=1, col=1)
    
    # 均线
    fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], line=dict(color='orange', width=1.5), name='MA20'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA50'], line=dict(color='blue', width=1.5), name='MA50'), row=1, col=1)

    # 成交量 (区分红绿柱)
    colors = ['green' if row['Open'] - row['Close'] >= 0 else 'red' for index, row in df.iterrows()]
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=colors, name='成交量'), row=2, col=1)

    fig.update_layout(title=f"{symbol} 近半年走势分析图", yaxis_title='价格', 
                      xaxis_rangeslider_visible=False, height=600, margin=dict(l=0, r=0, t=40, b=0))
    return fig

# ================= 个股全景诊断模块 =================
def analyze_single_stock(symbol):
    st.header(f"📊 {symbol} 深度诊断报告")
    ticker = yf.Ticker(symbol)
    
    with st.spinner('正在进行全方位数据计算，请稍候...'):
        try:
            # 1. 获取基本面信息 (带防报错机制)
            info = ticker.info
            cp = info.get('currentPrice', info.get('regularMarketPrice', 0))
            name = info.get('shortName', symbol)
            pe = info.get('trailingPE', '亏损/暂无')
            market_cap = info.get('marketCap', 0)
            mc_str = f"{market_cap / 1e8:.2f} 亿" if market_cap else "未知"
            
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("公司名称", name)
            c2.metric("最新价格", f"${cp}")
            c3.metric("市盈率 (PE)", pe)
            c4.metric("总市值", mc_str)
            
            # 2. 获取历史数据并计算指标
            hist = ticker.history(period="6mo")
            if hist.empty:
                st.error("无法获取历史数据，请检查代码是否正确。")
                return
                
            hist = calculate_indicators(hist)
            
            # 3. 绘制专业图表
            st.plotly_chart(plot_stock_chart(hist, symbol), use_container_width=True)
            
            # 4. 提取最新一天的数据进行诊断
            latest = hist.iloc[-1]
            prev = hist.iloc[-2]
            
            # --- 智能诊断逻辑 ---
            st.subheader("💡 核心技术指标诊断")
            col_tech1, col_tech2, col_tech3 = st.columns(3)
            
            # 趋势诊断 (MA)
            with col_tech1:
                st.markdown("#### 📈 趋势研判 (均线系统)")
                if latest['Close'] > latest['MA20'] and latest['MA20'] > latest['MA50']:
                    st.success("【多头排列】：股价站稳中短期均线，趋势向上。")
                elif latest['Close'] < latest['MA20'] and latest['MA20'] < latest['MA50']:
                    st.error("【空头排列】：股价受均线压制，处于下跌通道。")
                else:
                    st.warning("【震荡整理】：均线纠缠，方向不明，建议观望。")
            
            # 动能诊断 (MACD)
            with col_tech2:
                st.markdown("#### ⚡ 动能研判 (MACD)")
                if latest['MACD'] > latest['Signal'] and prev['MACD'] <= prev['Signal']:
                    st.success("【金叉买点】：MACD刚刚形成金叉，上涨动能强劲！")
                elif latest['MACD'] > 0 and latest['MACD'] > latest['Signal']:
                    st.info("【多头动能】：处于零轴上方且保持强势。")
                elif latest['MACD'] < latest['Signal']:
                    st.error("【空头动能】：MACD处于弱势或死叉状态。")
                else:
                    st.write("动能平缓。")
                    
            # 超买超卖诊断 (RSI)
            with col_tech3:
                st.markdown("#### ⚖️ 超买超卖 (RSI)")
                rsi_val = latest['RSI']
                st.metric("RSI (14日)", f"{rsi_val:.1f}")
                if rsi_val > 70:
                    st.error("⚠️ 【极度超买】：短期风险积聚，有回调压力。")
                elif rsi_val < 30:
                    st.success("🔥 【极度超卖】：跌幅过大，可能随时迎来技术性反弹。")
                else:
                    st.info("【区间震荡】：处于合理波动区间内。")
                    
            # 5. 综合结论
            st.markdown("---")
            st.subheader("🎯 AI 综合操作建议")
            score = 0
            if latest['Close'] > latest['MA20']: score += 1
            if latest['MACD'] > latest['Signal']: score += 1
            if 30 < latest['RSI'] < 70: score += 1
            elif latest['RSI'] < 30: score += 2 # 抄底加分
            
            if score >= 3:
                st.success("🟢 **【积极做多】**：技术面共振向上，当前为较好的入场或持有区间，建议顺势而为！")
            elif score == 2:
                st.warning("🟡 **【谨慎持有】**：多空博弈激烈，有一定的不确定性，建议控制仓位，关注均线得失。")
            else:
                st.error("🔴 **【观望为主】**：技术面整体偏弱，风险大于收益，建议空仓观望或逢高减磅。")

        except Exception as e:
            st.error(f"诊断过程发生错误: {str(e)}")


# ================= 优质股批量扫描模块 =================
def batch_scan_stocks(stock_list, strategy):
    st.subheader(f"🚀 策略扫描执行中：{strategy}")
    progress_bar = st.progress(0)
    status_text = st.empty()
    good_stocks = []
    
    for i, sym in enumerate(stock_list):
        status_text.text(f"正在分析: {sym} ...")
        try:
            ticker = yf.Ticker(sym)
            hist = ticker.history(period="3mo")
            if not hist.empty and len(hist) >= 50:
                hist = calculate_indicators(hist)
                latest = hist.iloc[-1]
                prev = hist.iloc[-2]
                
                # 根据用户选择的策略进行筛选
                condition_met = False
                reason = ""
                
                if strategy == "强势多头突破 (价格站上MA20且向上)":
                    if latest['Close'] > latest['MA20'] and latest['MA20'] > prev['MA20']:
                        condition_met = True
                        reason = "站上20日线且均线拐头向上"
                        
                elif strategy == "MACD金叉异动":
                    if latest['MACD'] > latest['Signal'] and prev['MACD'] <= prev['Signal']:
                        condition_met = True
                        reason = "MACD今日形成金叉"
                        
                elif strategy == "RSI极度超卖 (抄底)":
                    if latest['RSI'] < 30:
                        condition_met = True
                        reason = f"RSI低至 {latest['RSI']:.1f}"

                if condition_met:
                    good_stocks.append({
                        "代码": sym,
                        "最新价": round(latest['Close'], 2),
                        "RSI": round(latest['RSI'], 1),
                        "入选理由": reason
                    })
        except:
            pass # 忽略错误股票，继续扫描
            
        progress_bar.progress((i + 1) / len(stock_list))
        time.sleep(1) # 防封禁休眠
        
    status_text.text("✅ 扫描完成！")
    if good_stocks:
        st.success(f"🎉 发现 {len(good_stocks)} 只符合【{strategy}】的股票：")
        st.dataframe(pd.DataFrame(good_stocks), use_container_width=True)
        st.balloons() # 放个气球动画庆祝
    else:
        st.warning("当前股票池中没有符合该策略的股票。")


# ================= 主程序侧边栏 =================
def main():
    st.sidebar.title("🤖 智眸·股票诊断系统")
    st.sidebar.markdown("---")
    mode = st.sidebar.radio("请选择核心功能：", ["🔍 个股深度全景诊断", "🚀 策略智能批量扫描"])
    st.sidebar.markdown("---")
    st.sidebar.caption("提示：A股请在代码后加 .SS(沪) 或 .SZ(深)")
    
    if mode == "🔍 个股深度全景诊断":
        col1, col2 = st.columns([3, 1])
        with col1:
            t_input = st.text_input("请输入股票代码 (例如: AAPL, TSLA, 600519.SS):", "TSLA")
        with col2:
            st.write("") # 占位对齐
            st.write("")
            btn = st.button("开始深度诊断", type="primary", use_container_width=True)
            
        if btn and t_input.strip():
            analyze_single_stock(t_input.strip().upper())
                
    elif mode == "🚀 策略智能批量扫描":
        strategy = st.selectbox("选择扫描策略模型：", [
            "强势多头突破 (价格站上MA20且向上)", 
            "MACD金叉异动", 
            "RSI极度超卖 (抄底)"
        ])
        
        pool = "AAPL, MSFT, GOOGL, TSLA, NVDA, META, AMZN, BABA"
        ts_input = st.text_area("输入自选股票池 (用逗号分隔):", pool)
        
        if st.button("启动量化扫描", type="primary"):
            raw_list = ts_input.split(",")
            s_list = [t.strip().upper() for t in raw_list if t.strip()]
            if s_list:
                batch_scan_stocks(s_list, strategy)

if __name__ == "__main__":
    main()
