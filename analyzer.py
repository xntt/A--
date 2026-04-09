# analyzer.py

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import streamlit as st
from eastmoney_api import api
from config import (
    VOLUME_ANOMALY_RATIO, POSITIVE_KEYWORDS,
    NEGATIVE_KEYWORDS, FAMOUS_SEATS,
    BLOCK_DISCOUNT_THRESHOLD, MARGIN_SPIKE_RATIO,
)


def safe_float(val):
    try:
        if pd.isna(val):
            return 0.0
        return float(str(val).replace(",", "").replace("%", ""))
    except (ValueError, TypeError):
        return 0.0


class PreAnnounceScanner:

    def scan(self, days_back=30, max_stocks=30):
        alerts = []
        stocks = api.get_all_stocks()
        if stocks.empty:
            return alerts, pd.DataFrame()

        stocks["pct"] = pd.to_numeric(stocks.get("pct", 0), errors="coerce").fillna(0)
        top = stocks.nlargest(max_stocks, "pct")
        prog = st.progress(0)
        n = len(top)

        for i, (_, row) in enumerate(top.iterrows()):
            prog.progress((i + 1) / n)
            code = str(row.get("code", ""))
            name = str(row.get("name", ""))
            if not code or len(code) != 6:
                continue
            kl = api.get_kline(code, days=30)
            if kl.empty or len(kl) < 10:
                continue
            recent = kl.iloc[-1]
            base = kl.iloc[:-1]
            avg_v = base["volume"].mean()
            if avg_v == 0:
                continue
            vol_r = recent["volume"] / avg_v
            if vol_r < 2.0:
                continue
            pct = recent["change_pct"]
            conf = round(min(vol_r / 10 + abs(pct) / 20, 1.0), 2)
            if conf >= 0.5:
                lvl = "critical"
            elif conf >= 0.3:
                lvl = "high"
            else:
                lvl = "mid"
            alerts.append({
                "code": code, "name": name,
                "vol_ratio": round(vol_r, 1),
                "change": round(pct, 1),
                "confidence": conf, "level": lvl,
            })
        prog.empty()
        alerts.sort(key=lambda x: x["vol_ratio"], reverse=True)
        return alerts, pd.DataFrame(alerts) if alerts else pd.DataFrame()


class DragonTigerTracker:

    def __init__(self):
        self.rmap = {}
        for alias, kw in FAMOUS_SEATS.items():
            self.rmap[kw] = alias

    def scan(self, days=5):
        alerts = []
        all_raw = []
        dt_list = api.get_dragon_tiger(size=60)
        if dt_list.empty:
            return alerts, pd.DataFrame(), pd.DataFrame()

        if "code" not in dt_list.columns:
            return alerts, pd.DataFrame(), dt_list

        prog = st.progress(0)
        items = dt_list.head(20)
        n = len(items)
        for i, (_, sr) in enumerate(items.iterrows()):
            prog.progress((i + 1) / n)
            code = str(sr.get("code", ""))
            name = str(sr.get("name", ""))
            pct = safe_float(sr.get("pct", 0))
            reason = str(sr.get("reason", ""))
            dt = str(sr.get("date", ""))[:10]
            if not dt:
                dt = datetime.now().strftime("%Y-%m-%d")

            detail = api.get_dragon_detail(code, dt)
            if detail.empty:
                all_raw.append({
                    "date": dt, "code": code, "name": name,
                    "pct": pct, "seat": "-", "alias": "",
                    "direction": "-", "buy": 0, "sell": 0,
                    "net": 0, "reason": reason, "is_famous": False,
                })
                continue

            for _, dr in detail.iterrows():
                seat = str(dr.get("seat", ""))
                alias = self._match(seat)
                direction = str(dr.get("direction", ""))
                buy_v = safe_float(dr.get("buy", 0))
                net_v = safe_float(dr.get("net", 0))
                all_raw.append({
                    "date": dt, "code": code, "name": name,
                    "pct": pct, "seat": seat, "alias": alias,
                    "direction": direction, "buy": buy_v,
                    "sell": safe_float(dr.get("sell", 0)),
                    "net": net_v, "reason": reason,
                    "is_famous": alias != "",
                })
                if alias and "买" in direction:
                    alerts.append({
                        "date": dt, "code": code, "name": name,
                        "pct": pct, "seat": seat, "alias": alias,
                        "buy_amt": buy_v, "net": net_v,
                        "reason": reason, "level": "high",
                    })
        prog.empty()
        raw_df = pd.DataFrame(all_raw) if all_raw else pd.DataFrame()
        return alerts, pd.DataFrame(), raw_df

    def _match(self, seat):
        for kw, alias in self.rmap.items():
            if kw in str(seat):
                return alias
        return ""


class BlockTradeMonitor:

    def scan(self, days=30):
        alerts = []
        df = api.get_block_trades(days=days, size=200)
        if df.empty:
            return alerts, pd.DataFrame(), pd.DataFrame()

        for c in ["premium_pct", "deal_amount", "next1d", "close", "deal_price"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

        if "premium_pct" not in df.columns or df["premium_pct"].abs().sum() == 0:
            if "deal_price" in df.columns and "close" in df.columns:
                m = df["close"] > 0
                df.loc[m, "premium_pct"] = ((df.loc[m, "deal_price"] - df.loc[m, "close"]) / df.loc[m, "close"] * 100).round(2)

        if "deal_amount" in df.columns:
            df["deal_wan"] = df["deal_amount"] / 1e4
        else:
            df["deal_wan"] = 0

        if "premium_pct" in df.columns:
            disc = df[df["premium_pct"] < -1].copy()
            for _, r in disc.iterrows():
                n1 = safe_float(r.get("next1d", 0))
                dp = safe_float(r.get("premium_pct", 0))
                if n1 > 1:
                    lvl = "high" if n1 > 5 else "mid"
                    alerts.append({
                        "date": str(r.get("date", ""))[:10],
                        "code": str(r.get("code", "")),
                        "name": str(r.get("name", "")),
                        "discount": round(dp, 2),
                        "deal_wan": round(safe_float(r.get("deal_wan", 0)), 0),
                        "buyer": str(r.get("buyer", ""))[:25],
                        "seller": str(r.get("seller", ""))[:25],
                        "next1d": round(n1, 2),
                        "next5d": round(safe_float(r.get("next5d", 0)), 2),
                        "level": lvl,
                    })
        alerts.sort(key=lambda x: x.get("next1d", 0), reverse=True)
        return alerts, df, pd.DataFrame()


class InsiderReductionDetector:

    def scan(self, max_stocks=30):
        alerts = []
        red_df = api.get_holder_changes("减持", size=100)
        if red_df.empty or "code" not in red_df.columns:
            return alerts, pd.DataFrame()

        red_df = red_df.drop_duplicates(subset=["code"], keep="first").head(max_stocks)
        prog = st.progress(0)
        n = len(red_df)
        for i, (_, r) in enumerate(red_df.iterrows()):
            prog.progress((i + 1) / n)
            code = str(r.get("code", ""))
            if not code or len(code) != 6:
                continue
            kl = api.get_kline(code, days=60)
            if kl.empty or len(kl) < 10:
                continue

            mid = len(kl) - 10
            post = kl.iloc[mid:]
            sp = post.iloc[0]["close"]
            if sp <= 0:
                continue
            min_p = post["low"].min()
            drop = (min_p - sp) / sp * 100
            if drop > -3:
                continue

            pre = kl.iloc[max(0, mid - 20):mid]
            pre_chg = 0
            if not pre.empty and pre.iloc[0]["open"] > 0:
                pre_chg = (pre.iloc[-1]["close"] - pre.iloc[0]["open"]) / pre.iloc[0]["open"] * 100

            if drop < -15:
                lvl = "critical"
            elif drop < -10:
                lvl = "high"
            else:
                lvl = "mid"
            alerts.append({
                "code": code, "name": str(r.get("name", "")),
                "holder": str(r.get("holder", ""))[:20],
                "pre_change": round(pre_chg, 1),
                "post_drop": round(drop, 1),
                "level": lvl,
                "is_precision": pre_chg > 3 and drop < -8,
            })
        prog.empty()
        alerts.sort(key=lambda x: x.get("post_drop", 0))
        return alerts, pd.DataFrame(alerts) if alerts else pd.DataFrame()


class MarginAnomalyDetector:

    def scan(self, top_n=20):
        short_alerts = []
        long_alerts = []
        df = api.get_margin_ranking(size=top_n)
        if df.empty or "code" not in df.columns:
            return short_alerts, long_alerts, df

        prog = st.progress(0)
        n = min(len(df), 15)
        for i, (_, r) in enumerate(df.head(n).iterrows()):
            prog.progress((i + 1) / n)
            code = str(r.get("code", ""))
            name = str(r.get("name", ""))
            if not code or len(code) != 6:
                continue
            hist = api.get_margin_detail(code=code, size=15)
            if hist.empty or len(hist) < 3:
                continue

            for col, signal, target in [
                ("rq_sell", "做空预警", short_alerts),
                ("rz_buy", "做多信号", long_alerts),
            ]:
                if col not in hist.columns:
                    continue
                hist[col] = pd.to_numeric(hist[col], errors="coerce").fillna(0)
                latest = hist.iloc[0][col]
                avg = hist.iloc[1:][col].mean()
                if avg > 0 and latest > 0:
                    ratio = latest / avg
                    if ratio >= MARGIN_SPIKE_RATIO:
                        lvl = "critical" if ratio >= 4 else "high" if ratio >= 2.5 else "mid"
                        target.append({
                            "code": code, "name": name,
                            "spike_ratio": round(ratio, 1),
                            "level": lvl, "signal": signal,
                        })
        prog.empty()
        short_alerts.sort(key=lambda x: x["spike_ratio"], reverse=True)
        long_alerts.sort(key=lambda x: x["spike_ratio"], reverse=True)
        return short_alerts, long_alerts, df


class SmartMoneyScanner:

    def __init__(self):
        self.s1 = PreAnnounceScanner()
        self.s2 = DragonTigerTracker()
        self.s3 = BlockTradeMonitor()
        self.s4 = InsiderReductionDetector()
        self.s5 = MarginAnomalyDetector()

    def run_all(self):
        r = {}
        st.info("1/5 成交量异动...")
        a1, d1 = self.s1.scan()
        r["m1"] = {"alerts": a1, "df": d1}
        st.info("2/5 龙虎榜...")
        a2, s2, r2 = self.s2.scan(days=3)
        r["m2"] = {"alerts": a2, "summary": s2, "raw": r2}
        st.info("3/5 大宗交易...")
        a3, d3, b3 = self.s3.scan(days=30)
        r["m3"] = {"alerts": a3, "df": d3, "buyers": b3}
        st.info("4/5 精准减持...")
        a4, d4 = self.s4.scan()
        r["m4"] = {"alerts": a4, "df": d4}
        st.info("5/5 融资融券...")
        a5s, a5l, d5 = self.s5.scan()
        r["m5"] = {"short": a5s, "long": a5l, "df": d5}
        return r
