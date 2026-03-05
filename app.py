import streamlit as st
import yfinance as yf
import pandas as pd
import time

st.set_page_config(
    page_title="股票诊断系统",
    page_icon="📈",
    layout="wide"
)

def analyze_single_stock(symbol):
    st.subheader(f"[{symbol}] 个股诊断")
    ticker = yf.Ticker(symbol)
    
    try:
        info = ticker.info
        cp = info.get('currentPrice', info.get('regularMarketPrice'))
        if cp:
            st.write(f"**最新价格**: ${cp}")
    except:
        pass 

    with st.spinner('正在拉取数据...'):
        try:
            hist = ticker.history(period="6mo")
            if hist.empty:
                st.error("获取数据失败，请检查代码！")
                return
                
            hist['MA20'] = hist['Close'].rolling(window=20).mean()
            hist['MA50'] = hist['Close'].rolling(window=50).mean()
            
            latest_close = hist['Close'].iloc[-1]
            ma20 = hist['MA20'].iloc[-1]
            ma50 = hist['MA50'].iloc[-1]
            
            st.markdown("### 📊 核心指标")
            c1, c2, c3 = st.columns(3)
            c1.metric("收盘价", f"{latest_close:.2f}")
            c2.metric("20日均线", f"{ma20:.2f}")
            c3.metric("50日均线", f"{ma50:.2f}")
            
            st.markdown("### 📝 诊断结论")
            if pd.isna(ma20) or pd.isna(ma50):
                st.warning("数据不足，无法计算均线。")
            elif latest_close > ma20 and ma20 > ma50:
                st.success("🟢 多头趋势：短期走势强劲，适合顺势持有。")
            elif latest_close < ma20 and ma20 < ma50:
                st.error("🔴 空头趋势：处于下跌通道，建议观望。")
            elif latest_close > ma20 and ma20 < ma50:
                st.info("🟡 触底反弹：突破短期均线，可能在筑底。")
            else:
                st.warning("⚪ 震荡盘整：目前处于无方向震荡阶段。")
                
        except Exception as e:
            st.error(f"发生错误: {e}")

def batch_scan_stocks(stock_list):
    st.subheader("🚀 优质股扫描")
    st.info("为防封禁，每只扫描后暂停2秒。")
    
    p_bar = st.progress(0)
    s_text = st.empty()
    good_stocks = []
    
    for i, sym in enumerate(stock_list):
        s_text.text(f"扫描: {sym} ({i+1}/{len(stock_list)})")
        try:
            ticker = yf.Ticker(sym)
            hist = ticker.history(period="3mo")
            if not hist.empty and len(hist) > 20:
                hist['MA20'] = hist['Close'].rolling(window=20).mean()
                lc = hist['Close'].iloc[-1]
                ma20 = hist['MA20'].iloc[-1]
                if lc > ma20:
                    good_stocks.append({
                        "股票代码": sym,
                        "最新收盘价": round(lc, 2),
                        "20日均线": round(ma20, 2),
                        "状态": "🟢 站上20日线"
                    })
        except:
            pass
            
        p_bar.progress((i + 1) / len(stock_list))
        if i < len(stock_list) - 1:
            time.sleep(2)  
            
    s_text.text("✅ 扫描完成！")
    if good_stocks:
        st.success(f"🎉 发现 {len(good_stocks)} 只强势股：")
        st.dataframe(pd.DataFrame(good_stocks), use_container_width=True)
    else:
        st.warning("未发现符合条件的股票。")

def main():
    st.title("📈 股票智能诊断系统")
    st.sidebar.title("功能导航")
    mode = st.sidebar.radio("选择功能：", ["🔍 个股诊断", "🚀 批量扫描"])
    
    if mode == "🔍 个股诊断":
        st.header("🔍 个股诊断")
        # 这里的文字已经改短，绝不会再触发截断换行
        t_input = st.text_input("输入代码 (如: AAPL):", "AAPL")
        if st.button("开始诊断", type="primary"):
            if t_input.strip():
                analyze_single_stock(t_input.strip().upper())
            else:
                st.warning("请输入代码！")
                
    elif mode == "🚀 批量扫描":
        st.header("🚀 批量扫描")
        pool = "AAPL, MSFT, GOOGL, TSLA, NVDA"
        # 这里的文字已经改短，绝不会再触发截断换行
        ts_input = st.text_area("输入股票池(逗号分隔):", pool)
        if st.button("开始扫描", type="primary"):
            if ts_input.strip():
                raw_list = ts_input.split(",")
                s_list = [t.strip().upper() for t in raw_list if t.strip()]
                if len(s_list) > 0:
                    batch_scan_stocks(s_list)
                else:
                    st.warning("格式错误。")
            else:
                st.warning("不能为空！")

if __name__ == "__main__":
    main()
