# analyzer.py
# 适配新浪财经数据格式

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

        # 方案A：尝试拿真实公告
        ann_df = api.get_announcements(days=days_back, size=100)

        # 方案B：如果公告为空或没有title列，直接用全A股涨幅异动
        if ann_df.empty or "title" not in ann_df.columns:
            st.info("公告接口无数据，切换为全市场异动扫描模式")
            return self._scan_by_volume_anomaly(max_stocks)

        # 有title列但全是备用数据（不含关键词），也走异动模式
        has_keyword = ann_df["title"].apply(self._is_major).any()
        if not has_keyword:
            st.info("公告无关键词匹配，切换为全市场异动扫描模式")
            return self._scan_by_volume_anomaly(max_stocks)

        major = ann_df[ann_df["title"].apply(self._is_major)].copy()
        if "code" not in major.columns:
            return self._scan_by_volume_anomaly(max_stocks)

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

    def _scan_by_volume_anomaly(self, max_stocks=30):
        """不依赖公告，直接扫描全市场成交量异动"""
        alerts = []
        stocks = api.get_all_stocks()
        if stocks.empty:
            st.warning("全A股数据为空")
            return alerts, pd.DataFrame()

        stocks["pct"] = pd.to_numeric(stocks.get("pct", 0), errors="coerce").fillna(0)
        stocks["amount"] = pd.to_numeric(stocks.get("amount", 0), errors="coerce").fillna(0)

        # 取涨幅前N只
        top = stocks.nlargest(max_stocks, "pct")
        prog = st.progress(0, text="扫描成交量异动...")
        n = len(top)

        for i, (_, row) in enumerate(top.iterrows()):
            prog.progress((i + 1) / n, text=f"扫描 {row.get('name', '')} ({i+1}/{n})")
            code = str(row.get("code", ""))
            if not code or len(code) != 6:
                continue

            kl = api.get_kline(code, days=30)
            if kl.empty or len(kl) < 10:
                continue

            # 最近1天 vs 前20天均量
            recent = kl.iloc[-1]
            baseline = kl.iloc[-21:-1] if len(kl) >= 21 else kl.iloc[:-1]
            if baseline.empty:
                continue

            avg_vol = baseline["volume"].mean()
            avg_amt = baseline["amount"].mean()
            if avg_vol == 0:
                continue

            vol_ratio = recent["volume"] / avg_vol
            amt_ratio = recent["amount"] / avg_amt if avg_amt > 0 else 0

            if vol_ratio < 2.0:
                continue

            pct = recent["change_pct"]
            conf = min(vol_ratio / 10 + abs(pct) / 20, 1.0)

            if conf >= 0.6:
                lvl = "critical"
            elif conf >= 0.4:
                lvl = "high"
            elif conf >= 0.2:
                lvl = "mid"
            else:
                lvl = "low"

            alerts.append({
                "code": code,
                "name": row.get("name", ""),
                "ann_date": datetime.now().strftime("%Y-%m-%d"),
                "ann_type": "异动",
                "title": f"成交量放大{vol_ratio:.1f}倍，涨幅{pct:+.1f}%",
                "anom_date": recent["date"].strftime("%Y-%m-%d") if hasattr(recent["date"], "strftime") else str(recent["date"])[:10],
                "days_before": 0,
                "vol_ratio": round(vol_ratio, 1),
                "amt_ratio": round(amt_ratio, 1),
                "pre_change": round(pct, 1),
                "confidence": round(conf, 2),
                "level": lvl,
            })

        prog.empty()
        alerts.sort(key=lambda x: x.get("vol_ratio", 0), reverse=True)
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

        score = min(max_vr / 10, 0.3) + min(max_ar / 10, 0.2)
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

        # 新浪龙虎榜不按日期过滤，一次拉取最近数据
        st.info("正在拉取龙虎榜数据...")
        dt_list = api.get_dragon_tiger(size=100)

        if dt_list.empty:
            st.warning("龙虎榜数据为空，请检查API诊断")
            return alerts, pd.DataFrame(), pd.DataFrame()

        st.info(f"获取到 {len(dt_list)} 条龙虎榜记录，列: {list(dt_list.columns)}")

        # 确保有code列
        if "code" not in dt_list.columns:
            st.warning(f"龙虎榜缺少code列，现有列: {list(dt_list.columns)}")
            return alerts, pd.DataFrame(), dt_list

        prog = st.progress(0, text="分析龙虎榜明细...")
        n = len(dt_list)

        for i, (_, sr) in enumerate(dt_list.head(30).iterrows()):
            prog.progress((i + 1) / min(n, 30), text=f"分析 {sr.get('name', '')} ({i+1})")
            code = str(sr.get("code", ""))
            name = str(sr.get("name", ""))
            pct = self._to_float(sr.get("pct", 0))
            reason = str(sr.get("reason", ""))
            dt = str(sr.get("date", datetime.now().strftime("%Y-%m-%d")))[:10]

            # 拉取营业部明细
            detail = api.get_dragon_detail(code, dt)

            if detail.empty:
                all_raw.append({
                    "date": dt, "code": code, "name": name,
                    "pct": pct, "seat": "（无明细）", "alias": "",
                    "direction": "", "buy": 0, "sell": 0,
                    "net": 0, "reason": reason, "is_famous": False,
                })
                continue

            for _, dr in detail.iterrows():
                seat = str(dr.get("seat", ""))
                alias = self._match(seat)
                direction = str(dr.get("direction", ""))
                buy_v = self._to_float(dr.get("buy", 0))
                sell_v = self._to_float(dr.get("sell", 0))
                net_v = self._to_float(dr.get("net", 0))

                all_raw.append({
                    "date": dt, "code": code, "name": name,
                    "pct": pct, "seat": seat, "alias": alias,
                    "direction": direction,
                    "buy": buy_v, "sell": sell_v,
                    "net": net_v, "reason": reason,
                    "is_famous": alias != "",
                })

                if alias and "买" in direction:
                    alerts.append({
                        "date": dt, "code": code, "name": name,
                        "pct": pct, "seat": seat, "alias": alias,
                        "buy_amt": buy_v, "net": net_v,
                        "reason": reason,
                        "level": "high" if buy_v > 5000 else "mid",
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

    def _to_float(self, val):
        try:
            if pd.isna(val):
                return 0.0
            return float(str(val).replace(",", "").replace("%", ""))
        except (ValueError, TypeError):
            return 0.0

    def _build_summary(self, raw_df):
        if raw_df.empty:
            return pd.DataFrame()
        if "direction" not in raw_df.columns:
            return pd.DataFrame()
        buy_df = raw_df[raw_df["direction"].str.contains("买", na=False)]
        if buy_df.empty:
            # 如果没有明确的买入标记，显示全部
            buy_df = raw_df[raw_df["seat"] != "（无明细）"]
        if buy_df.empty:
            return pd.DataFrame()

        stats = []
        for seat, grp in buy_df.groupby("seat"):
            if not seat or seat == "（无明细）":
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

        if not stats:
            return pd.DataFrame()
        return pd.DataFrame(stats).sort_values("trades", ascending=False).head(30)


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

        st.info(f"获取到 {len(df)} 条大宗交易，列: {list(df.columns)}")

        # 确保数值列
        for c in ["premium_pct", "deal_amount", "next1d", "next5d",
                   "close", "deal_price", "deal_vol"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

        # 如果没有premium_pct但有deal_price和close，计算它
        if "premium_pct" not in df.columns or df["premium_pct"].sum() == 0:
            if "deal_price" in df.columns and "close" in df.columns:
                mask = df["close"] > 0
                df.loc[mask, "premium_pct"] = (
                    (df.loc[mask, "deal_price"] - df.loc[mask, "close"])
                    / df.loc[mask, "close"] * 100
                ).round(2)

        if "deal_amount" in df.columns:
            df["deal_wan"] = df["deal_amount"] / 1e4
        elif "deal_vol" in df.columns and "deal_price" in df.columns:
            df["deal_wan"] = (df["deal_vol"] * df["deal_price"]) / 1e4
        else:
            df["deal_wan"] = 0

        # 所有折价交易（不仅仅是超阈值的）
        if "premium_pct" in df.columns:
            discount = df[df["premium_pct"] < 0].copy()
        else:
            discount = pd.DataFrame()
            st.info("无折溢价数据")

        # 折价 + 次日涨
        if not discount.empty:
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

                # 降低阈值：只要折价且次日涨就报
                if next1 > 1 and disc < -1:
                    if next1 > 7:
                        lvl = "critical"
                    elif next1 > 4:
                        lvl = "high"
                    elif next1 > 2:
                        lvl = "mid"
                    else:
                        lvl = "low"

                    next5 = r.get("next5d", 0)
                    if pd.isna(next5):
                        next5 = 0

                    alerts.append({
                        "date": str(r.get("date", ""))[:10],
                        "code": str(r.get("code", "")),
                        "name": str(r.get("name", "")),
                        "discount": round(float(disc), 2),
                        "deal_wan": round(float(amt), 0),
                        "buyer": str(r.get("buyer", ""))[:30],
                        "seller": str(r.get("seller", ""))[:30],
                        "next1d": round(float(next1), 2),
                        "next5d": round(float(next5), 2),
                        "level": lvl,
                    })

        alerts.sort(key=lambda x: x.get("next1d", 0), reverse=True)

        # 买方统计
        buyer_stats = pd.DataFrame()
        if not discount.empty and "buyer" in discount.columns:
            try:
                grp_cols = {"buyer": "count"}
                agg_dict = {"buyer": "count"}
                if "premium_pct" in discount.columns:
                    agg_dict["premium_pct"] = "mean"
                if "next1d" in discount.columns:
                    agg_dict["next1d"] = "mean"
                if "deal_wan" in discount.columns:
                    agg_dict["deal_wan"] = "sum"

                bs = discount.groupby("buyer").agg(**{
                    "trades": ("buyer", "count"),
                }).reset_index()

                for col, func in [("premium_pct", "mean"), ("next1d", "mean"), ("deal_wan", "sum")]:
                    if col in discount.columns:
                        bs[col] = discount.groupby("buyer")[col].transform(func).drop_duplicates().values[:len(bs)]

                bs = bs.sort_values("trades", ascending=False).head(20)
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

        st.info(f"获取到 {len(red_df)} 条减持记录，列: {list(red_df.columns)}")

        if "code" not in red_df.columns:
            st.warning(f"减持数据缺少code列，现有列: {list(red_df.columns)}")
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

        # 尝试多种日期字段
        end_date = ""
        for key in ["end_date", "截止日期", "结束日期", "变动截止日"]:
            val = r.get(key, "")
            if val and str(val) != "nan":
                end_date = str(val)[:10]
                break

        if not end_date or len(end_date) < 8:
            # 没有日期就用当前日期往前推30天
            end_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

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
            # 用最后30天的中点
            red_idx = max(0, len(kl) - 15)

        post = kl.iloc[red_idx:min(red_idx + 30, len(kl))]
        if post.empty or len(post) < 3:
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
        if not pre.empty and len(pre) > 1 and pre.iloc[0]["open"] > 0:
            pre_chg = (pre.iloc[-1]["close"] - pre.iloc[0]["open"]) / pre.iloc[0]["open"] * 100

        # 降低阈值：减持后跌超5%就报
        is_prec = pre_chg > 3 and max_drop < -8
        if max_drop > -3:
            return None

        if max_drop < -20:
            lvl = "critical"
        elif max_drop < -15:
            lvl = "high"
        elif max_drop < -8:
            lvl = "mid"
        else:
            lvl = "low"

        holder = ""
        for key in ["holder", "股东名称", "股东"]:
            val = r.get(key, "")
            if val and str(val) != "nan":
                holder = str(val)[:20]
                break

        holder_type = ""
        for key in ["holder_type", "类型", "身份"]:
            val = r.get(key, "")
            if val and str(val) != "nan":
                holder_type = str(val)
                break

        return {
            "code": code,
            "name": str(r.get("name", "")),
            "holder": holder,
            "holder_type": holder_type,
            "end_date": end_date,
            "change_ratio": r.get("change_ratio", 0),
            "pre_change": round(pre_chg, 1),
            "post_drop": round(max_drop, 1),
            "post_total
