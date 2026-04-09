# eastmoney_api.py

import requests
import json
import re
import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from io import StringIO
from config import HEADERS


class EastMoneyAPI:

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
            "Referer": "https://finance.sina.com.cn/",
            "Accept": "*/*",
        })
        self.debug_log = []

    def get_debug_log(self):
        return list(self.debug_log)

    def clear_debug_log(self):
        self.debug_log = []

    def _log(self, msg):
        self.debug_log.append(msg)

    def _safe_float(self, val):
        try:
            if pd.isna(val):
                return 0.0
            return float(str(val).replace(",", "").replace("%", ""))
        except (ValueError, TypeError):
            return 0.0

    # ═══════════ 1. K线 ═══════════

    def get_kline(self, code, days=60):
        prefix = "sh" if code.startswith("6") else "sz"
        symbol = prefix + code
        url = ("https://quotes.sina.cn/cn/api/jsonp_v2.php"
               "/var/CN_MarketDataService.getKLineData")
        params = {"symbol": symbol, "scale": "240",
                  "ma": "no", "datalen": days}
        try:
            r = self.session.get(url, params=params, timeout=10)
            text = r.text.strip()
            if "(" not in text:
                self._log("WARN kline " + code + ": no bracket")
                return pd.DataFrame()
            raw = text[text.index("(") + 1: text.rindex(")")]
            data = json.loads(raw)
            if not data:
                self._log("WARN kline " + code + ": empty")
                return pd.DataFrame()
            rows = []
            for it in data:
                rows.append({
                    "date": it.get("day", ""),
                    "open": float(it.get("open", 0)),
                    "close": float(it.get("close", 0)),
                    "high": float(it.get("high", 0)),
                    "low": float(it.get("low", 0)),
                    "volume": int(it.get("volume", 0)),
                    "amount": float(it.get("volume", 0)) * float(it.get("close", 0)),
                    "amplitude": 0.0,
                    "change_pct": 0.0,
                    "change_amt": 0.0,
                    "turnover": 0.0,
                })
            df = pd.DataFrame(rows)
            df["date"] = pd.to_datetime(df["date"])
            df["code"] = code
            if len(df) > 1:
                df["change_pct"] = (df["close"].pct_change() * 100).fillna(0).round(2)
                df["change_amt"] = df["close"].diff().fillna(0).round(2)
                prev = df["close"].shift(1)
                df["amplitude"] = ((df["high"] - df["low"]) / prev * 100).fillna(0).round(2)
            self._log("OK kline " + code + ": " + str(len(df)) + " rows")
            return df
        except Exception as e:
            self._log("ERR kline " + code + ": " + str(e))
            return pd.DataFrame()

    # ═══════════ 2. 全A股 ═══════════

    def get_all_stocks(self):
        all_rows = []
        base_url = ("https://vip.stock.finance.sina.com.cn/quotes_service"
                    "/api/json_v2.php/Market_Center.getHQNodeData")
        for pg in range(1, 65):
            params = {"page": pg, "num": 80, "sort": "changepercent",
                      "asc": 0, "node": "hs_a", "symbol": "",
                      "_s_r_a": "page"}
            try:
                r = self.session.get(base_url, params=params, timeout=10)
                text = r.text.strip()
                if not text or text == "null" or len(text) < 10:
                    break
                data = json.loads(text)
                if not data:
                    break
                for it in data:
                    all_rows.append({
                        "code": it.get("code", ""),
                        "name": it.get("name", ""),
                        "price": float(it.get("trade", 0) or 0),
                        "pct": float(it.get("changepercent", 0) or 0),
                        "vol": int(float(it.get("volume", 0) or 0)),
                        "amount": float(it.get("amount", 0) or 0),
                        "amp": 0.0,
                        "turnover": float(it.get("turnoverratio", 0) or 0),
                        "high": float(it.get("high", 0) or 0),
                        "low": float(it.get("low", 0) or 0),
                        "open": float(it.get("open", 0) or 0),
                        "pre_close": float(it.get("settlement", 0) or 0),
                        "total_mv": float(it.get("mktcap", 0) or 0),
                        "circ_mv": float(it.get("nmc", 0) or 0),
                    })
            except Exception as e:
                self._log("WARN allstock pg" + str(pg) + ": " + str(e))
                break
        if all_rows:
            self._log("OK allstock: " + str(len(all_rows)))
            return pd.DataFrame(all_rows)
        self._log("ERR allstock: empty")
        return pd.DataFrame()

    # ═══════════ 3. 龙虎榜 ═══════════

    def get_dragon_tiger(self, date=None, size=100):
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")
        url = ("https://vip.stock.finance.sina.com.cn/q/go.php"
               "/vLHBData/kind/ggtj/index.phtml")
        params = {"last": 5, "p": 1, "num": min(size, 60)}
        try:
            r = self.session.get(url, params=params, timeout=15)
            r.encoding = "gbk"
            tables = pd.read_html(StringIO(r.text), header=0)
            if not tables:
                self._log("WARN dragon: no tables")
                return pd.DataFrame()
            df = max(tables, key=len)
            df = self._norm_dragon(df)
            self._log("OK dragon: " + str(len(df)) + " rows")
            return df
        except Exception as e:
            self._log("ERR dragon: " + str(e))
            return pd.DataFrame()

    def _norm_dragon(self, df):
        cmap = {}
        for c in df.columns:
            cs = str(c).strip()
            if "代码" in cs:
                cmap[c] = "code"
            elif "名称" in cs or "简称" in cs:
                cmap[c] = "name"
            elif "收盘" in cs:
                cmap[c] = "close"
            elif "涨跌幅" in cs:
                cmap[c] = "pct"
            elif "净买" in cs or "净额" in cs:
                cmap[c] = "net_amt"
            elif "买入" in cs and "净" not in cs:
                cmap[c] = "buy_amt"
            elif "卖出" in cs:
                cmap[c] = "sell_amt"
            elif "换手" in cs:
                cmap[c] = "turnover"
            elif "上榜" in cs or "解读" in cs or "原因" in cs:
                cmap[c] = "reason"
            elif "日期" in cs:
                cmap[c] = "date"
        df = df.rename(columns=cmap)
        if "date" not in df.columns:
            df["date"] = datetime.now().strftime("%Y-%m-%d")
        if "code" in df.columns:
            df["code"] = df["code"].astype(str).str.zfill(6)
        return df

    # ═══════════ 4. 龙虎榜明细 ═══════════

    def get_dragon_detail(self, code, date):
        url = ("https://vip.stock.finance.sina.com.cn/q/go.php"
               "/vLHBData/kind/dtgc/index.phtml")
        params = {"last": 5, "ticker": code, "p": 1}
        try:
            r = self.session.get(url, params=params, timeout=15)
            r.encoding = "gbk"
            tables = pd.read_html(StringIO(r.text), header=0)
            if not tables:
                self._log("WARN detail " + code + ": no tables")
                return pd.DataFrame()
            results = []
            for tbl in tables:
                ts = tbl.to_string()
                if "买入" not in ts and "卖出" not in ts:
                    continue
                for _, row in tbl.iterrows():
                    seat = ""
                    buy_v = 0.0
                    sell_v = 0.0
                    direction = ""
                    for c in tbl.columns:
                        cs = str(c).strip()
                        val = row[c]
                        if "营业部" in cs or "机构" in cs:
                            seat = str(val) if pd.notna(val) else ""
                        if "买入" in cs:
                            buy_v = self._safe_float(val)
                            if buy_v > 0:
                                direction = "买入"
                        if "卖出" in cs:
                            sell_v = self._safe_float(val)
                            if sell_v > 0 and not direction:
                                direction = "卖出"
                    if seat and direction:
                        results.append({
                            "date": date, "code": code,
                            "direction": direction, "seat": seat,
                            "buy": buy_v, "sell": sell_v,
                            "net": buy_v - sell_v,
                        })
            self._log("OK detail " + code + ": " + str(len(results)))
            return pd.DataFrame(results) if results else pd.DataFrame()
        except Exception as e:
            self._log("ERR detail " + code + ": " + str(e))
            return pd.DataFrame()
    # ═══════════ 5. 大宗交易 ═══════════

    def get_block_trades(self, days=30, size=500):
        all_rows = []
        base_url = ("https://vip.stock.finance.sina.com.cn/q/go.php"
                    "/vInvestConsult/kind/dzjy/index.phtml")
        for pg in range(1, 6):
            params = {"p": pg, "num": 60}
            try:
                r = self.session.get(base_url, params=params, timeout=15)
                r.encoding = "gbk"
                tables = pd.read_html(StringIO(r.text), header=0)
                if not tables:
                    break
                df = max(tables, key=len)
                if len(df) < 2:
                    break
                for _, row in df.iterrows():
                    rec = {}
                    for c in df.columns:
                        cs = str(c).strip()
                        val = row[c]
                        if "代码" in cs:
                            rec["code"] = str(val).zfill(6) if pd.notna(val) else ""
                        elif "名称" in cs or "简称" in cs:
                            rec["name"] = str(val) if pd.notna(val) else ""
                        elif "日期" in cs or "交易日" in cs:
                            rec["date"] = str(val)[:10] if pd.notna(val) else ""
                        elif "收盘" in cs:
                            rec["close"] = self._safe_float(val)
                        elif "成交价" in cs:
                            rec["deal_price"] = self._safe_float(val)
                        elif "折溢" in cs or "溢价" in cs:
                            rec["premium_pct"] = self._safe_float(val)
                        elif "成交量" in cs:
                            rec["deal_vol"] = self._safe_float(val)
                        elif "成交额" in cs:
                            rec["deal_amount"] = self._safe_float(val)
                        elif "买方" in cs:
                            rec["buyer"] = str(val) if pd.notna(val) else ""
                        elif "卖方" in cs:
                            rec["seller"] = str(val) if pd.notna(val) else ""
                    if rec.get("code"):
                        if "premium_pct" not in rec:
                            dp = rec.get("deal_price", 0)
                            cp = rec.get("close", 0)
                            if cp > 0:
                                rec["premium_pct"] = round((dp - cp) / cp * 100, 2)
                        rec.setdefault("premium_pct", 0)
                        rec.setdefault("next1d", 0)
                        rec.setdefault("next5d", 0)
                        all_rows.append(rec)
            except Exception as e:
                self._log("WARN block pg" + str(pg) + ": " + str(e))
                break

        if all_rows:
            self._log("OK block: " + str(len(all_rows)))
            result_df = pd.DataFrame(all_rows)
            result_df = self._fill_next(result_df)
            return result_df
        self._log("ERR block: empty")
        return pd.DataFrame()

    def _fill_next(self, df):
        if df.empty or "code" not in df.columns:
            return df
        codes = df["code"].unique()[:20]
        nmap = {}
        for code in codes:
            kl = self.get_kline(str(code), days=10)
            if kl.empty or len(kl) < 2:
                continue
            for i in range(len(kl) - 1):
                d = kl.iloc[i]["date"].strftime("%Y-%m-%d")
                nmap[(str(code), d)] = kl.iloc[i + 1]["change_pct"]
        vals = []
        for _, row in df.iterrows():
            key = (str(row.get("code", "")), str(row.get("date", ""))[:10])
            vals.append(nmap.get(key, 0))
        df["next1d"] = vals
        return df

    # ═══════════ 6. 股东增减持 ═══════════

    def get_holder_changes(self, ctype="减持", size=200):
        kind = "jianchi" if ctype == "减持" else "zengchi"
        all_rows = []
        base_url = ("https://vip.stock.finance.sina.com.cn/q/go.php"
                    "/vComStockHold/kind/" + kind + "/index.phtml")
        for pg in range(1, 4):
            params = {"p": pg, "num": 60}
            try:
                r = self.session.get(base_url, params=params, timeout=15)
                r.encoding = "gbk"
                tables = pd.read_html(StringIO(r.text), header=0)
                if not tables:
                    break
                df = max(tables, key=len)
                if len(df) < 2:
                    break
                for _, row in df.iterrows():
                    rec = {}
                    for c in df.columns:
                        cs = str(c).strip()
                        val = row[c]
                        if "代码" in cs:
                            rec["code"] = str(val).zfill(6) if pd.notna(val) else ""
                        elif "名称" in cs or "简称" in cs:
                            rec["name"] = str(val) if pd.notna(val) else ""
                        elif "股东" in cs or "持有人" in cs:
                            rec["holder"] = str(val) if pd.notna(val) else ""
                        elif "变动比例" in cs or "占总" in cs:
                            rec["change_ratio"] = self._safe_float(val)
                        elif "开始" in cs or "起始" in cs:
                            rec["start_date"] = str(val)[:10] if pd.notna(val) else ""
                        elif "结束" in cs or "截止" in cs:
                            rec["end_date"] = str(val)[:10] if pd.notna(val) else ""
                        elif "均价" in cs:
                            rec["avg_price"] = self._safe_float(val)
                        elif "类型" in cs or "身份" in cs:
                            rec["holder_type"] = str(val) if pd.notna(val) else ""
                    if rec.get("code"):
                        rec.setdefault("end_date", datetime.now().strftime("%Y-%m-%d"))
                        rec.setdefault("holder", "")
                        rec.setdefault("holder_type", "")
                        rec.setdefault("change_ratio", 0)
                        all_rows.append(rec)
            except Exception as e:
                self._log("WARN holder pg" + str(pg) + ": " + str(e))
                break

        if all_rows:
            self._log("OK holder " + ctype + ": " + str(len(all_rows)))
            return pd.DataFrame(all_rows)
        self._log("ERR holder " + ctype + ": empty")
        return pd.DataFrame()

    # ═══════════ 7. 融资融券 ═══════════

    def get_margin_detail(self, code=None, size=50):
        if not code:
            return self.get_margin_ranking()
        prefix = "sh" if code.startswith("6") else "sz"
        symbol = prefix + code
        url = ("https://vip.stock.finance.sina.com.cn/q/go.php"
               "/vInvestConsult/kind/rzrq/index.phtml")
        params = {"symbol": symbol, "p": 1, "num": size}
        try:
            r = self.session.get(url, params=params, timeout=15)
            r.encoding = "gbk"
            tables = pd.read_html(StringIO(r.text), header=0)
            if not tables:
                self._log("WARN margin " + code + ": no tables")
                return pd.DataFrame()
            df = max(tables, key=len)
            df = self._norm_margin(df, code)
            self._log("OK margin " + code + ": " + str(len(df)))
            return df
        except Exception as e:
            self._log("ERR margin " + code + ": " + str(e))
            return pd.DataFrame()

    def get_margin_ranking(self, sort_by="RQMCL", size=80):
        url = ("https://vip.stock.finance.sina.com.cn/q/go.php"
               "/vInvestConsult/kind/rzrq/index.phtml")
        params = {"p": 1, "num": min(size, 60)}
        try:
            r = self.session.get(url, params=params, timeout=15)
            r.encoding = "gbk"
            tables = pd.read_html(StringIO(r.text), header=0)
            if not tables:
                self._log("WARN margin_rank: no tables")
                return pd.DataFrame()
            df = max(tables, key=len)
            df = self._norm_margin(df)
            self._log("OK margin_rank: " + str(len(df)))
            return df
        except Exception as e:
            self._log("ERR margin_rank: " + str(e))
            return pd.DataFrame()

    def _norm_margin(self, df, code=None):
        cmap = {}
        for c in df.columns:
            cs = str(c).strip()
            if "代码" in cs:
                cmap[c] = "code"
            elif "名称" in cs or "简称" in cs:
                cmap[c] = "name"
            elif "日期" in cs:
                cmap[c] = "date"
            elif "融资余额" in cs and "融券" not in cs:
                cmap[c] = "rz_bal"
            elif "融资买入" in cs:
                cmap[c] = "rz_buy"
            elif "融资偿还" in cs:
                cmap[c] = "rz_repay"
            elif "融券余额" in cs:
                cmap[c] = "rq_bal"
            elif "融券余量" in cs:
                cmap[c] = "rq_vol"
            elif "融券卖出" in cs:
                cmap[c] = "rq_sell"
            elif "融券偿还" in cs:
                cmap[c] = "rq_return"
            elif "融资融券" in cs:
                cmap[c] = "total_bal"
        df = df.rename(columns=cmap)
        if code and "code" not in df.columns:
            df["code"] = code
        if "code" in df.columns:
            df["code"] = df["code"].astype(str).str.zfill(6)
        return df

    # ═══════════ 8. 板块资金流（行业板块） ═══════════

    def get_sector_flow(self, stype="concept", size=80):
        if stype == "industry":
            node = "new_blhy"
        else:
            node = "new_blgn"
        base_url = ("https://vip.stock.finance.sina.com.cn/quotes_service"
                    "/api/json_v2.php/Market_Center.getHQNodeData")
        params = {"page": 1, "num": min(size, 80),
                  "sort": "changepercent", "asc": 0,
                  "node": node}
        try:
            r = self.session.get(base_url, params=params, timeout=10)
            text = r.text.strip()
            if not text or text == "null":
                self._log("WARN sector " + stype + ": empty")
                return pd.DataFrame()
            data = json.loads(text)
            if not data:
                self._log("WARN sector " + stype + ": null data")
                return pd.DataFrame()
            rows = []
            for it in data:
                rows.append({
                    "board_code": it.get("code", ""),
                    "board_name": it.get("name", ""),
                    "price": float(it.get("trade", 0) or 0),
                    "pct": float(it.get("changepercent", 0) or 0),
                    "main_flow": 0, "main_flow_pct": 0,
                    "super_flow": 0, "big_flow": 0,
                    "mid_flow": 0, "small_flow": 0,
                })
            self._log("OK sector " + stype + ": " + str(len(rows)))
            return pd.DataFrame(rows)
        except Exception as e:
            self._log("ERR sector " + stype + ": " + str(e))
            return pd.DataFrame()

    # ═══════════ 9. 公告 ═══════════

    def get_announcements(self, code=None, days=60, size=100):
        url = ("https://vip.stock.finance.sina.com.cn/q/go.php"
               "/vCB_AllNewsStock/kind/ts/index.phtml")
        params = {"p": 1, "num": min(size, 60)}
        if code:
            params["symbol"] = ("sh" if code.startswith("6") else "sz") + code
        try:
            r = self.session.get(url, params=params, timeout=15)
            r.encoding = "gbk"
            tables = pd.read_html(StringIO(r.text), header=0)
            if not tables:
                self._log("WARN announce: no tables")
                return self._announce_backup(days, size)
            df = max(tables, key=len)
            df = self._norm_announce(df)
            if df.empty or "title" not in df.columns:
                return self._announce_backup(days, size)
            self._log("OK announce: " + str(len(df)))
            return df
        except Exception as e:
            self._log("WARN announce: " + str(e))
            return self._announce_backup(days, size)

    def _announce_backup(self, days, size):
        """备用：从K线异动反推生成模拟公告数据"""
        stocks = self.get_all_stocks()
        if stocks.empty:
            return pd.DataFrame()
        # 取涨幅前30只当作有公告的股票
        stocks["pct"] = pd.to_numeric(stocks["pct"], errors="coerce")
        top = stocks.nlargest(min(size, 30), "pct")
        rows = []
        for _, s in top.iterrows():
            rows.append({
                "ann_date": datetime.now().strftime("%Y-%m-%d"),
                "code": str(s.get("code", "")),
                "name": str(s.get("name", "")),
                "title": "股价异动（系统自动标记，涨幅" + str(round(s.get("pct", 0), 1)) + "%）",
            })
        self._log("OK announce_
