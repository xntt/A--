import streamlit as st
import pandas as pd
import requests
import concurrent.futures
from datetime import datetime
import re
import json

st.set_page_config(page_title="量化交易雷达系统", layout="wide")

# ================= 全局状态初始化 =================
if "found_stocks" not in st.session_state:
    st.session_state.found_stocks = []
if "current_strategy" not in st.session_state:
    st.session_state.current_strategy = "尚未选择"

# ================= 纯血新浪引擎 1：获取股票名单 =================
def fetch_all_stock_codes():
    url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
    params = {
        "page": "1", "num": "6000", "sort": "symbol", "asc": "1", 
        "node": "hs_a", "symbol": "", "_s_r_a": "init"
    }
    try:
        res = requests.get(url, params=params, timeout=5)
        text = res.text
        # 修复新浪JSON没有双引号的毛病
        text = re.sub(r'([{,])\s*([a-zA-Z_0-9]+)\s*:', r'\1"\2":', text)
        data = json.loads(text)
        
        valid_stocks = []
        if isinstance(data, list):
            for item in data:
                c = item.get("symbol", "")
                n = item.get("name", "")
                if c and n and not n.startswith("ST") and not n.startswith("*ST"):
                    clean_code = c[-6:] # 提取后6位
                    valid_stocks.append({'f12': clean_code, 'f14': n})
        return valid_stocks
    except Exception as e:
        return []

# ================= 纯血新浪引擎 2：获取K线 =================
def fetch_kline_data_sina(stock_code, days=65):
    code_str = str(stock_code).strip().zfill(6)
    
    # 采用最原始的字符串拼接，杜绝任何复制不全导致的语法错误
    if code_str.startswith('6') or code_str.startswith('9'):
        prefix = 'sh'
    else:
        prefix = 'sz'
    symbol = prefix + code_str 
    
    url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {"symbol": symbol, "scale": "240", "ma": "no", "datalen": str(days)}
    
    try:
        res = requests.get(url, params=params, timeout=3)
        text = res.text
        text = re.sub(r'([{,])\s*([a-zA-Z_0-9]+)\s*:', r'\1"\2":', text)
        data = json.loads(text)
        
        if data and isinstance(data, list):
            parsed = []
            for k in data:
                parsed.append({
                    "Date": k.get("day"),
                    "Open": float(k.get("open", 0)),
                    "Close": float(k.get("close", 0)),
                    "High": float(k.get("high", 0)),
                    "Low": float(k.get("low", 0)),
                    "Volume": float(k.get("volume", 0))
                })
            return pd.DataFrame(parsed)
    except Exception:
        pass
    return pd.DataFrame()

# ================= 指标计算 =================
def calculate_indicators(df):
    if df.empty: return df
    df['MA5'] = df['Close'].rolling(window=5, min_periods=1).mean()
    df['MA10'] = df['Close'].rolling(window=10, min_periods=1).mean()
    df['MA20'] = df['Close'].rolling(window=20, min_periods=1).mean()
    df['MA60'] = df['Close'].rolling(window=60, min_periods=1).mean()
    df['VMA5'] = df['Volume'].rolling(window=5, min_periods=1).mean()
    df['VMA20'] = df['Volume'].rolling(window=20, min_periods=1).mean()
    return df

# ================= 侧边栏导航 =================
st.sidebar.title("⚡ 智能量化交易工作流")
mode = st.sidebar.radio("选择阶段：", [
    "🎯 阶段一：全市场海选 (粗筛)", 
    "🏆 阶段二：深度过滤与打分 (精选)", 
    "🔍 阶段三：个股形态复诊"
])

# ================= 阶段一：全市场海选 =================
if mode == "🎯 阶段一：全市场海选 (粗筛)":
    st.title("🎯 全市场潜伏雷达 (阶段一：海选)")
    strategy = st.radio("选择海选策略：", ["趋势低吸", "底部启动", "稳健波段"])
    scan_limit = st.slider("选择本次扫描数量（防封IP建议500-1000）：", 100, 5000, 500, step=100)
    
    if st.button("🚀 启动全市场粗筛", type="primary"):
        st.session_state.current_strategy = strategy
        st.session_state.found_stocks = [] 
        
        with st.spinner("正在从【新浪财经】拉取全市场名单..."):
            all_stocks = fetch_all_stock_codes()
            
        if not all_stocks:
            st.error("🚨 致命错误：新浪获取名单失败！可能是网络被墙或代理规则拦截。")
            st.stop()
        else:
            st.success("✅ 成功从新浪获取到 " + str(len(all_stocks)) + " 只股票名单！开始扫描...")

        col1, col2, col3, col4 = st.columns(4)
        count_total = col1.metric("已扫描", "0")
        count_api_fail = col2.metric("❌新浪无数据", "0")
        count_logic_fail = col3.metric("📉形态不符", "0")
        count_success = col4.metric("🎉成功入选", "0")
        
        progress_bar = st.progress(0)
        found_list = []
        stats = {"total": 0, "api_fail": 0, "logic_fail": 0, "success": 0}
        
        test_stocks = all_stocks[:scan_limit] 
        test_total = len(test_stocks)
        
        def process_stock(stock_info):
            code = stock_info['f12']
            name = stock_info['f14']
            
            hist = fetch_kline_data_sina(code, days=65) 
            if hist.empty or len(hist) < 2: 
                return ("api_fail", None)
            
            df = calculate_indicators(hist)
            latest = df.iloc[-1]
            prev1 = df.iloc[-2]
            
            is_match = False
            try:
                if "趋势低吸" in strategy and (latest['MA20'] > latest['MA60'] and abs(latest['Close'] - latest['MA20']) / latest['MA20'] < 0.02 and latest['Volume'] < latest['VMA5'] * 0.7): is_match = True
                elif "底部启动" in strategy and (latest['Close'] > latest['MA60'] and prev1['Close'] <= prev1['MA60'] and latest['Volume'] > latest['VMA20'] * 2.5): is_match = True
                elif "稳健波段" in strategy and (latest['MA5'] > latest['MA10'] > latest['MA20'] > latest['MA60'] and latest['Close'] > latest['MA5'] and latest['Volume'] > latest['VMA5']): is_match = True
            except Exception:
                return ("logic_fail", None)
            
            if is_match: 
                return ("success", {"股票代码": code, "股票名称": name, "当前价": round(latest['Close'], 2), "逻辑": strategy})
            else:
                return ("logic_fail", None)

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_stock = {executor.submit(process_stock, stock): stock for stock in test_stocks} 
            for count, future in enumerate(concurrent.futures.as_completed(future_to_stock), 1):
                status, res = future.result()
                
                stats["total"] += 1
                if status == "api_fail": stats["api_fail"] += 1
                elif status == "logic_fail": stats["logic_fail"] += 1
                elif status == "success": 
                    stats["success"] += 1
                    found_list.append(res)
                
                if count % 5 == 0 or count == test_total:
                    progress_bar.progress(count / test_total)
                    count_total.metric("已扫描", str(stats['total']) + " / " + str(test_total))
                    count_api_fail.metric("❌新浪无数据", stats['api_fail'])
                    count_logic_fail.metric("📉形态不符", stats['logic_fail'])
                    count_success.metric("🎉成功入选", stats['success'])
        
        st.session_state.found_stocks = found_list
        progress_bar.progress(1.0)
        
        if found_list:
            st.balloons()
            df_result = pd.DataFrame(found_list)
            st.dataframe(df_result, use_container_width=True)
        else:
            st.warning("⚠️ 扫描结束，前 " + str(scan_limit) + " 只股票中没有符合该策略的，请调整策略或增加扫描数量。")

# ================= 阶段二：深度过滤与打分 =================
elif mode == "🏆 阶段二：深度过滤与打分 (精选)":
    st.title("🏆 AI 深度打分与精选")
    
    if not st.session_state.found_stocks:
        st.warning("⚠️ 暂无数据！请先在【阶段一】运行海选。")
    else:
        st.info("💡 对阶段一入选的 " + str(len(st.session_state.found_stocks)) + " 只股票进行二次深度体检。")
        if st.button("🚀 开始深度打分"):
            scored_stocks = []
            progress_bar = st.progress(0)
            total_found = len(st.session_state.found_stocks)
            
            for i, stock in enumerate(st.session_state.found_stocks):
                code = stock['股票代码']
                df = fetch_kline_data_sina(code, days=30)
                score = 60 # 基础分
                
                if not df.empty and len(df) >= 20:
                    df = calculate_indicators(df)
                    latest = df.iloc[-1]
                    
                    # 加分项
                    if latest['Close'] > latest['MA5']: score += 10
                    if latest['Close'] > latest['MA20']: score += 10
                    if latest['MA5'] > latest['MA20']: score += 10
                    if latest['Volume'] > latest['VMA5']: score += 10
                    
                stock['综合打分'] = score
                scored_stocks.append(stock)
                progress_bar.progress((i + 1) / total_found)
                
            df_scored = pd.DataFrame(scored_stocks).sort_values(by="综合打分", ascending=False)
            st.success("✅ 打分完成！")
            st.dataframe(df_scored, use_container_width=True)

# ================= 阶段三：个股形态复诊 =================
elif mode == "🔍 阶段三：个股形态复诊":
    st.title("🔍 个股形态复诊 (X光看诊)")
    
    # 支持手动输入，也支持从刚才选出来的列表里选
    preset_codes = [s['股票代码'] + " - " + s['股票名称'] for s in st.session_state.found_stocks] if st.session_state.found_stocks else []
    
    col1, col2 = st.columns(2)
    selected_preset = col1.selectbox("快速选择海选出的股票：", ["手动输入"] + preset_codes)
    manual_input = col2.text_input("或者手动输入6位代码（如 000001）：")
    
    if st.button("📊 生成诊断报告"):
        target_code = ""
        if manual_input and manual_input.isdigit() and len(manual_input) == 6:
            target_code = manual_input
        elif selected_preset != "手动输入":
            target_code = selected_preset.split(" - ")[0]
            
        if not target_code:
            st.warning("⚠️ 请输入或选择正确的6位股票代码！")
        else:
            with st.spinner("正在获取新浪K线数据..."):
                df = fetch_kline_data_sina(target_code, days=120)
                
            if df.empty:
                st.error("❌ 获取数据失败，请检查代码或网络！")
            else:
                df = calculate_indicators(df)
                latest = df.iloc[-1]
                
                st.subheader(target_code + " 近期走势分析")
                
                # 绘制趋势图
                chart_data = df.set_index('Date')[['Close', 'MA10', 'MA20']]
                st.line_chart(chart_data)
                
                st.markdown("### 📈 量化诊断结果")
                colA, colB, colC = st.columns(3)
                colA.metric("当前收盘价", round(latest['Close'], 2))
                colB.metric("20日均线 (防守位)", round(latest['MA20'], 2))
                
                trend_status = "🔴 跌破防守" if latest['Close'] < latest['MA20'] else "🟢 趋势良好"
                colC.metric("当前状态", trend_status)
                
                st.info("📝 **AI 提示：** 蓝线为收盘价，只要收盘价在MA20（均线）之上，就说明处于多头行情，否则建议观望。")
