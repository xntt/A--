# eastmoney_api.py
# 全部使用新浪财经接口，不依赖东方财富

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
    """实际使用新浪财经接口，保持方法名不变"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/131.0.0.0 Safari/537.36",
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

    # ═══════════════════════════════════════
    #  1. K线 — 新浪
    # ═══════════════════════════════════════

    def get_kline(self, code, days=60):
        prefix = "sh" if code.startswith("6") else "sz"
        symbol = f"{prefix}{code}"
        url = "https://quotes.sina.cn/cn/api/jsonp_v2.php/var/CN_MarketDataService.getKLineData"
        params = {"symbol": symbol, "scale": "240", "ma": "no", "datalen": days}
        try:
            r = self.session.get(url, params=params, timeout=10)
            text = r.text.strip()
            if "(" not in text:
                self._log(f"WARN kline {code}: no bracket")
                return pd.DataFrame()
            raw = text[text.index("(") + 1: text.rindex(")")]
            data = json.loads(raw)
            if not data:
                self._log(f"WARN kline {code}: empty")
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
                    "amplitude": 0, "change_pct": 0,
                    "change_amt": 0, "turnover": 0,
                })
            df = pd.DataFrame(rows)
            df["date"] = pd.to_datetime(df["date"])
            df["code"] = code
            if len(df) > 1:
                df["change_pct"] = (df["close"].pct_change() * 100).fillna(0).round(2)
                df["change_amt"] = df["close"].diff().fillna(0).round(2)
                df["amplitude"] = ((df["high"] - df["low"]) / df["close"].shift(1) * 100).fillna(0).round(2)
            self._log(f"OK kline {code}: {len(df)} rows")
            return df
        except Exception as e:
            self._log(f"ERR kline {code}: {e}")
            return pd.DataFrame()

    # ═══════════════════════════════════════
    #  2. 全A股实时行情 — 新浪
    # ═══════════════════════════════════════

    def get_all_stocks(self):
        all_rows = []
        for pg in range(1, 65):
            url = ("https://vip.stock.finance.sina.com.cn/quotes_service"
                   "/api/json_v2.php/Market_Center.getHQNodeData")
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
                for it in data:
                    all_rows.append({
                        "code": it.get("code", ""),
                        "name": it.get("name", ""),
                        "price": float(it.get("trade", 0) or 0),
                        "pct": float(it.get("changepercent", 0) or 0),
                        "vol": int(float(it.get("volume", 0) or 0)),
                        "amount": float(it.get("amount", 0) or 0),
                        "amp": 0,
                        "turnover": float(it.get("turnoverratio", 0) or 0),
                        "high": float(it.get("high", 0) or 0),
                        "low": float(it.get("low", 0) or 0),
                        "open": float(it.get("open", 0) or 0),
                        "pre_close": float(it.get("settlement", 0) or 0),
                        "total_mv": float(it.get("mktcap", 0) or 0),
                        "circ_mv": float(it.get("nmc", 0) or 0),
                    })
            except Exception as e:
                self._log(f"WARN allstock pg{pg}: {e}")
                break
        if all_rows:
            self._log(f"OK allstock: {len(all_rows)}")
            return pd.DataFrame(all_rows)
        self._log("ERR allstock: empty")
        return pd.DataFrame()

    # ═══════════════════════════════════════
    #  3. 龙虎榜 — 新浪HTML解析
    # ═══════════════════════════════════════

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
            # 找最大的表
            df = max(tables, key=len)
            self._log(f"OK dragon: {len(df)} rows, cols={list(df.columns)}")
            # 标准化列名
            df = self._normalize_dragon_cols(df)
            return df
        except Exception as e:
            self._log(f"ERR dragon: {e}")
            return pd.DataFrame()

    def _normalize_dragon_cols(self, df):
        col_map = {}
        for c in df.columns:
            cl = str(c).strip()
            if "代码" in cl or "证券代码" in cl:
                col_map[c] = "code"
            elif "名称" in cl or "证券简称" in cl:
                col_map[c] = "name"
            elif "收盘" in cl or "收盘价" in cl:
                col_map[c] = "close"
            elif "涨跌幅" in cl:
                col_map[c] = "pct"
            elif "龙虎榜净买" in cl or "净买入" in cl or "净额" in cl:
                col_map[c] = "net_amt"
            elif "买入" in cl and "净" not in cl:
                col_map[c] = "buy_amt"
            elif "卖出" in cl:
                col_map[c] = "sell_amt"
            elif "换手" in cl:
                col_map[c] = "turnover"
            elif "上榜原因" in cl or "解读" in cl:
                col_map[c] = "reason"
            elif "日期" in cl or "交易日" in cl:
                col_map[c] = "date"
        df = df.rename(columns=col_map)
        if "date" not in df.columns:
            df["date"] = datetime.now().strftime("%Y-%m-%d")
        if "code" in df.columns:
            df["code"] = df["code"].astype(str).str.zfill(6)
        return df

    # ═══════════════════════════════════════
    #  4. 龙虎榜营业部明细 — 新浪
    # ═══════════════════════════════════════

    def get_dragon_detail(self, code, date):
        url = ("https://vip.stock.finance.sina.com.cn/q/go.php"
               "/vLHBData/kind/dtgc/index.phtml")
        params = {"last": 5, "ticker": code, "p": 1}
        try:
            r = self.session.get(url, params=params, timeout=15)
            r.encoding = "gbk"
            tables = pd.read_html(StringIO(r.text), header=0)
            if not tables:
                self._log(f"WARN dragon_detail {code}: no tables")
                return pd.DataFrame()

            results = []
            for tbl in tables:
                tbl_str = tbl.to_string()
                if "买入" in tbl_str or "卖出" in tbl_str:
                    for _, row in tbl.iterrows():
                        seat = ""
                        buy_v = 0
                        sell_v = 0
                        direction = ""
                        for c in tbl.columns:
                            cs = str(c).strip()
                            val = row[c]
                            if "营业部" in cs or "机构" in cs:
                                seat = str(val)
                            if "买入" in cs:
                                try:
                                    buy_v = float(val)
                                except (ValueError, TypeError):
                                    buy_v = 0
                                if buy_v > 0:
                                    direction = "买入"
                            if "卖出" in cs:
                                try:
                                    sell_v = float(val)
                                except (ValueError, TypeError):
                                    sell_v = 0
                                if sell_v > 0 and not direction:
                                    direction = "卖出"
                        if seat and direction:
                            results.append({
                                "date": date, "code": code,
                                "direction": direction,
                                "seat": seat,
                                "buy": buy_v, "sell": sell_v,
                                "net": buy_v - sell_v,
                            })
            self._log(f"OK dragon_detail {code}: {len(results)}")
            return pd.DataFrame(results) if results else pd.DataFrame()
        except Exception as e:
            self._log(f"ERR dragon_detail {code}: {e}")
            return pd.DataFrame()

    # ═══════════════════════════════════════
    #  5. 大宗交易 — 新浪
    # ═══════════════════════════════════════

    def get_block_trades(self, days=30, size=500):
        all_rows = []
        for pg in range(1, 6):
            url = ("https://vip.stock.finance.sina.com.cn/q/go.php"
                   "/vInvestConsult/kind/dzjy/index.phtml")
            params = {"p": pg, "num": 60}
            try:
                r = self.session.get(url, params=params, timeout=15)
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
                        elif "买方" in cs or "买入" in cs:
                            rec["buyer"] = str(val) if pd.notna(val) else ""
                        elif "卖方" in cs or "卖出" in cs:
                            rec["seller"] = str(val) if pd.notna(val) else ""
                    if rec.get("code"):
                        # 计算折溢价（如果没有直接给出）
                        if "premium_pct" not in rec and rec.get("deal_price") and rec.get("close"):
                            dp = rec["deal_price"]
                            cp = rec["close"]
                            if cp > 0:
                                rec["premium_pct"] = round((dp - cp) / cp * 100, 2)
                        rec.setdefault("premium_pct", 0)
                        rec.setdefault("next1d", 0)
                        rec.setdefault("next5d", 0)
                        all_rows.append(rec)
            except Exception as e:
                self._log(f"WARN block pg{pg}: {e}")
                break

        if all_rows:
            self._log(f"OK block: {len(all_rows)}")
            result_df = pd.DataFrame(all_rows)
            # 补充次日涨幅
            result_df = self._fill_next_day_pct(result_df)
            return result_df
        self._log("ERR block: empty")
        return pd.DataFrame()

    def _fill_next_day_pct(self, df):
        """为大宗交易补充次日涨幅"""
        if df.empty or "code" not in df.columns:
            return df
        unique_codes = df["code"].unique()[:30]  # 限制数量
        next1d_map = {}
        for code in unique_codes:
            kl = self.get_kline(code, days=10)
            if kl.empty or len(kl) < 2:
                continue
            for i in range(len(kl) - 1):
                d = kl.iloc[i]["date"].strftime("%Y-%m-%d")
                next1d_map[(code, d)] = kl.iloc[i + 1]["change_pct"]

        n1_list = []
        for _, row in df.iterrows():
            key = (row.get("code", ""), str(row.get("date", ""))[:10])
            n1_list.append(next1d_map.get(key, 0))
        df["next1d"] = n1_list
        return df

    # ═══════════════════════════════════════
    #  6. 股东增减持 — 新浪
    # ═══════════════════════════════════════

    def get_holder_changes(self, ctype="减持", size=200):
        kind = "jianchi" if ctype == "减持" else "zengchi"
        all_rows = []
        for pg in range(1, 4):
            url = ("https://vip.stock.finance.sina.com.cn/q/go.php"
                   "/vComStockHold/kind/{}/index.phtml".format(kind))
            params = {"p": pg, "num": 60}
            try:
                r = self.session.get(url, params=params, timeout=15)
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
                self._log(f"WARN holder pg{pg}: {e}")
                break

        if all_rows:
            self._log(f"OK holder_{ctype}: {len(all_rows)}")
            return pd.DataFrame(all_rows)
        self._log(f"ERR holder
