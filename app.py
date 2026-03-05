import streamlit as st
import pandas as pd
import requests
import concurrent.futures
from datetime import datetime
import re
import json

st.set_page_config(page_title="量化交易雷达", layout="wide")

if "found_stocks" not in st.session_state:
    st.session_state.found_stocks = []
if "current_strategy" not in st.session_state:
    st.session_state.current_strategy = "尚未选择"

# ================= 100%纯血新浪引擎：获取全市场股票名单 =================
def fetch_all_stock_codes():
    # 彻底弃用网易/东方财富，改用新浪API直接拉取所有沪深A股名单
    url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
    params = {
        "page": "1", 
        "num": "6000", # 一次性拉取6000只
        "sort": "symbol", 
        "asc": "1", 
        "node": "hs_a", 
        "symbol": "", 
        "_s_r_a": "init"
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
                # 过滤掉 ST 股
                if c and n and not n.startswith("ST") and not n.startswith("*ST"):
                    clean_code = c[-6:] # 提取后6位纯数字代码
                    valid_stocks.append({'f12': clean_code, 'f14': n})
        return valid_stocks
    except Exception as e:
        return []

# ================= 100%纯血新浪引擎：获取单只股票K线 =================
def fetch_kline_data_sina(stock_code, days=65):
    code_str = str(stock_code).strip().zfill(6)
    
    # 彻底抛弃f-string语法，使用最基础的加号拼接，杜绝一切括号没复制全的报错！
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

def calculate_indicators(df):
    if df.empty: return df
    df['MA5'] = df['Close'].rolling(window=5, min_periods=1).mean()
    df['MA10'] = df['Close'].rolling(window=10, min_periods=1).mean()
    df['MA20'] = df['Close'].rolling(window=20, min_periods=1).mean()
    df['MA60'] = df['Close'].rolling(window=60, min_periods=1).mean()
    df['VMA5'] = df['Volume'].rolling(window=5, min_periods=1).mean()
    df['VMA20'] = df['Volume'].rolling(window=20, min_periods=1).mean()
    return df

# ================= 极简主界面 UI =================
st.sidebar.title("⚡ 智能量化交易工作流")
mode = st.sidebar.radio("选择工作流阶段：", [
    "🎯 阶段一：全市场海选 (粗筛)"
])

if mode == "🎯 阶段一：全市场海选 (粗筛)":
    st.title("🎯 全市场潜伏雷达 (100%纯新浪版)")
    strategy = st.radio("选择海选策略：", ["趋势低吸", "底部启动", "稳健波段"])
    
    if st.button("🚀 启动纯血新浪扫描", type="primary"):
        st.session_state.current_strategy = strategy
        st.session_state.found_stocks = [] 
        
        with st.spinner("正在从【新浪财经】获取全市场沪深A股名单..."):
            all_stocks = fetch_all_stock_codes()
            
        if not all_stocks:
            st.error("🚨 致命错误：新浪获取名单失败！请检查你的代理规则是否拦截了新浪 API。")
            st.stop()
        else:
            st.success(f"✅ 成功从新浪获取到 {len(all_stocks)} 只股票！开始扫描 K 线...")

        # 四大监控面板
        col1, col2, col3, col4 = st.columns(4)
        count_total = col1.metric("已扫描", "0")
        count_api_fail = col2.metric("❌新浪无数据", "0")
        count_logic_fail = col3.metric("📉形态不符", "0")
        count_success = col4.metric("🎉成功入选", "0")
        
        progress_bar = st.progress(0)
        found_list = []
        stats = {"total": 0, "api_fail": 0, "logic_fail": 0, "success": 0}
        
        # 扫描前 500 只作为测试（保证速度）
        test_stocks = all_stocks[:500] 
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

        # 多线程扫描
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
                
                # 动态更新数据面板
                if count % 5 == 0 or count == test_total:
                    progress_bar.progress(count / test_total)
                    count_total.metric("已扫描", f"{stats['total']} / {test_total}")
                    count_api_fail.metric("❌新浪无数据", stats['api_fail'])
                    count_logic_fail.metric("📉形态不符", stats['logic_fail'])
                    count_success.metric("🎉成功入选", stats['success'])
        
        st.session_state.found_stocks = found_list
        progress_bar.progress(1.0)
        
        if found_list:
            st.balloons()
            df_result = pd.DataFrame(found_list)
            st.dataframe(df_result, use_container_width=True)
            csv_data = df_result.to_csv(index=False).encode('utf-8-sig')
            st.download_button("💾 下载 CSV", data=csv_data, file_name=f"新浪海选_{datetime.now().strftime('%Y%m%d')}.csv", mime="text/csv", type="primary")
        else:
            st.warning("⚠️ 扫描结束。请看上方【四个数据面板】，如果是【新浪无数据】多，说明代理封了K线；如果是【形态不符】多，说明一切正常，只是今天前500只里没有这种图形的股票！")
