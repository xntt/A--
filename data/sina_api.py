# data/sina_api.py
"""新浪财经备用接口"""

import requests
import re
import json
import pandas as pd
from datetime import datetime
from config import SINA_HEADERS


class SinaAPI:
    """新浪财经API - 东方财富接口故障时的备用"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(SINA_HEADERS)

    def get_realtime_quote(self, stock_code: str) -> dict:
        """
        新浪实时行情
        stock_code: 纯数字如 '600519'
        """
        prefix = "sh" if stock_code.startswith("6") else "sz"
        symbol = f"{prefix}{stock_code}"
        url = f"https://hq.sinajs.cn/list={symbol}"

        try:
            resp = self.session.get(url, timeout=5)
            resp.encoding = "gbk"
            text = resp.text.strip()
            match = re.search(r'"(.+)"', text)
            if not match:
                return {}

            parts = match.group(1).split(",")
            if len(parts) < 32:
                return {}

            return {
                "stock_name": parts[0],
                "open": float(parts[1]),
                "pre_close": float(parts[2]),
                "latest_price": float(parts[3]),
                "high": float(parts[4]),
                "low": float(parts[5]),
                "volume": int(parts[8]),       # 手
                "amount": float(parts[9]),     # 元
                "date": parts[30],
                "time": parts[31],
            }
        except Exception:
            return {}

    def get_realtime_batch(self, stock_codes: list) -> pd.DataFrame:
        """批量获取实时行情"""
        symbols = []
        for code in stock_codes:
            prefix = "sh" if code.startswith("6") else "sz"
            symbols.append(f"{prefix}{code}")

        url = f"https://hq.sinajs.cn/list={','.join(symbols)}"
        try:
            resp = self.session.get(url, timeout=10)
            resp.encoding = "gbk"
            lines = resp.text.strip().split("\n")

            records = []
            for i, line in enumerate(lines):
                match = re.search(r'"(.+)"', line)
                if not match:
                    continue
                parts = match.group(1).split(",")
                if len(parts) < 32:
                    continue

                pre_close = float(parts[2]) if float(parts[2]) > 0 else 1
                latest = float(parts[3])
                change_pct = (latest - pre_close) / pre_close * 100

                records.append({
                    "stock_code": stock_codes[i] if i < len(stock_codes) else "",
                    "stock_name": parts[0],
                    "open": float(parts[1]),
                    "pre_close": pre_close,
                    "latest_price": latest,
                    "high": float(parts[4]),
                    "low": float(parts[5]),
                    "volume": int(parts[8]),
                    "amount": float(parts[9]),
                    "change_pct": round(change_pct, 2),
                })
            return pd.DataFrame(records)
        except Exception:
            return pd.DataFrame()

    def get_money_flow(self, stock_code: str) -> dict:
        """新浪个股资金流"""
        prefix = "sh" if stock_code.startswith("6") else "sz"
        symbol = f"{prefix}{stock_code}"
        url = f"https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssi_ssfx_flzjtj?daession=&stock={symbol}"

        try:
            resp = self.session.get(url, timeout=5)
            data = json.loads(resp.text)
            if isinstance(data, list) and len(data) > 0:
                return data[0]
            return {}
        except Exception:
            return {}


sina_api = SinaAPI()
