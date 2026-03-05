import streamlit as st
import yfinance as yf
import pandas as pd
import time

# 设置页面基本配置
st.set_page_config(page_title="股票智能诊断与扫描系统", page_icon="📈", layout="wide")

# ==========================================
# 功能一：个股深度诊断
# ==========================================
def analyze_single_stock(ticker_symbol):
    st.subheader(f"[{ticker_symbol}] 个股技术诊断")
    ticker = yf.Ticker(ticker_symbol)
    
    # 1. 获取基础信息与当前价格
    try:
        info = ticker.info
        current_price = info.get('currentPrice', info.get('regularMarketPrice', None))
        if current_price:
            st.write(f"**实时/最新价格**: ${current_price}")
        else:
            st.info("提示：无法获取实时报价，将使用历史数据中的最新收盘价。")
    except Exception:
        pass # 忽略基础信息报错，依赖后续历史数据

    # 2. 获取历史数据并计算技术指标
    with st.spinner('正在拉取历史数据并计算技术指标...'):
        try:
            hist = ticker.history(period="6mo") # 获取半年数据
            
            if hist.empty:
                st.error("获取不到该股票的历史数据，可能是代码输入有误或接口超时！")
                return
                
            # 计算基础技术指标：20日均线(短期), 50日均线(中期)
            hist['MA20'] = hist['Close'].rolling(window=20).mean()
            hist['MA50'] = hist['Close'].rolling(window=50).mean()
            
            # 获取最新一日的数据
            latest_close = hist['Close'].iloc[-1]
            ma20 = hist['MA20'].iloc[-1]
            ma50 = hist['MA50'].iloc[-1]
            
            # UI展示指标
            st.markdown("### 📊 核心指标")
            col1, col2, col3 = st.columns(3)
            col1.metric("最新收盘价", f"{latest_close:.2f}")
            col2.metric("20日均线(短期)", f"{ma20:.2f}")
            col3.metric("50日均线(中期)", f"{ma50:.2f}")
            
            # 趋势诊断逻辑
            st.markdown("### 📝 系统诊断结论")
            if pd.isna(ma20) or pd.isna(ma50):
                st.warning("历史数据不足，无法计算均线指标。")
            elif latest_close > ma20 and ma20 > ma50:
                st.success("🟢 **多头趋势**：价格站上20日线，且20日线大于50日线，短期走势强劲，适合顺势持有。")
            elif latest_close < ma20 and ma20 < ma50:
                st.error("🔴 **空头趋势**：价格跌破20日线，且20日线小于50日线，处于下跌通道，建议观望防范风险。")
            elif latest_close > ma20 and ma20 < ma50:
                st.info("🟡 **触底反弹**：价格已突破短期20日均线，但中期均线依然向下，可能在震荡筑底。")
            else:
                st.warning("⚪ **震荡盘整**：长短均线交织，目前处于无方向的震荡阶段，建议等待突破信号。")
                
        except Exception as e:
            st.error(f"分析过程中发生错误: {e}")

# ==========================================
# 功能二：优质股批量安全扫描
# ==========================================
def batch_scan_stocks(stock_list):
    st.subheader("🚀 优质股自动扫描")
    st.info(f"共需扫描 {len(stock_list)} 只股票。为防止接口封禁，每只股票扫描后将**暂停 2 秒**，请耐心等待。")
    
    # 初始化UI组件：进度条和文本提示
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    good_stocks = [] # 用于保存符合条件的股票
    
    # 遍历扫描
    for i, symbol in enumerate(stock_list):
        status_text.text(f"正在扫描: {symbol} ({i+1}/{len(stock_list)}) ...")
        
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="3mo")
            
            if not hist.empty and len(hist) > 20:
                hist['MA20'] = hist['Close'].rolling(window=20).mean()
                latest_close = hist['Close'].iloc[-1]
                ma20 = hist['MA20'].iloc[-1]
                
                # 优质股筛选条件：最新收盘价站上20日均线 (你可以根据需要修改这里)
                if latest_close > ma20:
                    good_stocks.append({
                        "股票代码": symbol,
                        "最新收盘价": round(latest_close, 2),
                        "20日均线": round(ma20, 2),
                        "当前状态": "🟢 站上短期均线"
                    })
        except Exception:
            # 遇到单只股票错误（如停牌、退市、超时），直接跳过，防止整个程序崩溃
            pass 
            
        # 更新进度条
        progress_bar.progress((i + 1) / len(stock_list))
        
        # ★★★ 核心防封禁代码：强制休眠 ★★★
        if i < len(stock_list) - 1: # 最后一只扫描完就不需要停顿了
            time.sleep(2)  
            
    status_text.text("✅ 全部扫描完成！")
    
    # 展示最终结果
    if good_stocks:
        st.success(f"🎉 扫描结束！共发现 {len(good_stocks)} 只符合[站上20日均线]条件的强势股：")
        st.dataframe(pd.DataFrame(good_stocks), use_container_width=True)
    else:
        st.warning("扫描结束。本次股票池中未发现符合条件的股票。")


# ==========================================
# 主程序路由设计
# ==========================================
def main():
    st.title("📈 股票智能诊断与扫描系统")
    
    # 侧边栏菜单
    st.sidebar.title("功能导航")
    mode = st.sidebar.radio("请选择你要使用的功能：", ["🔍 个股深度诊断", "🚀 优质股自动扫描"])
    
    st.sidebar.markdown("---")
    st.sidebar.caption("注：数据来源为 Yahoo Finance。美股直接输入代码 (如 AAPL)；A股需加后缀 (沪市加 .SS，深市加 .SZ，如 600519.SS)。")

    # 根据菜单选择显示对应页面
    if mode == "🔍 个股深度诊断":
        st.header("🔍 个股深度诊断")
        ticker_input = st.text_input("请输入单只股票代码 (例如: AAPL, TSLA, 600519.SS)", "AAPL")
        
        if st.button("开始诊断", type="primary"):
            if ticker_input.strip():
                analyze_single_stock(ticker_input.strip().upper())
            else:
                st.warning("请输入有效的股票代码！")
                
    elif mode == "🚀 优质股自动扫描":
        st.header("🚀 优质股自动扫描 (防封禁模式)")
        default_pool = "AAPL, MSFT, GOOGL, AMZN, TSLA, META, NVDA, BABA, JD"
        tickers_input = st.text_area("请输入要批量扫描的股票池 (请用英文逗号
