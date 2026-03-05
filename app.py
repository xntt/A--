import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import time

# 设置页面基本配置
st.set_page_config(page_title="A股智能诊断与扫描系统", page_icon="📈", layout="wide")

# ==========================================
# 核心计算模块：计算技术指标 (MACD, RSI, 均线)
# ==========================================
def calculate_indicators(df):
    # 计算均线
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA50'] = df['Close'].rolling(window=50).mean()
    df['Vol5'] = df['Volume'].rolling(window=5).mean() # 5日均量
    
    # 计算 MACD
    exp1 = df['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp1 - exp2
    df['Signal_Line'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['MACD'] - df['Signal_Line']
    
    # 计算 RSI (14日)
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    return df

# ==========================================
# 功能一：个股深度诊断 (A股全面策略)
# ==========================================
def analyze_single_stock(ticker_symbol):
    st.subheader(f"[{ticker_symbol}] 深度技术诊断")
    ticker = yf.Ticker(ticker_symbol)
    
    with st.spinner('正在拉取历史数据并计算多重指标...'):
        try:
            hist = ticker.history(period="1y") # 获取1年数据以确保指标计算准确
            
            if hist.empty:
                st.error("获取不到数据，请检查代码是否正确（沪市加 .SS，深市加 .SZ，如 600519.SS）")
                return
                
            # 计算所有指标
            hist = calculate_indicators(hist)
            
            # 获取最新数据
            latest = hist.iloc[-1]
            prev = hist.iloc[-2]
            
            # 提取各项指标值
            close = latest['Close']
            ma20 = latest['MA20']
            ma50 = latest['MA50']
            macd = latest['MACD']
            signal = latest['Signal_Line']
            rsi = latest['RSI']
            vol_ratio = latest['Volume'] / latest['Vol5'] if latest['Vol5'] > 0 else 0
            
            # 1. 数据面板展示
            st.markdown("### 📊 核心指标面板")
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("最新收盘价", f"¥{close:.2f}", f"{(close - prev['Close'])/prev['Close']*100:.2f}%")
            col2.metric("20日均线 (短期)", f"¥{ma20:.2f}")
            col3.metric("MACD 柱", f"{latest['MACD_Hist']:.3f}")
            col4.metric("RSI (14日)", f"{rsi:.1f}")
            
            # 2. 综合多因子诊断逻辑
            st.markdown("### 📝 策略综合诊断结论")
            
            # 趋势判定
            if close > ma20 and ma20 > ma50:
                trend_status = "🟢 多头排列（强势）"
            elif close < ma20 and ma20 < ma50:
                trend_status = "🔴 空头排列（弱势）"
            else:
                trend_status = "🟡 震荡盘整（方向不明）"
                
            # 动能判定 (MACD)
            if macd > signal and macd > 0:
                macd_status = "🟢 水上金叉/多头发散（动能强劲）"
            elif macd > signal and macd < 0:
                macd_status = "🟡 水下金叉（反弹动能）"
            else:
                macd_status = "🔴 死叉/空头（动能衰退）"
                
            # 状态判定 (RSI)
            if rsi > 80:
                rsi_status = "🔴 超买区域（警惕回调风险）"
            elif rsi < 20:
                rsi_status = "🟢 超卖区域（存在反弹预期）"
            elif rsi >= 50:
                rsi_status = "🟢 强势区域 (多头控盘)"
            else:
                rsi_status = "🔴 弱势区域 (空头压制)"
                
            # 成交量判定
            if vol_ratio > 1.5:
                vol_status = f"🟢 明显放量 (是5日均量的 {vol_ratio:.1f} 倍)"
            elif vol_ratio < 0.8:
                vol_status = "🔴 明显缩量"
            else:
                vol_status = "⚪ 平量运行"

            # 输出诊断结果
            st.write(f"- **趋势状态 (均线)**: {trend_status}")
            st.write(f"- **涨跌动能 (MACD)**: {macd_status}")
            st.write(f"- **买卖力度 (RSI)**: {rsi_status}")
            st.write(f"- **量能表现 (Volume)**: {vol_status}")
            
            # 最终策略建议
            st.markdown("#### 💡 操作建议")
            if close > ma20 and macd > signal and rsi >= 50 and rsi <= 80:
                st.success("★★★★★ **综合评级：强烈看多**。均线、MACD与RSI形成多头共振，且未严重超买，建议顺势积极做多。")
            elif close < ma20 and macd < signal:
                st.error("☆☆☆☆☆ **综合评级：看空观望**。多项指标走坏，处于明确下跌趋势，建议空仓或防守。")
            elif close > ma20 but macd < signal:
                st.warning("★★★☆☆ **综合评级：谨慎持有**。虽然价格在均线上方，但MACD动能不足（背离或死叉），谨防冲高回落。")
            else:
                st.info("★★☆☆☆ **综合评级：震荡等待**。多空信号不一致，建议等待更明确的突破信号再做决策。")
                
        except Exception as e:
            st.error(f"分析失败: {e}")

# ==========================================
# 功能二：A股多因子策略批量扫描
# ==========================================
def batch_scan_stocks(stock_list):
    st.subheader("🚀 强势股多因子共振扫描")
    st.info(f"共需扫描 {len(stock_list)} 只股票。为防封禁，每只扫描后暂停 2 秒。")
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    good_stocks = [] 
    
    for i, symbol in enumerate(stock_list):
        status_text.text(f"正在扫描: {symbol} ({i+1}/{len(stock_list)}) ...")
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="6mo")
            
            if not hist.empty and len(hist) > 50:
                hist = calculate_indicators(hist)
                latest = hist.iloc[-1]
                
                close = latest['Close']
                ma20 = latest['MA20']
                macd = latest['MACD']
                signal = latest['Signal_Line']
                rsi = latest['RSI']
                
                # =====================================
                # 核心过滤策略：多因子共振
                # 1. 价格站上20日均线 (趋势向上)
                # 2. MACD 为多头 (MACD > Signal)
                # 3. RSI 处于 50-80 之间 (强势但未严重超买)
                # =====================================
                if (close > ma20) and (macd > signal) and (50 <= rsi <= 80):
                    good_stocks.append({
                        "股票代码": symbol,
                        "最新价": round(close, 2),
                        "20日均线": round(ma20, 2),
                        "MACD状态": "🟢 多头/金叉",
                        "RSI值": round(rsi, 1),
                        "入选理由": "均线+MACD+RSI多头共振"
                    })
        except Exception:
            pass # 容错处理
            
        progress_bar.progress((i + 1) / len(stock_list))
        if i < len(stock_list) - 1:
            time.sleep(2)  
            
    status_text.text("✅ 全部扫描完成！")
    
    if good_stocks:
        st.success(f"🎉 发现 {len(good_stocks)} 只符合【多因子共振】的强势股：")
        st.dataframe(pd.DataFrame(good_stocks), use_container_width=True)
    else:
        st.warning("扫描结束。本次股票池中极其严格，未发现完全符合[均线+MACD+RSI]共振条件的股票。")

# ==========================================
# 主程序路由设计
# ==========================================
def main():
    st.title("📈 A股智能诊断与多因子扫描系统")
    
    st.sidebar.title("功能导航")
    mode = st.sidebar.radio("请选择功能：", ["🔍 A股深度诊断", "🚀 强势股多因子扫描"])
    st.sidebar.markdown("---")
    st.sidebar.caption("输入提示：A股代码必须加后缀。\n- 沪市加 `.SS` (如 600519.SS)\n- 深市加 `.SZ` (如 000858.SZ)")

    if mode == "🔍 A股深度诊断":
        st.header("🔍 个股深度诊断 (均线+MACD+RSI+量能)")
        # 默认改为 A股 贵州茅台
        ticker_input = st.text_input("请输入单只股票代码 (如: 600519.SS):", "600519.SS")
        
        if st.button("开始诊断", type="primary"):
            if ticker_input.strip():
                analyze_single_stock(ticker_input.strip().upper())
            else:
                st.warning("请输入有效的股票代码！")
                
    elif mode == "🚀 强势股多因子扫描":
        st.header("🚀 强势股多因子扫描 (严格策略)")
        st.markdown("**选股逻辑**：价格 > 20日均线 **且** MACD处于多头 **且** RSI处于强势区(50~80)。")
        
        # 默认改为 A股常用蓝筹股池
        default_pool = "600519.SS, 000858.SZ, 600036.SS, 000001.SZ, 601318.SS, 600276.SS, 002594.SZ, 601012.SS"
        tickers_input = st.text_area("请输入 A股 股票池(用英文逗号分隔)：", default_pool)
        
        if st.button("开始批量扫描", type="primary"):
            if tickers_input.strip():
                raw_list = tickers_input.split(",")
                stock_list = [t.strip().upper() for t in raw_list if t.strip()]
                
                if len(stock_list) > 0:
                    batch_scan_stocks(stock_list)
                else:
                    st.warning("提取不到有效代码，请检查格式。")
            else:
                st.warning("股票池不能为空！")

if __name__ == "__main__":
    main()
