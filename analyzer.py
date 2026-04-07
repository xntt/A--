# analyzer.py

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import streamlit as st
from eastmoney_api import api
from config import (
    VOLUME_ANOMALY_RATIO, AMOUNT_ANOMALY_RATIO,
    PRE_ANNOUNCE_WINDOW, BASELINE_WINDOW,
    POSITIVE_KEYWORDS, NEGATIVE_KEYWORDS,
    FAMOUS_SEATS, BLOCK_DISCOUNT_THRESHOLD,
    BLOCK_AMOUNT_MIN, MARGIN_SPIKE_RATIO,
)


# ══════════════════════════════════════
#  模块1：公告前异动
# ══════════════════════════════════════

class PreAnnounceScanner:

    def scan(self, days_back=30, max_stocks=30):
        alerts = []
        ann_df = api.get_announcements(days=days_back, size=100)
        if ann_df.empty:
            st.warning("公告数据为空")
            return alerts, pd.DataFrame()

        if "title" not in ann_df.columns:
            st.warning("公告数据缺少title列")
            return alerts, pd.DataFrame()

        major = ann_df[ann_df["title"].apply(self._is_major)].copy()
        if major.empty:
            st.info("未找到含关键词的重大公告")
            return alerts, pd.DataFrame()

        if "code" not in major.columns:
            st.warning("公告数据缺少code列")
            return alerts, pd.DataFrame()

        major = major.drop_duplicates(subset=["code"], keep="first").head(max_stocks)
        prog = st.progress(0, text="扫描中...")
        n = len(major)

        for i, (_, r) in enumerate(major.iterrows()):
            prog.progress((i + 1) / n, text=f"扫描 {r.get('name', '')} ({i+1}/{n})")
            res = self._check(r)
            if res:
                alerts.append(res)

        prog.empty()
        alerts.sort(key=lambda x: x.get("confidence", 0), reverse=True)
        df = pd.DataFrame(alerts) if alerts else pd.DataFrame()
        return alerts, df

    def _is_major(self, title):
        t = str(title)
        return any(k in t for k in POSITIVE_KEYWORDS + NEGATIVE_KEYWORDS)

    def _classify(self, title):
        t = str(title)
        if any(k in t for k in POSITIVE_KEYWORDS):
            return "利好"
        if any(k in t for k in NEGATIVE_KEYWORDS):
            return "利空"
        return "中性"

    def _check(self, ann):
        code = str(ann.get("code", ""))
        if not code or len(code) != 6:
            return None

        kl = api.get_kline(code, days=60)
        if kl.empty or len(kl) < BASELINE_WINDOW + PRE_ANNOUNCE_WINDOW:
            return None

        kl["ds"] = kl["date"].dt.strftime("%Y-%m-%d")
        ann_date = str(ann.get("ann_date", ""))[:10]
        ann_type = self._classify(ann.get("title", ""))

        idx = None
        for j in range(len(kl)):
            if kl.iloc[j]["ds"] >= ann_date:
                idx = j
                break
        if idx is None:
            idx = len(kl) - 1

        b_end = idx - PRE_ANNOUNCE_WINDOW
        b_start = b_end - BASELINE_WINDOW
        if b_start < 0:
            return None

        base = kl.iloc[b_start:b_end]
        pre = kl.iloc[b_end:idx]
        if base.empty or pre.empty:
            return None

        avg_v = base["volume"].mean()
        avg_a = base["amount"].mean()
        if avg_v == 0 or avg_a == 0:
            return None

        max_vr, max_ar, anom_date, days_b = 0, 0, "", 0
        for k2, (_, row) in enumerate(pre.iterrows()):
            vr = row["volume"] / avg_v
            ar = row["amount"] / avg_a
            if vr > max_vr:
                max_vr = vr
                max_ar = ar
                anom_date = row["ds"]
                days_b = idx - b_end - k2

        if max_vr < VOLUME_ANOMALY_RATIO and max_ar < AMOUNT_ANOMALY_RATIO:
            return None

        p0 = pre.iloc[0]["open"]
        p1 = pre.iloc[-1]["close"]
        chg = (p1 - p0) / p0 * 100 if p0 > 0 else 0

        score = 0.0
        score += min(max_vr / 10, 0.3)
        score += min(max_ar / 10, 0.2)
        if (ann_type == "利好" and chg > 3) or (ann_type == "利空" and chg < -3):
            score += 0.3
        elif (ann_type == "利好" and chg > 0) or (ann_type == "利空" and chg < 0):
            score += 0.15
        if 1 <= days_b <= 3:
            score += 0.2
        elif days_b <= 5:
            score += 0.1
        conf = min(score, 1.0)

        if conf >= 0.7:
            lvl = "critical"
        elif conf >= 0.5:
            lvl = "high"
        elif conf >= 0.3:
            lvl = "mid"
        else:
            lvl = "low"

        return {
            "code": code, "name": ann.get("name", ""),
            "ann_date": ann_date, "ann_type": ann_type,
            "title": str(ann.get("title", ""))[:50],
            "anom_date": anom_date, "days_before": days_b,
            "vol_ratio": round(max_vr, 1), "amt_ratio": round(max_ar, 1),
            "pre_change": round(chg, 1), "confidence": round(conf, 2),
            "level": lvl,
        }


# ══════════════════════════════════════
#  模块2：龙虎榜席位追踪
# ══════════════════════════════════════

class DragonTigerTracker:

    def __init__(self):
        self.reverse_map = {}
        for alias, kw in FAMOUS_SEATS.items():
            self.reverse_map[kw] = alias

    def scan(self, days=5):
        alerts = []
        all_raw = []

        prog = st.progress(0, text="扫描龙虎榜...")
        for d in range(days):
            prog.progress((d + 1) / days, text=f"龙虎榜第{d+1}/{days}天...")
            dt = (datetime.now() - timedelta(days=d)).strftime("%Y-%m-%d")
            dt_list = api.get_dragon_tiger(date=dt, size=100)
            if dt_list.empty:
                continue

            for _, sr in dt_list.iterrows():
                code = sr.get("code", "")
                name = sr.get("name", "")
                pct = sr.get("pct", 0)
                reason = sr.get("reason", "")

                detail = api.get_dragon_detail(code, dt)
                if detail.empty:
                    all_raw.append({
                        "date": dt, "code": code, "name": name,
                        "pct": pct, "seat": "", "alias": "",
                        "direction": "", "buy": 0, "sell": 0,
                        "net": 0, "reason": reason, "is_famous": False,
                    })
                    continue

                for _, dr in detail.iterrows():
                    seat = str(dr.get("seat", ""))
                    alias = self._match(seat)
                    direction = dr.get("direction", "")
                    buy_v = dr.get("buy", 0)
                    net_v = dr.get("net", 0)

                    row_data = {
                        "date": dt, "code": code, "name": name,
                        "pct": pct, "seat": seat, "alias": alias,
                        "direction": direction,
                        "buy": buy_v, "sell": dr.get("sell", 0),
                        "net": net_v, "reason": reason,
                        "is_famous": alias != "",
                    }
                    all_raw.append(row_data)

                    if alias and direction == "买入":
                        alerts.append({
                            "date": dt, "code": code, "name": name,
                            "pct": pct, "seat": seat, "alias": alias,
                            "buy_amt": buy_v, "net": net_v,
                            "reason": reason,
                            "level": "high" if buy_v and float(buy_v) > 5000 else "mid",
                        })

        prog.empty()

        raw_df = pd.DataFrame(all_raw) if all_raw else pd.DataFrame()
        summary_df = self._build_summary(raw_df)
        return alerts, summary_df, raw_df

    def _match(self, seat_name):
        s = str(seat_name)
        for kw, alias in self.reverse_map.items():
            if kw in s:
                return alias
        return ""

    def _build_summary(self, raw_df):
        if raw_df.empty or "direction" not in raw_df.columns:
            return pd.DataFrame()
        buy_df = raw_df[raw_df["direction"] == "买入"]
        if buy_df.empty:
            return pd.DataFrame()

        stats = []
        for seat, grp in buy_df.groupby("seat"):
            if not seat:
                continue
            alias = grp.iloc[0].get("alias", "")
            total = len(grp)
            codes = grp["code"].unique().tolist()[:5]
            stats.append({
                "seat": str(seat)[:35],
                "alias": alias,
                "trades": total,
                "stocks": ", ".join(str(c) for c in codes),
            })

        return pd.DataFrame(stats).sort_values("trades", ascending=False).head(30) if stats else pd.DataFrame()


# ══════════════════════════════════════
#  模块3：大宗交易监控
# ══════════════════════════════════════

class BlockTradeMonitor:

    def scan(self, days=30):
        alerts = []
        df = api.get_block_trades(days=days, size=500)
        if df.empty:
            st.warning("大宗交易数据为空")
            return alerts, pd.DataFrame(), pd.DataFrame()

        for c in ["premium_pct", "deal_amount", "next1d", "next5d"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")

        if "deal_amount" in df.columns:
            df["deal_wan"] = df["deal_amount"] / 1e4
        else:
            df["deal_wan"] = 0

        if "premium_pct" not in df.columns:
            st.warning("大宗交易缺少折价率数据")
            return alerts, df, pd.DataFrame()

        discount = df[df["premium_pct"] <= BLOCK_DISCOUNT_THRESHOLD].copy()

        for _, r in discount.iterrows():
            next1 = r.get("next1d", 0)
            if pd.isna(next1):
                next1 = 0
            disc = r.get("premium_pct", 0)
            if pd.isna(disc):
                disc = 0
            amt = r.get("deal_wan", 0)
            if pd.isna(amt):
                amt = 0

            if next1 > 2 and amt > BLOCK_AMOUNT_MIN:
                if next1 > 7:
                    lvl = "critical"
                elif next1 > 5:
                    lvl = "high"
                else:
                    lvl = "mid"

                next5 = r.get("next5d", 0)
                if pd.isna(next5):
                    next5 = 0

                alerts.append({
                    "date": str(r.get("date", ""))[:10],
                    "code": r.get("code", ""),
                    "name": r.get("name", ""),
                    "discount": round(float(disc), 2),
                    "deal_wan": round(float(amt), 0),
                    "buyer": str(r.get("buyer", ""))[:30],
                    "seller": str(r.get("seller", ""))[:30],
                    "next1d": round(float(next1), 2),
                    "next5d": round(float(next5), 2),
                    "level": lvl,
                })

        alerts.sort(key=lambda x: x.get("next1d", 0), reverse=True)

        buyer_stats = pd.DataFrame()
        if not discount.empty and "buyer" in discount.columns:
            try:
                bs = discount.groupby("buyer").agg(
                    trades=("buyer", "count"),
                    avg_disc=("premium_pct", "mean"),
                    avg_n1=("next1d", "mean"),
                    total_amt=("deal_wan", "sum"),
                ).reset_index()
                bs = bs.sort_values("trades", ascending=False).head(20)
                for c2 in ["avg_disc", "avg_n1", "total_amt"]:
                    bs[c2] = bs[c2].round(2)
                buyer_stats = bs
            except Exception:
                pass

        return alerts, df, buyer_stats


# ══════════════════════════════════════
#  模块4：精准减持
# ══════════════════════════════════════

class InsiderReductionDetector:

    def scan(self, max_stocks=40):
        alerts = []
        red_df = api.get_holder_changes("减持", size=200)
        if red_df.empty:
            st.warning("减持数据为空")
            return alerts, pd.DataFrame()

        if "code" not in red_df.columns:
            st.warning("减持数据缺少code列")
            return alerts, pd.DataFrame()

        red_df = red_df.drop_duplicates(subset=["code"], keep="first").head(max_stocks)
        prog = st.progress(0, text="扫描精准减持...")
        n = len(red_df)

        for i, (_, r) in enumerate(red_df.iterrows()):
            prog.progress((i + 1) / n, text=f"扫描 {r.get('name', '')} ({i+1}/{n})")
            res = self._check(r)
            if res:
                alerts.append(res)

        prog.empty()
        alerts.sort(key=lambda x: x.get("post_drop", 0))
        df = pd.DataFrame(alerts) if alerts else pd.DataFrame()
        return alerts, df

    def _check(self, r):
        code = str(r.get("code", ""))
        if not code or len(code) != 6:
            return None

        end_date = str(r.get("end_date", ""))[:10]
        if not end_date or len(end_date) < 8:
            return None

        kl = api.get_kline(code, days=90)
        if kl.empty or len(kl) < 10:
            return None

        kl["ds"] = kl["date"].dt.strftime("%Y-%m-%d")

        red_idx = None
        for j in range(len(kl)):
            if kl.iloc[j]["ds"] >= end_date:
                red_idx = j
                break
        if red_idx is None:
            return None

        post = kl.iloc[red_idx:min(red_idx + 30, len(kl))]
        if post.empty:
            return None

        sp = post.iloc[0]["close"]
        if sp <= 0:
            return None

        min_p = post["low"].min()
        max_drop = (min_p - sp) / sp * 100

        ep = post.iloc[-1]["close"]
        total_chg = (ep - sp) / sp * 100

        pre_start = max(0, red_idx - 20)
        pre = kl.iloc[pre_start:red_idx]
        pre_chg = 0
        if not pre.empty and pre.iloc[0]["open"] > 0:
            pre_chg = (pre.iloc[-1]["close"] - pre.iloc[0]["open"]) / pre.iloc[0]["open"] * 100

        is_prec = pre_chg > 5 and max_drop < -10
        if not is_prec and max_drop > -5:
            return None

        if max_drop < -20:
            lvl = "critical"
        elif max_drop < -15:
            lvl = "high"
        elif max_drop < -10:
            lvl = "mid"
        else:
            lvl = "low"

        return {
            "code": code,
            "name": r.get("name", ""),
            "holder": str(r.get("holder", ""))[:20],
            "holder_type": str(r.get("holder_type", "")),
            "end_date": end_date,
            "change_ratio": r.get("change_ratio", 0),
            "pre_change": round(pre_chg, 1),
            "post_drop": round(max_drop, 1),
            "post_total": round(total_chg, 1),
            "level": lvl,
            "is_precision": is_prec,
        }


# ══════════════════════════════════════
#  模块5：融资融券异动
# ══════════════════════════════════════

class MarginAnomalyDetector:

    def scan(self, top_n=30):
        short_alerts = []
        long_alerts = []

        rq_df = api.get_margin_ranking(sort_by="RQMCL", size=top_n)
        rz_df = api.get_margin_ranking(sort_by="RZMRE", size=top_n)

        if not rq_df.empty and "code" in rq_df.columns:
            short_alerts = self._detect_spike(rq_df, "rq_sell", "做空预警")

        if not rz_df.empty and "code" in rz_df.columns:
            long_alerts = self._detect_spike(rz_df, "rz_buy", "做多信号")

        combined = pd.DataFrame()
        frames = []
        if not rq_df.empty:
            frames.append(rq_df.head(20))
        if not rz_df.empty:
            frames.append(rz_df.head(20))
        if frames:
            combined = pd.concat(frames, ignore_index=True)
            if "code" in combined.columns:
                combined = combined.drop_duplicates(subset=["code"], keep="first")

        return short_alerts, long_alerts, combined

    def _detect_spike(self, df, col, signal_name):
        alerts = []
        prog = st.progress(0, text=f"扫描{signal_name}...")
        check_df = df.head(15)
        n = len(check_df)

        for i, (_, r) in enumerate(check_df.iterrows()):
            prog.progress((i + 1) / n, text=f"{signal_name} {i+1}/{n}")
            code = str(r.get("code", ""))
            name = r.get("name", "")
            if not code or len(code) != 6:
                continue

            hist = api.get_margin_detail(code=code, size=20)
            if hist.empty or len(hist) < 5:
                continue

            if col not in hist.columns:
                continue

            hist[col] = pd.to_numeric(hist[col], errors="coerce").fillna(0)
            latest = hist.iloc[0][col]
            avg = hist.iloc[1:11][col].mean()

            if avg > 0 and latest > 0:
                ratio = latest / avg
                if ratio >= MARGIN_SPIKE_RATIO:
                    kl = api.get_kline(code, days=5)
                    price_chg = 0
                    if not kl.empty:
                        price_chg = kl.iloc[-1]["change_pct"]

                    if ratio >= 5:
                        lvl = "critical"
                    elif ratio >= 3:
                        lvl = "high"
                    else:
                        lvl = "mid"

                    alerts.append({
                        "code": code, "name": name,
                        "today": latest, "avg": round(avg, 0),
                        "spike_ratio": round(ratio, 1),
                        "price_chg": round(price_chg, 2),
                        "level": lvl, "signal": signal_name,
                    })

        prog.empty()
        alerts.sort(key=lambda x: x.get("spike_ratio", 0), reverse=True)
        return alerts


# ══════════════════════════════════════
#  综合扫描器
# ══════════════════════════════════════

class SmartMoneyScanner:

    def __init__(self):
        self.s1 = PreAnnounceScanner()
        self.s2 = DragonTigerTracker()
        self.s3 = BlockTradeMonitor()
        self.s4 = InsiderReductionDetector()
        self.s5 = MarginAnomalyDetector()

    def run_all(self):
        results = {}

        st.info("▶ 1/5 公告前异动...")
        a1, d1 = self.s1.scan()
        results["m1"] = {"alerts": a1, "df": d1}

        st.info("▶ 2/5 龙虎榜追踪...")
        a2, s2, r2 = self.s2.scan(days=3)
        results["m2"] = {"alerts": a2, "summary": s2, "raw": r2}

        st.info("▶ 3/5 大宗交易...")
        a3, d3, b3 = self.s3.scan(days=30)
        results["m3"] = {"alerts": a3, "df": d3, "buyers": b3}

        st.info("▶ 4/5 精准减持...")
        a4, d4 = self.s4.scan()
        results["m4"] = {"alerts": a4, "df": d4}

        st.info("▶ 5/5 融资融券...")
        a5s, a5l, d5 = self.s5.scan()
        results["m5"] = {"short": a5s, "long": a5l, "df": d5}

        return results
