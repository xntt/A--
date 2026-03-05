import streamlit as st
import pandas as pd
import requests
import time
import concurrent.futures
from datetime import datetime
import re
import json

st.set_page_config(page_title="量化交易雷达系统", layout="wide")

if "found_stocks" not in st.session_state:
    st.session_state.found_stocks = []
if "current_strategy" not in st.session_state:
    st.session_state.current_strategy = "尚未选择"

# ================= 全新：网易163 股票名单获取引擎 =================
def fetch_all_stock_codes():
    # 彻底弃用东方财富，改用网易163财经接口获取全市场股票
    url = "http://quotes.money.163.com/hs/service/diyrank.php"
    params = {
        "page": 0, "query": "STYPE:EQA", "fields": "SYMBOL,NAME",
        "sort": "SYMBOL", "order": "asc", "count": 5000, "type": "query"
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        response = requests.get(url, params=params, headers=headers, timeout=5)
        data = response.json()
        valid_stocks = []
        for s in data.get('list', []):
            code = s.get('SYMBOL')
            name = s.get('NAME')
            if code and name and not name.startswith('ST') and not name.startswith('*ST'):
                valid_stocks.append({'f12': str(code).zfill(6), 'f14': name})
        return valid_stocks
    except Exception as e:
        return []

# ================= 纯血：新浪财经 K线获取引擎 =================
def fetch_kline_data_sina(stock_code, days=100):
    code_str = str(stock_code).strip().zfill(6)
    prefix = 'sh' if code_str.startswith(('6', '9')) else 'sz'
    symbol = f"{prefix}{code_str}"
    
    url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {
        "symbol": symbol,
        "scale": "240", 
        "ma": "no",
        "datalen": str(days)
    }
    headers = {
        "Referer": "http://finance.sina.com.cn/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=3)
        text = response.text
        text = re.sub(r'([{,])\s*([a-zA-Z_]+)\s*:', r'\1"\2":', text)
        data = json.loads(text)
        
        if data and isinstance(data, list):
            parsed_data = []
            for k in data:
                parsed_data.append({
                    "Date": k.get("day"),
                    "Open": float(k.get("open", 0)),
                    "Close": float(k.get("close", 0)),
                    "High": float(k.get("high", 0)),
                    "Low": float(k.get("low", 0)),
                    "Volume": float(k.get("volume", 0))
                })
            return pd.DataFrame(parsed_data)
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

# ================= 侧边栏 =================
st.sidebar.title("⚡ 智能量化交易工作流")
mode = st.sidebar.radio("选择工作流阶段：", [
    "🎯 阶段一：全市场海选 (粗筛)", 
    "🏆 阶段二：深度过滤与打分 (精选)", 
    "🔍 阶段三：个股形态复诊"
])

# ================= 主程序 =================
if mode == "🎯 阶段一：全市场海选 (粗筛)":
    st.title("🎯 全市场潜伏雷达 (阶段一：海选)")
    strategy = st.radio("选择海选策略：", ["趋势低吸", "底部启动", "稳健波段"])
    
    if st.button("🚀 启动全市场粗筛", type="primary"):
        st.session_state.current_strategy = strategy
        st.session_state.found_stocks = [] 
        
        # 1. 拦截诊断：看网易接口能否拿到股票名单
        with st.spinner("正在从网易财经获取全市场股票名单..."):
            all_stocks = fetch_all_stock_codes()
            
        if not all_stocks:
            st.error("🚨 致命错误：连网易接口也被拦截了，无法获取股票名单（获取到了 0 只）。请检查网络代理或防火墙。")
            st.stop() # 直接停止运行
        else:
            st.success(f"✅ 成功从网易获取到 {len(all_stocks)} 只股票名单！开始扫描 K 线...")

        # 设置 X光透视仪 UI
        col1, col2, col3, col4 = st.columns(4)
        count_total = col1.metric("已扫描", "0")
        count_api_fail = col2.metric("新浪接口拒接(空数据)", "0")
        count_logic_fail = col3.metric("形态不符被踢出", "0")
        count_success = col4.metric("🎉 成功入选", "0")
        
        progress_bar = st.progress(0)
        
        found_list = []
        stats = {"total": 0, "api_fail": 0, "logic_fail": 0, "success": 0}
        
        # 取前 500 只测试，避免新浪封IP
        test_stocks = all_stocks[:500] 
        test_total = len(test_stocks)
        
        def process_stock(stock_info):
            code = stock_info['f12']
            name = stock_info['f14']
            
            hist = fetch_kline_data_sina(code, days=65) 
            if hist.empty or len(hist) < 2: 
                return ("api_fail", None) # 接口拉取失败
            
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
                return ("success", {"股票代码": str(code).zfill(6), "股票名称": name, "当前价": latest['Close'], "入选核心逻辑": strategy})
            else:
                return ("logic_fail", None)

        # 启动多线程
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_stock = {executor.submit(process_stock, stock): stock for stock in test_stocks} 
            for count, future in enumerate(concurrent.futures.as_completed(future_to_stock), 1):
                status, res = future.result()
                
                # 统计归类
                stats["total"] += 1
                if status == "api_fail": stats["api_fail"] += 1
                elif status == "logic_fail": stats["logic_fail"] += 1
                elif status == "success": 
                    stats["success"] += 1
                    found_list.append(res)
                
                # 每跑 5 个更新一次 UI 面板
                if count % 5 == 0 or count == test_total:
                    progress_bar.progress(count / test_total)
                    count_total.metric("已扫描", f"{stats['total']} / {test_total}")
                    count_api_fail.metric("新浪接口拒接(空数据)", stats['api_fail'])
                    count_logic_fail.metric("形态不符被踢出", stats['logic_fail'])
                    count_success.metric("🎉 成功入选", stats['success'])
        
        st.session_state.found_stocks = found_list
        progress_bar.progress(1.0)
        
        if found_list:
            st.balloons()
            df_result = pd.DataFrame(st.session_state.found_stocks)
            st.dataframe(df_result, use_container_width=True)
            csv_data = df_result.to_csv(index=False).encode('utf-8-sig')
            st.download_button("💾 下载本次海选结果 (CSV文件)", data=csv_data, file_name=f"海选结果_{datetime.now().strftime('%Y%m%d')}.csv", mime="text/csv", type="primary")
        else:
            st.warning("⚠️ 扫描结束，虽然没报错，但没找到符合策略的股票。你可以看看上面的数据面板，如果是【形态不符】很多，说明今天大盘没出这种图形；如果是【新浪拒接】很多，说明新浪把咱们屏蔽了！")

elif mode == "🏆 阶段二：深度过滤与打分 (精选)":
    # 暂时隐藏阶段二代码以突出解决当前“没记录”的痛点
    st.info("请先前往阶段一运行【🎯 阶段一：全市场海选 (粗筛)】，看看透视面板上到底是哪一项出了问题！")
