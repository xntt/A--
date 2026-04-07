# eastmoney_api.py
"""东方财富全部HTTP原始接口 — 不依赖任何第三方库"""

import requests
import json
import time
import pandas as pd
from datetime import datetime, timedelta
from config import HEADERS


class EastMoneyAPI:
    """东方财富数据接口"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    # ──────────── 通用请求 ────────────

    def _req(self, url, params, timeout=15):
        """通用GET请求，自动处理JSONP，带重试"""
        for i in range(3):
            try:
                r = self.session.get(url, params=params, timeout=timeout)
                r.raise_for_status()
                t = r.text.strip()
                if t.startswith("jQuery") or t.startswith("callback"):
                    t = t[t.index("(") + 1: t.rindex(")")]
                return json.loads(t)
            except Exception:
                if i == 2:
                    return {}
                time.sleep(0.3)
        return {}

    def _secid(self, code):
        """股票代码 → secid"""
        if code.startswith("6"):
            return f"1.{code}"
        return f"0.{code}"

    # ──────────── datacenter通用 ────────────

    def _dc_query(self, report, columns="ALL", sort_col="",
                  sort_type="-1", page=1, size=200, filt=""):
        """东方财富datacenter通用查询"""
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            "reportName": report,
            "columns": columns,
            "source": "WEB",
            "client": "WEB",
            "sortColumns": sort_col,
            "sortTypes": sort_type,
            "pageNumber": page,
            "pageSize": size,
        }
        if filt:
            params["filter"] = filt
        data = self._req(url, params)
        if data and "result" in data and data["result"]:
            records = data["result"].get("data", [])
            if records:
                return pd.DataFrame(records)
        return pd.DataFrame()

    # ──────────── 1. 个股K线 ────────────

    def get_kline(self, code, days=60):
        """个股日K线"""
        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            "secid": self._secid(code),
            "ut": "fa5fd1943c7b386f172d6893dbfba10b",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": 101, "fqt": 1,
            "end": "20500101", "lmt": days,
        }
        data = self._req(url, params)
        if not data or "data" not in data or not data["data"]:
            return pd.DataFrame()
        klines = data["data"].get("klines", [])
        if not klines:
            return pd.DataFrame()

        rows = []
        for line in klines:
            p = line.split(",")
            if len(p) >= 11:
                rows.append({
                    "date": p[0], "open": float(p[1]),
                    "close": float(p[2]), "high": float(p[3]),
                    "low": float(p[4]), "volume": int(p[5]),
                    "amount": float(p[6]), "amplitude": float(p[7]),
                    "change_pct": float(p[8]), "change_amt": float(p[9]),
                    "turnover": float(p[10]),
                })
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        df["code"] = code
        return df

    # ──────────── 2. 全市场股票列表 ────────────

    def get_all_stocks(self):
        """全A股列表+实时行情"""
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "cb": "jq", "pn": 1, "pz": 6000,
            "po": 1, "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": 2, "invt": 2, "fid": "f3",
            "fs": "m:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23",
            "fields": "f2,f3,f4,f5,f6,f7,f8,f12,f14,f15,f16,f17,f18,f20,f21",
        }
        data = self._req(url, params)
        if not data or "data" not in data or not data["data"]:
            return pd.DataFrame()
        df = pd.DataFrame(data["data"].get("diff", []))
        return df.rename(columns={
            "f12": "code", "f14": "name", "f2": "price",
            "f3": "pct", "f5": "vol", "f6": "amount",
            "f7": "amp", "f8": "turnover", "f15": "high",
            "f16": "low", "f17": "open", "f18": "pre_close",
            "f20": "total_mv", "f21": "circ_mv",
        })

    # ──────────── 3. 龙虎榜列表 ────────────

    def get_dragon_tiger(self, date=None, size=200):
        """龙虎榜列表"""
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")
        df = self._dc_query(
            report="RPT_DAILYBILLBOARD_DETAILSNEW",
            sort_col="TRADE_DATE,SECURITY_CODE",
            sort_type="-1,1",
            size=size,
            filt=f"(TRADE_DATE>='{date}')(TRADE_DATE<='{date}')",
        )
        if df.empty:
            return df
        cm = {
            "TRADE_DATE": "date", "SECURITY_CODE": "code",
            "SECURITY_NAME_ABBR": "name", "CLOSE_PRICE": "close",
            "CHANGE_RATE": "pct", "BILLBOARD_NET_AMT": "net_amt",
            "BILLBOARD_BUY_AMT": "buy_amt",
            "BILLBOARD_SELL_AMT": "sell_amt",
            "DEAL_NET_RATIO": "net_ratio",
            "TURNOVERRATE": "turnover",
            "FREE_MARKET_CAP": "free_mv",
            "EXPLANATION": "reason",
        }
        return df.rename(columns={k: v for k, v in cm.items() if k in df.columns})

    # ──────────── 4. 龙虎榜营业部明细 ────────────

    def get_dragon_detail(self, code, date):
        """龙虎榜买卖营业部明细"""
        results = []
        for direction, report in [("买入", "RPT_BILLBOARD_DAILYDETAILSBUY"),
                                  ("卖出", "RPT_BILLBOARD_DAILYDETAILSSELL")]:
            sort_c = "BUY" if direction == "买入" else "SELL"
            df = self._dc_query(
                report=report, sort_col=sort_c,
                size=50,
                filt=f"(TRADE_DATE='{date}')(SECURITY_CODE=\"{code}\")",
            )
            if df.empty:
                continue
            for _, r in df.iterrows():
                results.append({
                    "date": date, "code": code,
                    "direction": direction,
                    "seat": r.get("OPERATEDEPT_NAME", ""),
                    "buy": r.get("BUY", 0),
                    "sell": r.get("SELL", 0),
                    "net": r.get("NET", 0),
                })
        return pd.DataFrame(results)

    # ──────────── 5. 大宗交易 ────────────

    def get_block_trades(self, days=30, size=500):
        """大宗交易数据"""
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        df = self._dc_query(
            report="RPT_BLOCK_TRADEINFOR",
            sort_col="TRADE_DATE", sort_type="-1",
            size=size,
            filt=f"(TRADE_DATE>='{start}')(TRADE_DATE<='{end}')",
        )
        if df.empty:
            return df
        cm = {
            "TRADE_DATE": "date", "SECURITY_CODE": "code",
            "SECURITY_NAME_ABBR": "name",
            "CLOSE_PRICE": "close", "DEAL_PRICE": "deal_price",
            "PREMIUM_RATIO": "premium_pct",
            "DEAL_AMOUNT": "deal_amount",
            "DEAL_VOLUME": "deal_vol",
            "BUYER_NAME": "buyer", "SELLER_NAME": "seller",
            "CHANGE_RATE_1DAYS": "next1d",
            "CHANGE_RATE_5DAYS": "next5d",
            "CHANGE_RATE_10DAYS": "next10d",
            "CHANGE_RATE_20DAYS": "next20d",
        }
        return df.rename(columns={k: v for k, v in cm.items() if k in df.columns})

    # ──────────── 6. 股东增减持 ────────────

    def get_holder_changes(self, change_type="减持", size=200):
        """股东增减持"""
        report = "RPT_SHARE_REDUCE" if change_type == "减持" else "RPT_SHARE_INCREASE"
        df = self._dc_query(report=report, sort_col="END_DATE",
                            sort_type="-1", size=size)
        if df.empty:
            return df
        cm = {
            "SECURITY_CODE": "code", "SECURITY_NAME_ABBR": "name",
            "END_DATE": "end_date", "START_DATE": "start_date",
            "CHANGE_SHARES_RATIO": "change_ratio",
            "HOLDER_NAME": "holder",
            "HOLDER_TYPE": "holder_type",
            "AVG_PRICE": "avg_price",
            "CHANGE_AMOUNT": "change_amount",
        }
        return df.rename(columns={k: v for k, v in cm.items() if k in df.columns})

    # ──────────── 7. 融资融券 ────────────

    def get_margin_detail(self, code=None, size=200):
        """个股融资融券明细"""
        filt = f'(SECURITY_CODE="{code}")' if code else ""
        df = self._dc_query(
            report="RPTA_WEB_RZRQ_GGMX",
            sort_col="TRADE_DATE", sort_type="-1",
            size=size, filt=filt,
        )
        if df.empty:
            return df
        cm = {
            "TRADE_DATE": "date", "SECURITY_CODE": "code",
            "SECURITY_NAME_ABBR": "name",
            "RZYE": "rz_bal", "RZMRE": "rz_buy",
            "RZCHE": "rz_repay",
            "RQYE": "rq_bal", "RQYL": "rq_vol",
            "RQMCL": "rq_sell", "RQCHL": "rq_return",
            "RZRQYE": "total_bal",
        }
        return df.rename(columns={k: v for k, v in cm.items() if k in df.columns})

    def get_margin_ranking(self, sort_by="RQMCL", size=100):
        """融资融券排名"""
        df = self._dc_query(
            report="RPTA_WEB_RZRQ_GGMX",
            sort_col=sort_by, sort_type="-1", size=size,
        )
        if df.empty:
            return df
        cm = {
            "TRADE_DATE": "date", "SECURITY_CODE": "code",
            "SECURITY_NAME_ABBR": "name",
            "RZYE": "rz_bal", "RZMRE": "rz_buy",
            "RQYE": "rq_bal", "RQYL": "rq_vol",
            "RQMCL": "rq_sell", "RZRQYE": "total_bal",
        }
        return df.rename(columns={k: v for k, v in cm.items() if k in df.columns})

    # ──────────── 8. 板块资金流 ────────────

    def get_sector_flow(self, stype="concept", size=100):
        """板块资金流排名"""
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        fs = {"concept": "m:90+t:3+f:!50", "industry": "m:90+t:2+f:!50"}
        params = {
            "cb": "jq", "pn": 1, "pz": size,
            "po": 1, "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": 2, "invt": 2, "fid": "f62",
            "fs": fs.get(stype, fs["concept"]),
            "fields": "f12,f14,f2,f3,f62,f184,f66,f72,f78,f84,f124",
        }
        data = self._req(url, params)
        if not data or "data" not in data or not data["data"]:
            return pd.DataFrame()
        df = pd.DataFrame(data["data"].get("diff", []))
        df = df.rename(columns={
            "f12": "board_code", "f14": "board_name",
            "f2": "price", "f3": "pct",
            "f62": "main_flow", "f184": "main_flow_pct",
            "f66": "super_flow", "f72": "big_flow",
            "f78": "mid_flow", "f84": "small_flow",
        })
        for c in ["main_flow", "super_flow", "big_flow", "mid_flow", "small_flow"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce") / 1e8
        return df

    # ──────────── 9. 公告 ────────────

    def get_announcements(self, code=None, days=60, size=100):
        """上市公司公告"""
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
        params = {
            "page_index": 1, "page_size": size,
            "ann_type": "A", "client_source": "web",
            "f_node": "0", "s_node": "0",
            "begin_time": start, "end_time": end,
        }
        if code:
            params["stock_list"] = code
        try:
            r = self.session.get(url, params=params, timeout=10)
            data = r.json()
            items = data.get("data", {}).get("list", [])
            rows = []
            for it in items:
                codes = it.get("codes", [{}])
                rows.append({
                    "ann_date": it.get("notice_date", ""),
                    "code": codes[0].get("stock_code", "") if codes else "",
                    "name": codes[0].get("short_name", "") if codes else "",
                    "title": it.get("title", ""),
                })
            return pd.DataFrame(rows)
        except Exception:
            return pd.DataFrame()

    # ──────────── 10. 涨停池 ────────────

    def get_limit_up(self, date=None):
        """涨停股池"""
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")
        df = self._dc_query(
            report="RPT_LIMITUP_BASICINFOS",
            sort_col="FIRST_LIMIT_TIME", sort_type="1",
            size=300,
            filt=f"(TRADE_DATE='{date}')",
        )
        if df.empty:
            return df
        cm = {
            "SECURITY_CODE": "code", "SECURITY_NAME_ABBR": "name",
            "CLOSE_PRICE": "close", "CHANGE_RATE": "pct",
            "FIRST_LIMIT_TIME": "first_time",
            "LAST_LIMIT_TIME": "last_time",
            "LIMIT_UP_DAYS": "limit_days",
            "OPEN_TIMES": "open_times",
            "TURNOVERRATE": "turnover",
            "INDUSTRY": "industry",
        }
        return df.rename(columns={k: v for k, v in cm.items() if k in df.columns})


# 全局单例
api = EastMoneyAPI()
