import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime
import re
import json

# ================= 页面配置 =================
st.set_page_config(page_title="量化交易雷达系统 - 纯血新浪版", layout="wide")

if "found_stocks" not in st.session_state:
    st.session_state.found_stocks = []
if "current_strategy" not in st.session_state:
    st.session_state.current_strategy = "尚未选择"

# ================= 纯血新浪数据引擎 =================

# 【彻底替换】：用新浪接口获取全市场 A 股名单
def fetch_all_stock_codes_sina():
    # 新浪获取沪深A股节点的API
    url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
    params = {
        "page": "1", 
        "num": "5000", # 一次性拉取5000只
        "sort": "symbol", 
        "asc": "1", 
        "node": "hs_a", 
        "symbol": "", 
        "_s_r_a": "init"
    }
    try:
        response = requests.get(url, params=params, timeout=5)
        text = response.text
        
        # 修复新浪变态的不规范JSON (键名没有引号)
        text = re.sub(r'([{,])\s*([a-zA-Z_0-9]+)\s*:', r'\1"\2":', text)
        data = json.loads(text)
        
        valid_stocks = []
        if isinstance(data, list):
            for item in data:
                # 过滤ST股
                name = item.get("name", "")
                if not name.startswith("ST") and not name.startswith("*ST"):
                    # 提取六位纯数字代码 (如 sh600000 变成 600000)
                    symbol = item.get("symbol", "")
                    match = re.search(r'\d{6}', symbol)
                    if match:
                        valid_stocks.append({"f12": match.group(), "f14": name})
            return valid_stocks
    except Exception as e:
        return str(e) # 返回错误信息供UI显示
    return []

# 【纯血新浪K线获取】
def fetch_kline_data_sina(stock_code, days=100):
    code_str = str(stock_code).strip().zfill(6)
    prefix = 'sh' if code_str.startswith(('6', '9')) else 'sz'
    symbol = f"{prefix}{
