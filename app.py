import streamlit as st
import yfinance as yf
import pandas as pd
import time

st.set_page_config(page_title="股票诊断", layout="wide")

def analyze_single_stock(symbol):
    st.subheader(f"[{symbol}] 个股诊断")
    
    # 提示用户 A股格式
    if symbol.isdigit() and len(symbol) == 6:
        st.warning("⚠️ 警告：检测到纯数字代码！如果是A股，沪市请加上 .SS，深市请加上 .SZ（例如：600519.SS）")

    ticker = yf.Ticker(symbol)
    
    with st.spinner('正在连接雅虎财经拉取数据...'):
        try:
            # 放弃极易报错的 info，直接使用 history 获取最近半年的日K线
            hist = ticker.history(period="6mo")
            
            # 【核心调试】：直接在页面展示是否拿到了数据
            if hist.empty:
                st.error(f"❌ 雅虎财经未返回 {symbol} 的数据！")
                st.info("原因可能是：1. 股票代码不存在或格式错（A股需加.SS或.SZ）；2. 雅虎财经接口临时抽风；3. 您的服务器IP被封禁。")
                return
                
            # 如果拿到了数据，计算指标
            hist['MA20'] = hist['Close'].rolling(window=20).mean()
            hist['MA50'] = hist['Close'].rolling(window=50).mean()
            
            # 获取最新一天的数据
            latest_date = hist.index[-1].strftime('%Y-%m-%d')
            latest_close = hist['Close'].iloc[-1]
            ma20 = hist['MA20'].iloc[-1]
            ma50 = hist['MA50'].iloc[-1]
            
            st.success(f"✅ 成功获取数据！最后更新时间：{latest_date}")
            
            st.markdown("### 📊 核心指标")
            c1, c2, c3 = st.columns(3)
            c1.metric("最新收盘价", f"{latest_close:.2f}")
            c2.metric("20日均线", f"{ma20:.2f}")
            c3.metric("50日均线", f"{ma50:.2f}")
            
            st.markdown("### 📝 诊断结论")
            if pd.isna(ma20) or pd.isna(ma50):
                st.warning("获取的数据天数不足50天，无法计算均线趋势。")
            elif latest_close > ma20 and ma20 > ma50:
                st.success("🟢 多头趋势：短期走势强劲。")
            elif latest_close < ma20 and ma20 < ma50:
                st.error("🔴 空头趋势：处于下跌通道。")
            elif latest_close > ma20 and ma20 < ma50:
                st.info("🟡 触底反弹：突破短期均线。")
            else:
                st.warning("⚪ 震荡盘整：目前处于无方向震荡阶段。")
                
            # 展开查看历史数据表
            with st.expander("查看最近5天原始数据"):
                st.dataframe(hist.tail(5))
                
        except Exception as e:
            st.error(f"❌ 发生系统级错误，详细信息：{str(e)}")


def batch_scan_stocks(stock_list):
    st.subheader("🚀 优质股扫描 (找寻站上20日均线的股票)")
    st.info("开始扫描，如果个别股票报错将显示在下方...")
    
    good_stocks = []
    
    # 用一个容器来显示扫描日志
    log_container = st.container()
    
    for i, sym in enumerate(stock_list):
        with log_container:
            st.text(f"正在扫描: {sym}...")
            
        try:
            ticker = yf.Ticker(sym)
            hist = ticker.history(period="3mo")
            
            if hist.empty:
                st.error(f"   ❌ {sym}: 获取数据失败 (可能代码错误)")
                continue
                
            if len(hist) > 20:
                hist['MA20'] = hist['Close'].rolling(window=20).mean()
                lc = hist['Close'].iloc[-1]
                ma20 = hist['MA20'].iloc[-1]
                
                # 判断条件：最新价大于20日均线
                if lc > ma20:
                    good_stocks.append({
                        "股票代码": sym,
                        "最新价": round(lc, 2),
                        "20日均线": round(ma20, 2),
                    })
                    st.success(f"   ✅ {sym}: 符合条件！")
                else:
                    st.write(f"   - {sym}: 不符合条件 (价格 {lc:.2f} < 均线 {ma20:.2f})")
            else:
                st.warning(f"   ⚠️ {sym}: 历史数据不足20天")
                
        except Exception as e:
            st.error(f"   ❌ {sym}: 发生错误 {str(e)}")
            
        # 强制休眠1秒，防封禁
        time.sleep(1)  
            
    st.markdown("---")
    if good_stocks:
        st.success(f"🎉 扫描完毕！共发现 {len(good_stocks)} 只强势股：")
        st.dataframe(pd.DataFrame(good_stocks), use_container_width=True)
    else:
        st.warning("扫描完毕，未发现符合条件的股票。")

def main():
    st.title("📈 股票智能诊断 (增强排错版)")
    
    mode = st.sidebar.radio("选择功能：", ["🔍 个股诊断", "🚀 批量扫描"])
    
    if mode == "🔍 个股诊断":
        t_input = st.text_input("输入代码 (A股请加后缀, 例如: 600519.SS 或 AAPL):", "AAPL")
        if st.button("开始诊断", type="primary"):
            if t_input.strip():
                analyze_single_stock(t_input.strip().upper())
                
    elif mode == "🚀 批量扫描":
        pool = "AAPL, MSFT, 600519.SS, 000858.SZ"
        ts_input = st.text_area("输入股票池 (逗号分隔):", pool)
        if st.button("开始扫描", type="primary"):
            raw_list = ts_input.split(",")
            s_list = [t.strip().upper() for t in raw_list if t.strip()]
            if s_list:
                batch_scan_stocks(s_list)

if __name__ == "__main__":
    main()
