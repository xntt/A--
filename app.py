import streamlit as st
import pandas as pd
import requests
import concurrent.futures
from datetime import datetime
import re
import json
import io

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
    
    # 最稳妥的字符串拼接，防SyntaxError
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

# ========
