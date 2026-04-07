# eastmoney_api.py

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

                # 处理JSONP
                if "(" in t and t.endswith(")"):
                    start = t.index("(") + 1
                    t = t[start:-1]

                data = json.loads(t)
                self.debug_log.append(f"✅ {label}: 成功 (长度={len(t)})")
                return data
            except json.JSONDecodeError as e:
                self.debug_log.append(f"⚠️ {label}: JSON解析失败 attempt={i+1}, text={r.text[:200]}")
                if i == 2:
                    return {}
            except Exception as e:
                self.debug_log.append(f"❌ {label}: 请求失败 attempt={i+1}, err={e}")
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

    # ════════════ datacenter 通用查询 ════════════

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

        # datacenter 返回结构: {"result": {"data": [...]}} 或 {"data": [...]}
        result = data.get("result")
        if result and isinstance(result, dict):
            records = result.get("data")
            if records and isinstance(records, list):
                return pd.DataFrame(records)

        # 备用结构
        records = data.get("data")
        if records and isinstance(records, list):
            return pd.DataFrame(records)

        self.debug_log.append(f"⚠️ {label}: 返回结构异常 keys={list(data.keys())}")
        return pd.DataFrame()

    # ════════════ 1. K线 ════════════

    def get_kline(self, code, days=60):
        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            "secid": self._secid(code),
            "ut": "fa5fd1943c7b386f172d6893dbfba10b",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": 101, "fqt": 1,
            "end": "20500101", "lmt": days,
        }
        data = self._req(url, params, label=f"K线_{code}")

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
                    "date": p[0],
                    "open": float(p[1]),
                    "close": float(p[2]),
                    "high": float(p[3]),
                    "low": float(p[4]),
                    "volume": int(p[5]),
                    "amount": float(p[6]),
                    "amplitude": float(p[7]),
                    "change_pct": float(p[8]),
                    "change_amt": float(p[9]),
                    "turnover": float(p[10]),
                })

        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        df["code"] = code
        return df

    # ════════════ 2. 全A股列表 ════════════

    def get_all_stocks(self):
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": 1, "pz": 5000,
            "po": 1, "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": 2, "invt": 2, "fid": "f3",
            "fs": "m:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23",
            "fields": "f2,f3,f4,f5,f6,f7,f8,f12,f14,f15,f16,f17,f18,f20,f21",
        }
        data = self._req(url, params, label="全A股列表")
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

        # 尝试多种日期格式
        for d in [date, date.replace("-", "")]:
            df = self._dc(
                report="RPT_DAILYBILLBOARD_DETAILSNEW",
                sort_col="TRADE_DATE,SECURITY_CODE",
                sort_type="-1,1",
                size=size,
                filt=f"(TRADE_DATE>='{d}')(TRADE_DATE<='{d}')",
                label=f"龙虎榜_{d}",
            )
            if not df.empty:
                break

        if df.empty:
            # 不带日期过滤，取最新
            df = self._dc(
                report="RPT_DAILYBILLBOARD_DETAILSNEW",
                sort_col="TRADE_DATE",
                sort_type="-1",
                size=size,
                label="龙虎榜_最新",
            )

        if df.empty:
            return df

        cm = {
            "TRADE_DATE": "date", "SECURITY_CODE": "code",
            "SECURITY_NAME_ABBR": "name", "CLOSE_PRICE": "close",
            "CHANGE_RATE": "pct",
            "BILLBOARD_NET_AMT": "net_amt",
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

        # 不带日期过滤再试
        if df.empty:
            df = self._dc(
                report="RPT_BLOCK_TRADEINFOR",
                sort_col="TRADE_DATE", sort_type="-1", size=size,
                label="大宗交易_无日期",
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
        report_map = {
            "减持": "RPT_CUSTOM_HOLDER_REDUCE_GET",
            "增持": "RPT_CUSTOM_HOLDER_INCREASE_GET",
        }
        report = report_map.get(ctype, "RPT_CUSTOM_HOLDER_REDUCE_GET")

        df = self._dc(
            report=report,
            sort_col="END_DATE", sort_type="-1", size=size,
            label=f"股东{ctype}",
        )

        # 备用报表名
        if df.empty:
            backup = "RPT_SHARE_REDUCE" if ctype == "减持" else "RPT_SHARE_INCREASE"
            df = self._dc(
                report=backup,
                sort_col="END_DATE", sort_type="-1", size=size,
                label=f"股东{ctype}_备用",
            )

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

    # ════════════ 7. 融资融券 ════════════

    def get_margin_detail(self, code=None, size=50):
        filt = f'(SECURITY_CODE="{code}")' if code else ""
        df = self._dc(
            report="RPTA_WEB_RZRQ_GGMX",
            sort_col="TRADE_DATE", sort_type="-1",
            size=size, filt=filt,
            label=f"融资融券_{code or '全市场'}",
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
            sort_col=sort_by, sort_type="-1", size=size,
            label=f"融资融券排名_{sort_by}",
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

    # ════════════ 8. 板块资金流 ════════════

    def get_sector_flow(self, stype="concept", size=80):
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        fs = {"concept": "m:90+t:3+f:!50", "industry": "m:90+t:2+f:!50"}
        params = {
            "pn": 1, "pz": size,
            "po": 1, "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": 2, "invt": 2, "fid": "f62",
            "fs": fs.get(stype, fs["concept"]),
            "fields": "f12,f14,f2,f3,f62,f184,f66,f72,f78,f84,f124",
        }
        data = self._req(url, params, label=f"板块资金流_{stype}")
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

    # ════════════ 9. 公告 ════════════

    def get_announcements(self, code=None, days=60, size=100):
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        # 方法1: np-anotice
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
                self.debug_log.append(f"✅ 公告_方法1: 获取{len(rows)}条")
                return pd.DataFrame(rows)
        except Exception as e:
            self.debug_log.append(f"⚠️ 公告_方法1失败: {e}")

        # 方法2: datacenter
        df = self._dc(
            report="RPT_ANNOUNCEMENT_LIST",
            sort_col="NOTICE_DATE", sort_type="-1",
            size=size, label="公告_方法2",
        )
        if not df.empty:
            cm = {
                "NOTICE_DATE": "ann_date",
                "SECURITY_CODE": "code",
                "SECURITY_NAME_ABBR": "name",
                "ANN_TITLE": "title",
            }
            return df.rename(columns={k: v for k, v in cm.items() if k in df.columns})

        self.debug_log.append("❌ 公告: 所有方法均失败")
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
            label=f"涨停池_{date}",
        )

        # 不带日期再试
        if df.empty:
            df = self._dc(
                report="RPT_LIMITUP_BASICINFOS",
                sort_col="FIRST_LIMIT_TIME", sort_type="1",
                size=300, label="涨停池_最新",
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

    # ════════════ 诊断测试 ════════════

    def run_diagnostics(self):
        """逐个测试所有API，返回结果字典"""
        self.clear_debug_log()
        results = {}

        # 测试1: K线
        df = self.get_kline("600519", days=5)
        results["K线(茅台)"] = f"✅ {len(df)}行" if not df.empty else "❌ 空"

        # 测试2: 全A股
        df = self.get_all_stocks()
        results["全A股列表"] = f"✅ {len(df)}只" if not df.empty else "❌ 空"

        # 测试3: 板块资金流
        df = self.get_sector_flow("concept", size=10)
        results["概念板块资金流"] = f"✅ {len(df)}板块" if not df.empty else "❌ 空"

        # 测试4: 龙虎榜
        df = self.get_dragon_tiger(size=10)
        results["龙虎榜"] = f"✅ {len(df)}条" if not df.empty else "❌ 空"

        # 测试5: 大宗交易
        df = self.get_block_trades(days=30, size=10)
        results["大宗交易"] = f"✅ {len(df)}条" if not df.empty else "❌ 空"

        # 测试6: 股东减持
        df = self.get_holder_changes("减持", size=10)
        results["股东减持"] = f"✅ {len(df)}条" if not df.empty else "❌ 空"

        # 测试7: 融资融券
        df = self.get_margin_ranking(size=10)
        results["融资融券"] = f"✅ {len(df)}条" if not df.empty else "❌ 空"

        # 测试8: 公告
        df = self.get_announcements(days=30, size=10)
        results["公告"] = f"✅ {len(df)}条" if not df.empty else "❌ 空"

        # 测试9: 涨停池
        df = self.get_limit_up()
        results["涨停池"] = f"✅ {len(df)}条" if not df.empty else "❌ 空"

        return results


api = EastMoneyAPI()
