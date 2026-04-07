# data/eastmoney_api.py
"""
东方财富原始HTTP接口封装
不依赖任何第三方金融数据库，全部直连东方财富服务器
"""

import requests
import json
import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import streamlit as st
from config import EASTMONEY_HEADERS


class EastMoneyAPI:
    """东方财富全接口"""

    # ====================== 基础请求 ======================

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(EASTMONEY_HEADERS)

    def _request(self, url: str, params: dict, timeout: int = 15) -> dict:
        """通用请求方法，带重试"""
        for attempt in range(3):
            try:
                resp = self.session.get(url, params=params, timeout=timeout)
                resp.raise_for_status()
                text = resp.text

                # 处理JSONP格式
                if text.startswith("jQuery") or text.startswith("callback"):
                    start = text.index("(") + 1
                    end = text.rindex(")")
                    text = text[start:end]

                return json.loads(text)
            except Exception as e:
                if attempt == 2:
                    st.warning(f"API请求失败: {url} → {e}")
                    return {}
                time.sleep(0.5)
        return {}

    def _get_secid(self, stock_code: str) -> str:
        """股票代码转东方财富secid"""
        if stock_code.startswith("6"):
            return f"1.{stock_code}"
        elif stock_code.startswith(("0", "3")):
            return f"0.{stock_code}"
        elif stock_code.startswith(("4", "8")):
            return f"0.{stock_code}"
        return f"1.{stock_code}"

    # ====================== 个股K线 ======================

    def get_stock_kline(self, stock_code: str, days: int = 60,
                        klt: int = 101) -> pd.DataFrame:
        """
        获取个股K线数据
        klt: 101=日K 102=周K 103=月K
        """
        secid = self._get_secid(stock_code)
        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            "secid": secid,
            "ut": "fa5fd1943c7b386f172d6893dbfba10b",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": klt,
            "fqt": 1,  # 前复权
            "end": "20500101",
            "lmt": days,
        }
        data = self._request(url, params)
        if not data or "data" not in data or not data["data"]:
            return pd.DataFrame()

        klines = data["data"].get("klines", [])
        if not klines:
            return pd.DataFrame()

        records = []
        for line in klines:
            parts = line.split(",")
            if len(parts) >= 11:
                records.append({
                    "date": parts[0],
                    "open": float(parts[1]),
                    "close": float(parts[2]),
                    "high": float(parts[3]),
                    "low": float(parts[4]),
                    "volume": int(parts[5]),        # 手
                    "amount": float(parts[6]),       # 元
                    "amplitude": float(parts[7]),    # 振幅%
                    "change_pct": float(parts[8]),   # 涨跌幅%
                    "change_amt": float(parts[9]),   # 涨跌额
                    "turnover_rate": float(parts[10])  # 换手率%
                })

        df = pd.DataFrame(records)
        df["date"] = pd.to_datetime(df["date"])
        df["stock_code"] = stock_code
        return df

    # ====================== 个股实时行情 ======================

    def get_stock_realtime(self, stock_code: str) -> dict:
        """获取个股实时行情"""
        secid = self._get_secid(stock_code)
        url = "https://push2.eastmoney.com/api/qt/stock/get"
        params = {
            "secid": secid,
            "ut": "fa5fd1943c7b386f172d6893dbfba10b",
            "fields": "f43,f44,f45,f46,f47,f48,f50,f51,f52,f55,f57,f58,"
                       "f60,f71,f116,f117,f162,f167,f168,f169,f170,f171,"
                       "f177,f192,f193",
            "invt": 2,
        }
        data = self._request(url, params)
        if data and "data" in data:
            return data["data"]
        return {}

    # ====================== 全市场股票列表 ======================

    def get_all_stocks(self, market: str = "all") -> pd.DataFrame:
        """获取全市场股票列表+实时行情"""
        url = "https://push2.eastmoney.com/api/qt/clist/get"

        fs_map = {
            "sh": "m:1+t:2,m:1+t:23",
            "sz": "m:0+t:6,m:0+t:13,m:0+t:80",
            "all": "m:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23",
            "cyb": "m:0+t:80",
            "kcb": "m:1+t:23",
        }
        params = {
            "pn": 1, "pz": 6000,
            "po": 1, "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": 2, "invt": 2,
            "fid": "f3",
            "fs": fs_map.get(market, fs_map["all"]),
            "fields": "f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f14,f15,f16,f17,f18,f20,f21",
        }
        data = self._request(url, params)
        if not data or "data" not in data or not data["data"]:
            return pd.DataFrame()

        records = data["data"].get("diff", [])
        df = pd.DataFrame(records)
        col_map = {
            "f12": "stock_code", "f14": "stock_name",
            "f2": "latest_price", "f3": "change_pct",
            "f4": "change_amt", "f5": "volume",
            "f6": "amount", "f7": "amplitude",
            "f8": "turnover_rate", "f9": "pe_ratio",
            "f15": "high", "f16": "low",
            "f17": "open", "f18": "pre_close",
            "f20": "total_mv", "f21": "circulating_mv",
        }
        df = df.rename(columns=col_map)
        return df

    # ====================== 龙虎榜数据 ======================

    def get_dragon_tiger_list(self, date: str = None,
                               page_size: int = 200) -> pd.DataFrame:
        """
        获取龙虎榜数据
        date: YYYY-MM-DD格式
        """
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            "reportName": "RPT_DAILYBILLBOARD_DETAILSNEW",
            "columns": "ALL",
            "source": "WEB",
            "client": "WEB",
            "sortColumns": "TRADE_DATE,SECURITY_CODE",
            "sortTypes": "-1,1",
            "pageNumber": 1,
            "pageSize": page_size,
            "filter": f'(TRADE_DATE>=\'{date}\')(TRADE_DATE<=\'{date}\')',
        }
        data = self._request(url, params)
        if not data or "result" not in data or not data["result"]:
            return pd.DataFrame()

        records = data["result"].get("data", [])
        if not records:
            return pd.DataFrame()

        df = pd.DataFrame(records)

        # 标准化列名
        col_map = {
            "TRADE_DATE": "trade_date",
            "SECURITY_CODE": "stock_code",
            "SECURITY_NAME_ABBR": "stock_name",
            "CLOSE_PRICE": "close_price",
            "CHANGE_RATE": "change_pct",
            "BILLBOARD_NET_AMT": "net_amount",        # 龙虎榜净买额
            "BILLBOARD_BUY_AMT": "buy_amount",        # 龙虎榜买入额
            "BILLBOARD_SELL_AMT": "sell_amount",       # 龙虎榜卖出额
            "BILLBOARD_DEAL_AMT": "deal_amount",       # 龙虎榜成交额
            "ACCUM_AMOUNT": "total_amount",            # 总成交额
            "DEAL_NET_RATIO": "net_ratio",             # 净买入占比
            "TURNOVERRATE": "turnover_rate",
            "FREE_MARKET_CAP": "free_mv",
            "EXPLANATION": "reason",                    # 上榜原因
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        return df

    # ====================== 龙虎榜营业部明细 ======================

    def get_dragon_tiger_detail(self, stock_code: str,
                                 date: str) -> pd.DataFrame:
        """获取龙虎榜营业部买卖明细"""
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            "reportName": "RPT_BILLBOARD_DAILYDETAILSBUY",  # 买入明细
            "columns": "ALL",
            "source": "WEB",
            "client": "WEB",
            "sortColumns": "BUY",
            "sortTypes": "-1",
            "pageNumber": 1,
            "pageSize": 50,
            "filter": f"(TRADE_DATE='{date}')(SECURITY_CODE=\"{stock_code}\")",
        }

        # 买入方
        data_buy = self._request(url, params)
        buy_records = []
        if data_buy and "result" in data_buy and data_buy["result"]:
            buy_records = data_buy["result"].get("data", [])

        # 卖出方
        params["reportName"] = "RPT_BILLBOARD_DAILYDETAILSSELL"
        params["sortColumns"] = "SELL"
        data_sell = self._request(url, params)
        sell_records = []
        if data_sell and "result" in data_sell and data_sell["result"]:
            sell_records = data_sell["result"].get("data", [])

        results = []
        for r in buy_records:
            results.append({
                "trade_date": date,
                "stock_code": stock_code,
                "direction": "买入",
                "seat_name": r.get("OPERATEDEPT_NAME", ""),
                "buy_amount": r.get("BUY", 0),
                "sell_amount": r.get("SELL", 0),
                "net_amount": r.get("NET", 0),
                "rank": r.get("RANK", 0),
            })
        for r in sell_records:
            results.append({
                "trade_date": date,
                "stock_code": stock_code,
                "direction": "卖出",
                "seat_name": r.get("OPERATEDEPT_NAME", ""),
                "buy_amount": r.get("BUY", 0),
                "sell_amount": r.get("SELL", 0),
                "net_amount": r.get("NET", 0),
                "rank": r.get("RANK", 0),
            })

        return pd.DataFrame(results)

    # ====================== 龙虎榜营业部统计 ======================

    def get_seat_statistics(self, days: int = 30) -> pd.DataFrame:
        """获取营业部龙虎榜统计排名"""
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            "reportName": "RPT_OPERATEDEPT_TRADE",
            "columns": "ALL",
            "source": "WEB",
            "client": "WEB",
            "sortColumns": "TOTAL_NETAMT",
            "sortTypes": "-1",
            "pageNumber": 1,
            "pageSize": 100,
            "filter": "",
        }
        data = self._request(url, params)
        if not data or "result" not in data or not data["result"]:
            return pd.DataFrame()
        records = data["result"].get("data", [])
        return pd.DataFrame(records) if records else pd.DataFrame()

    # ====================== 大宗交易数据 ======================

    def get_block_trades(self, start_date: str = None,
                          end_date: str = None,
                          page_size: int = 500) -> pd.DataFrame:
        """获取大宗交易数据"""
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            "reportName": "RPT_BLOCK_TRADEINFOR",
            "columns": "ALL",
            "source": "WEB",
            "client": "WEB",
            "sortColumns": "TRADE_DATE",
            "sortTypes": "-1",
            "pageNumber": 1,
            "pageSize": page_size,
            "filter": f"(TRADE_DATE>='{start_date}')(TRADE_DATE<='{end_date}')",
        }
        data = self._request(url, params)
        if not data or "result" not in data or not data["result"]:
            return pd.DataFrame()

        records = data["result"].get("data", [])
        if not records:
            return pd.DataFrame()

        df = pd.DataFrame(records)
        col_map = {
            "TRADE_DATE": "trade_date",
            "SECURITY_CODE": "stock_code",
            "SECURITY_NAME_ABBR": "stock_name",
            "CLOSE_PRICE": "close_price",
            "DEAL_PRICE": "deal_price",        # 成交价
            "PREMIUM_RATIO": "premium_pct",     # 溢价率%（负=折价）
            "DEAL_AMOUNT": "deal_amount",       # 成交额(元)
            "DEAL_VOLUME": "deal_volume",       # 成交量(股)
            "BUYER_NAME": "buyer",              # 买方
            "SELLER_NAME": "seller",            # 卖方
            "CHANGE_RATE_1DAYS": "next_1d_pct",   # 次日涨幅
            "CHANGE_RATE_5DAYS": "next_5d_pct",   # 5日涨幅
            "CHANGE_RATE_10DAYS": "next_10d_pct",
            "CHANGE_RATE_20DAYS": "next_20d_pct",
            "D1_CLOSE_ADJCHRATE": "adj_next_1d",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        return df

    # ====================== 股东减持/增持公告 ======================

    def get_shareholder_changes(self, change_type: str = "减持",
                                 page_size: int = 200) -> pd.DataFrame:
        """
        获取重要股东增减持数据
        change_type: '减持' / '增持'
        """
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"

        if change_type == "减持":
            report = "RPT_SHARE_REDUCE"
        else:
            report = "RPT_SHARE_INCREASE"

        params = {
            "reportName": report,
            "columns": "ALL",
            "source": "WEB",
            "client": "WEB",
            "sortColumns": "END_DATE",
            "sortTypes": "-1",
            "pageNumber": 1,
            "pageSize": page_size,
        }
        data = self._request(url, params)
        if not data or "result" not in data or not data["result"]:
            return pd.DataFrame()

        records = data["result"].get("data", [])
        if not records:
            return pd.DataFrame()

        df = pd.DataFrame(records)
        col_map = {
            "SECURITY_CODE": "stock_code",
            "SECURITY_NAME_ABBR": "stock_name",
            "END_DATE": "end_date",               # 减持截止日
            "START_DATE": "start_date",            # 减持起始日
            "CHANGE_SHARES_RATIO": "change_ratio", # 变动比例%
            "HOLDER_NAME": "holder_name",          # 股东名
            "HOLDER_TYPE": "holder_type",          # 高管/股东
            "AVG_PRICE": "avg_price",              # 均价
            "CHANGE_AMOUNT": "change_amount",      # 变动金额
            "CLOSE_PRICE_BEFORE": "price_before",
            "CLOSE_PRICE_AFTER": "price_after",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        return df

    # ====================== 融资融券数据 ======================

    def get_margin_data_market(self) -> pd.DataFrame:
        """获取全市场融资融券汇总数据"""
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            "reportName": "RPTA_WEB_RZRQ_GGMX",
            "columns": "ALL",
            "source": "WEB",
            "client": "WEB",
            "sortColumns": "TRADE_DATE",
            "sortTypes": "-1",
            "pageNumber": 1,
            "pageSize": 30,
        }
        data = self._request(url, params)
        if not data or "result" not in data or not data["result"]:
            return pd.DataFrame()
        records = data["result"].get("data", [])
        return pd.DataFrame(records) if records else pd.DataFrame()

    def get_margin_data_stock(self, stock_code: str = None,
                               page_size: int = 200) -> pd.DataFrame:
        """获取个股融资融券明细"""
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            "reportName": "RPTA_WEB_RZRQ_GGMX",
            "columns": "ALL",
            "source": "WEB",
            "client": "WEB",
            "sortColumns": "TRADE_DATE",
            "sortTypes": "-1",
            "pageNumber": 1,
            "pageSize": page_size,
        }
        if stock_code:
            params["filter"] = f'(SECURITY_CODE="{stock_code}")'

        data = self._request(url, params)
        if not data or "result" not in data or not data["result"]:
            return pd.DataFrame()

        records = data["result"].get("data", [])
        if not records:
            return pd.DataFrame()

        df = pd.DataFrame(records)
        col_map = {
            "TRADE_DATE": "trade_date",
            "SECURITY_CODE": "stock_code",
            "SECURITY_NAME_ABBR": "stock_name",
            "RZYE": "rz_balance",         # 融资余额
            "RZMRE": "rz_buy",            # 融资买入额
            "RZCHE": "rz_repay",          # 融资偿还额
            "RQYE": "rq_balance",         # 融券余额(元)
            "RQYL": "rq_volume",          # 融券余量(股)
            "RQMCL": "rq_sell_volume",    # 融券卖出量
            "RQCHL": "rq_return_volume",  # 融券偿还量
            "RZRQYE": "total_balance",    # 融资融券余额
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        return df

    # ====================== 融资融券变动排名 ======================

    def get_
