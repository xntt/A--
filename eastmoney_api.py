import requests
import json
import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from config import HEADERS


class EastMoneyAPI:

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.debug_log = []

    # ════════════ 通用请求 ════════════

    def _req(self, url, params, timeout=15, label=""):
        for i in range(3):
            try:
                r = self.session.get(url, params=params, timeout=timeout)
                r.raise_for_status()
                t = r.text.strip()
                if "(" in t and t.endswith(")"):
                    start = t.index("(") + 1
                    t = t[start:-1]
                data = json.loads(t)
                self.debug_log.append(f"OK {label}: len={len(r.text)}")
                return data
            except json.JSONDecodeError:
                self.debug_log.append(f"WARN {label}: JSON解析失败 #{i+1} text={r.text[:200]}")
                if i == 2:
                    return {}
            except Exception as e:
                self.debug_log.append(f"ERR {label}: {e} #{i+1}")
                if i == 2:
                    return {}
                time.sleep(0.5)
        return {}

    def _secid(self, code):
        if code.startswith("6"):
            return f"1.{code}"
        return f"0.{code}"

    def get_debug_log(self):
        return list(self.debug_log)

    def clear_debug_log(self):
        self.debug_log = []

    # ════════════ datacenter通用 ════════════

    def _dc(self, report, sort_col="", sort_type="-1",
            page=1, size=200, filt="", label=""):
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            "reportName": report,
            "columns": "ALL",
            "source": "WEB",
            "client": "WEB",
            "sortColumns": sort_col,
            "sortTypes": sort_type,
            "pageNumber": page,
            "pageSize": size,
        }
        if filt:
            params["filter"] = filt
        data = self._req(url, params, label=label or report)
        if not data:
            return pd.DataFrame()
        result = data.get("result")
        if result and isinstance(result, dict):
            records = result.get("data")
            if records and isinstance(records, list):
                return pd.DataFrame(records)
        records = data.get("data")
        if records and isinstance(records, list):
            return pd.DataFrame(records)
        self.debug_log.append(f"WARN {label}: keys={list(data.keys())}")
        return pd.DataFrame()

    # ════════════ 1. K线（新浪优先） ════════════

    def get_kline(self, code, days=60):
        df = self._kline_sina(code, days)
        if not df.empty:
            return df
        return self._kline_em(code, days)

    def _kline_sina(self, code, days):
        prefix = "sh" if code.startswith("6") else "sz"
        symbol = f"{prefix}{code}"
        url = "https://quotes.sina.cn/cn/api/jsonp_v2.php/var/CN_MarketDataService.getKLineData"
        params = {
            "symbol": symbol,
            "scale": "240",
            "ma": "no",
            "datalen": days,
        }
        try:
            r = self.session.get(url, params=params, timeout=10)
            text = r.text.strip()
            if "(" not in text:
                self.debug_log.append(f"WARN K线_sina_{code}: 无括号")
                return pd.DataFrame()
            start = text.index("(") + 1
            end = text.rindex(")")
            raw = text[start:end]
            data = json.loads(raw)
            if not data:
                self.debug_log.append(f"WARN K线_sina_{code}: 空数据")
                return pd.DataFrame()
            rows = []
            for item in data:
                rows.append({
                    "date": item.get("day", ""),
                    "open": float(item.get("open", 0)),
                    "close": float(item.get("close", 0)),
                    "high": float(item.get("high", 0)),
                    "low": float(item.get("low", 0)),
                    "volume": int(item.get("volume", 0)),
                    "amount": float(item.get("volume", 0)) * float(item.get("close", 0)),
                    "amplitude": 0,
                    "change_pct": 0,
                    "change_amt": 0,
                    "turnover": 0,
                })
            df = pd.DataFrame(rows)
            df["date"] = pd.to_datetime(df["date"])
            df["code"] = code
            if len(df) > 1:
                df["change_pct"] = (df["close"].pct_change() * 100).fillna(0).round(2)
                df["change_amt"] = df["close"].diff().fillna(0).round(2)
            self.debug_log.append(f"OK K线_sina_{code}: {len(df)}行")
            return df
        except Exception as e:
            self.debug_log.append(f"ERR K线_sina_{code}: {e}")
            return pd.DataFrame()

    def _kline_em(self, code, days):
        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            "secid": self._secid(code),
            "ut": "fa5fd1943c7b386f172d6893dbfba10b",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": 101, "fqt": 1,
            "end": "20500101", "lmt": days,
        }
        data = self._req(url, params, label=f"K线_em_{code}")
        if not data:
            return pd.DataFrame()
        kdata = data.get("data")
        if not kdata:
            return pd.DataFrame()
        klines = kdata.get("klines", [])
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

    # ════════════ 2. 全A股（新浪优先） ════════════

    def get_all_stocks(self):
        df = self._all_stocks_sina()
        if not df.empty:
            return df
        return self._all_stocks_em()

    def _all_stocks_sina(self):
        all_rows = []
        for pg in range(1, 65):
            url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
            params = {
                "page": pg, "num": 80,
                "sort": "changepercent", "asc": 0,
                "node": "hs_a", "symbol": "",
                "_s_r_a": "page",
            }
            try:
                r = self.session.get(url, params=params, timeout=10)
                text = r.text.strip()
                if not text or text == "null" or len(text) < 10:
                    break
                data = json.loads(text)
                if not data:
                    break
                for item in data:
                    all_rows.append({
                        "code": item.get("code", ""),
                        "name": item.get("name", ""),
                        "price": float(item.get("trade", 0) or 0),
                        "pct": float(item.get("changepercent", 0) or 0),
                        "vol": int(float(item.get("volume", 0) or 0)),
                        "amount": float(item.get("amount", 0) or 0),
                        "amp": 0,
                        "turnover": float(item.get("turnoverratio", 0) or 0),
                        "high": float(item.get("high", 0) or 0),
                        "low": float(item.get("low", 0) or 0),
                        "open": float(item.get("open", 0) or 0),
                        "pre_close": float(item.get("settlement", 0) or 0),
                        "total_mv": float(item.get("mktcap", 0) or 0),
                        "circ_mv": float(item.get("nmc", 0) or 0),
                    })
            except Exception as e:
                self.debug_log.append(f"WARN allstock_sina pg{pg}: {e}")
                break
        if all_rows:
            self.debug_log.append(f"OK allstock_sina: {len(all_rows)}只")
            return pd.DataFrame(all_rows)
        self.debug_log.append("WARN allstock_sina: 全部失败")
        return pd.DataFrame()

    def _all_stocks_em(self):
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": 1, "pz": 5000, "po": 1, "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": 2, "invt": 2, "fid": "f3",
            "fs": "m:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23",
            "fields": "f2,f3,f4,f5,f6,f7,f8,f12,f14,f15,f16,f17,f18,f20,f21",
        }
        data = self._req(url, params, label="allstock_em")
        if not data or "data" not in data:
            return pd.DataFrame()
        diff = data.get("data", {}).get("diff")
        if not diff:
            return pd.DataFrame()
        df = pd.DataFrame(diff)
        return df.rename(columns={
            "f12": "code", "f14": "name", "f2": "price",
            "f3": "pct", "f5": "vol", "f6": "amount",
            "f7": "amp", "f8": "turnover", "f15": "high",
            "f16": "low", "f17": "open", "f18": "pre_close",
            "f20": "total_mv", "f21": "circ_mv",
        })

    # ════════════ 3. 龙虎榜 ════════════

    def get_dragon_tiger(self, date=None, size=100):
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")
        for d in [date, date.replace("-", "")]:
            df = self._dc(
                report="RPT_DAILYBILLBOARD_DETAILSNEW",
                sort_col="TRADE_DATE,SECURITY_CODE",
                sort_type="-1,1", size=size,
                filt=f"(TRADE_DATE>='{d}')(TRADE_DATE<='{d}')",
                label=f"龙虎榜_{d}",
            )
            if not df.empty:
                break
        if df.empty:
            df = self._dc(
                report="RPT_DAILYBILLBOARD_DETAILSNEW",
                sort_col="TRADE_DATE", sort_type="-1",
                size=size, label="龙虎榜_latest",
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

    # ════════════ 4. 龙虎榜营业部明细 ════════════

    def get_dragon_detail(self, code, date):
        results = []
        for direction, report, sort_c in [
            ("买入", "RPT_BILLBOARD_DAILYDETAILSBUY", "BUY"),
            ("卖出", "RPT_BILLBOARD_DAILYDETAILSSELL", "SELL"),
        ]:
            df = self._dc(
                report=report, sort_col=sort_c, size=50,
                filt=f"(TRADE_DATE='{date}')(SECURITY_CODE=\"{code}\")",
                label=f"龙虎明细_{code}_{direction}",
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

    # ════════════ 5. 大宗交易 ════════════

    def get_block_trades(self, days=30, size=500):
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        df = self._dc(
            report="RPT_BLOCK_TRADEINFOR",
            sort_col="TRADE_DATE", sort_type="-1", size=size,
            filt=f"(TRADE_DATE>='{start}')(TRADE_DATE<='{end}')",
            label="大宗交易",
        )
        if df.empty:
            df = self._dc(
                report="RPT_BLOCK_TRADEINFOR",
                sort_col="TRADE_DATE", sort_type="-1",
                size=size, label="大宗交易_nofilt",
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

    # ════════════ 6. 股东增减持 ════════════

    def get_holder_changes(self, ctype="减持", size=200):
        reports = (
            ["RPT_CUSTOM_HOLDER_REDUCE_GET", "RPT_SHARE_REDUCE"]
            if ctype == "减持"
            else ["RPT_CUSTOM_HOLDER_INCREASE_GET", "RPT_SHARE_INCREASE"]
        )
        df = pd.DataFrame()
        for rpt in reports:
            df = self._dc(report=rpt, sort_col="END_DATE",
                          sort_type="-1", size=size, label=f"holder_{ctype}_{rpt}")
            if not df.empty:
                break
        if df.empty:
            return df
        cm = {
            "SECURITY_CODE": "code", "SECURITY_NAME_ABBR": "name",
            "END_DATE": "end_date", "START_DATE": "start_date",
            "CHANGE_SHARES_RATIO": "change_ratio",
            "HOLDER_NAME": "holder", "HOLDER_TYPE": "holder_type",
            "AVG_PRICE": "avg_price", "CHANGE_AMOUNT": "change_amount",
        }
        return df.rename(columns={k: v for k, v in cm.items() if k in df.columns})

    # ════════════ 7. 融资融券 ════════════

    def get_margin_detail(self, code=None, size=50):
        filt = f'(SECURITY_CODE="{code}")' if code else ""
        df = self._dc(
            report="RPTA_WEB_RZRQ_GGMX",
            sort_col="TRADE_DATE", sort_type="-1",
            size=size, filt=filt,
            label=f"margin_{code or 'all'}",
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

    def get_margin_ranking(self, sort_by="RQMCL", size=80):
        df = self._dc(
            report="RPTA_WEB_RZRQ_GGMX",
            sort_col=sort_by, sort_type="-1",
            size=size, label=f"margin_rank_{sort_by}",
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

    # ════════════ 8. 板块资金流（三源） ════════════

    def get_sector_flow(self, stype="concept", size=80):
        if stype == "industry":
            df = self._sector_sina()
            if not df.empty:
                return df
        df = self._sector_em(stype, size)
        if not df.empty:
            return df
        return self._sector_dc(stype)

    def _sector_sina(self):
        url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
        params = {
            "page": 1, "num": 80,
            "sort": "changepercent", "asc": 0,
            "node": "new_blhy",
        }
        try:
            r = self.session.get(url, params=params, timeout=10)
            text = r.text.strip()
            if not text or text == "null":
                self.debug_log.append("WARN sector_sina: empty")
                return pd.DataFrame()
            data = json.loads(text)
            if not data:
                return pd.DataFrame()
            rows = []
            for item in data:
                rows.append({
                    "board_code": item.get("code", ""),
                    "board_name": item.get("name", ""),
                    "price": float(item.get("trade", 0) or 0),
                    "pct": float(item.get("changepercent", 0) or 0),
                    "main_flow": 0, "main_flow_pct": 0,
                    "super_flow": 0, "big_flow": 0,
                    "mid_flow": 0, "small_flow": 0,
                })
            self.debug_log.append(f"OK sector_sina: {len(rows)}")
            return pd.DataFrame(rows)
        except Exception as e:
            self.debug_log.append(f"ERR sector_sina: {e}")
            return pd.DataFrame()

    def _sector_em(self, stype, size):
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        fs = {"concept": "m:90+t:3+f:!50", "industry": "m:90+t:2+f:!50"}
        params = {
            "pn": 1, "pz": size, "po": 1, "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": 2, "invt": 2, "fid": "f62",
            "fs": fs.get(stype, fs["concept"]),
            "fields": "f12,f14,f2,f3,f62,f184,f66,f72,f78,f84,f124",
        }
        data = self._req(url, params, label=f"sector_em_{stype}")
        if not data or "data" not in data:
            return pd.DataFrame()
        diff = data.get("data", {}).get("diff")
        if not diff:
            return pd.DataFrame()
        df = pd.DataFrame(diff)
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

    def _sector_dc(self, stype):
        rpt = "RPT_SECTOR_FUNDFLOW_CONCEPT" if stype == "concept" else "RPT_SECTOR_FUNDFLOW_INDUSTRY"
        df = self._dc(report=rpt, sort_col="MAIN_NET_INFLOW",
                      sort_type="-1", size=80, label=f"sector_dc_{stype}")
        if df.empty:
            return df
        cm = {
            "BOARD_CODE": "board_code", "BOARD_NAME": "board_name",
            "CLOSE_PRICE": "price", "CHANGE_RATE": "pct",
            "MAIN_NET_INFLOW": "main_flow",
        }
        df = df.rename(columns={k: v for k, v in cm.items() if k in df.columns})
        if "main_flow" in df.columns:
            df["main_flow"] = pd.to_numeric(df["main_flow"], errors="coerce") / 1e8
        return df

    # ════════════ 9. 公告 ════════════

    def get_announcements(self, code=None, days=60, size=100):
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        # 方法1
        url1 = "https://np-anotice-stock.eastmoney.com/api/security/ann"
        params1 = {
            "page_index": 1, "page_size": size,
            "ann_type": "A", "client_source": "web",
            "f_node": "0", "s_node": "0",
            "begin_time": start, "end_time": end,
        }
        if code:
            params1["stock_list"] = code
        try:
            r = self.session.get(url1, params=params1, timeout=10)
            data = r.json()
            items = data.get("data", {}).get("list", [])
            if items:
                rows = []
                for it in items:
                    codes = it.get("codes") or [{}]
                    rows.append({
                        "ann_date": it.get("notice_date", ""),
                        "code": codes[0].get("stock_code", "") if codes else "",
                        "name": codes[0].get("short_name", "") if codes else "",
                        "title": it.get("title", ""),
                    })
                self.debug_log.append(f"OK announce_m1: {len(rows)}")
                return pd.DataFrame(rows)
        except Exception as e:
            self.debug_log.append(f"WARN announce_m1: {e}")

        # 方法2
        df = self._dc(report="RPT_ANNOUNCEMENT_LIST",
                       sort_col="NOTICE_DATE", sort_type="-1",
                       size=size, label="announce_m2")
        if not df.empty:
            cm = {
                "NOTICE_DATE": "ann_date", "SECURITY_CODE": "code",
                "SECURITY_NAME_ABBR": "name", "ANN_TITLE": "title",
            }
            return df.rename(columns={k: v for k, v in cm.items() if k in df.columns})

        # 方法3: 新浪公告
        return self._announcements_sina(days, size)

    def _announcements_sina(self, days, size):
        try:
            url = "https://vip.stock.finance.sina.com.cn/q/go.php/vReport_List/kind/search/index.phtml"
            params = {"t1": 0, "p": 1, "num": min(size, 40)}
            r = self.session.get(url, params=params, timeout=10)
            self.debug_log.append(f"WARN announce_sina: 仅返回原始HTML，暂不解析")
        except Exception:
            pass
        return pd.DataFrame()

    # ════════════ 10. 涨停池 ════════════

    def get_limit_up(self, date=None):
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")
        df = self._dc(
            report="RPT_LIMITUP_BASICINFOS",
            sort_col="FIRST_LIMIT_TIME", sort_type="1",
            size=300,
            filt=f"(TRADE_DATE='{date}')",
            label=f"limitup_{date}",
        )
        if df.empty:
            df = self._dc(
                report="RPT_LIMITUP_BASICINFOS",
                sort_col="FIRST_LIMIT_TIME", sort_type="1",
                size=300, label="limitup_latest",
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
            "TRADE_DATE": "trade_date",
        }
        return df.rename(columns={k: v for k, v in cm.items() if k in df.columns})

    # ════════════ 诊断 ════════════

    def run_diagnostics(self):
        self.clear_debug_log()
        results = {}

        # 新浪K线
        df = self._kline_sina("600519", 5)
        results["新浪K线(茅台)"] = f"OK {len(df)}行" if not df.empty else "FAIL"

        # 东方财富K线
        df = self._kline_em("600519", 5)
        results["东财K线(茅台)"] = f"OK {len(df)}行" if not df.empty else "FAIL"

        # 新浪全A
        try:
            url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
