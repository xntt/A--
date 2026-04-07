# analyzer.py
"""全部5个分析模块 — 完整版"""

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
    BLOCK_AMOUNT_MIN, MARGIN_SPIKE_RATIO, COLORS,
)


# ═══════════════════════════════════════════════════════════
#  模块1：公告前异动扫描
# ═══════════════════════════════════════════════════════════

class PreAnnounceScanner:
    """扫描公告发布前 N 日的成交量/成交额异常放大"""

    def scan(self, days_back=30, max_stocks=30):
        """
        主扫描入口
        返回 (alerts_list, detail_dataframe)
        """
        alerts = []
        rows = []

        ann_df = api.get_announcements(days=days_back, size=100)
        if ann_df.empty:
            return alerts, pd.DataFrame()

        major = ann_df[ann_df["title"].apply(self._is_major)].copy()
        if major.empty:
            return alerts, pd.DataFrame()

        major = major.drop_duplicates(subset=["code"], keep="first").head(max_stocks)

        prog = st.progress(0, text="扫描公告前异动...")
        n = len(major)
        for i, (_, r) in enumerate(major.iterrows()):
            prog.progress((i + 1) / n, text=f"扫描 {r.get('name', '')}...")
            res = self._check(r)
            if res:
                alerts.append(res)
                rows.append(res)
        prog.empty()

        alerts.sort(key=lambda x: x.get("confidence", 0), reverse=True)
        return alerts, pd.DataFrame(rows) if rows else pd.DataFrame()

    def _is_major(self, title):
        """判断公告标题是否包含重大关键词"""
        title = str(title)
        return any(k in title for k in POSITIVE_KEYWORDS + NEGATIVE_KEYWORDS)

    def _classify(self, title):
        """判断公告属于利好还是利空"""
        title = str(title)
        if any(k in title for k in POSITIVE_KEYWORDS):
            return "利好"
        if any(k in title for k in NEGATIVE_KEYWORDS):
            return "利空"
        return "中性"

    def _check(self, ann):
        """对单只股票做公告前异动检测"""
        code = ann.get("code", "")
        if not code or len(code) != 6:
            return None

        kl = api.get_kline(code, days=60)
        if kl.empty or len(kl) < BASELINE_WINDOW + PRE_ANNOUNCE_WINDOW:
            return None

        kl["ds"] = kl["date"].dt.strftime("%Y-%m-%d")
        ann_date = str(ann.get("ann_date", ""))[:10]
        ann_type = self._classify(ann.get("title", ""))

        # 找公告日在K线中的位置
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

        max_vr = 0
        max_ar = 0
        anom_date = ""
        days_b = 0
        for k, (_, row) in enumerate(pre.iterrows()):
            vr = row["volume"] / avg_v
            ar = row["amount"] / avg_a
            if vr > max_vr:
                max_vr = vr
                max_ar = ar
                anom_date = row["ds"]
                days_b = idx - b_end - k

        if max_vr < VOLUME_ANOMALY_RATIO and max_ar < AMOUNT_ANOMALY_RATIO:
            return None

        p0 = pre.iloc[0]["open"]
        p1 = pre.iloc[-1]["close"]
        chg = (p1 - p0) / p0 * 100 if p0 > 0 else 0

        # 置信度打分
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
            "code": code,
            "name": ann.get("name", ""),
            "ann_date": ann_date,
            "ann_type": ann_type,
            "title": str(ann.get("title", ""))[:50],
            "anom_date": anom_date,
            "days_before": days_b,
            "vol_ratio": round(max_vr, 1),
            "amt_ratio": round(max_ar, 1),
            "pre_change": round(chg, 1),
            "confidence": round(conf, 2),
            "level": lvl,
        }


# ═══════════════════════════════════════════════════════════
#  模块2：龙虎榜席位追踪
# ═══════════════════════════════════════════════════════════

class DragonTigerTracker:
    """追踪龙虎榜知名游资席位及其胜率"""

    def __init__(self):
        # 反向映射：关键词 → 别名
        self.reverse_map = {}
        for alias, kw in FAMOUS_SEATS.items():
            self.reverse_map[kw] = alias

    def scan(self, days=5):
        """
        扫描近 N 天龙虎榜
        返回 (alerts_list, summary_df, raw_df)
        """
        alerts = []
        all_raw = []

        prog = st.progress(0, text="扫描龙虎榜...")
        for d in range(days):
            prog.progress((d + 1) / days, text=f"扫描第 {d+1}/{days} 天龙虎榜...")
            dt = (datetime.now() - timedelta(days=d)).strftime("%Y-%m-%d")
            dt_list = api.get_dragon_tiger(date=dt)
            if dt_list.empty:
                continue

            for _, stock_row in dt_list.iterrows():
                code = stock_row.get("code", "")
                name = stock_row.get("name", "")
                pct = stock_row.get("pct", 0)
                reason = stock_row.get("reason", "")

                # 拉取营业部明细
                detail = api.get_dragon_detail(code, dt)
                if detail.empty:
                    continue

                for _, seat_row in detail.iterrows():
                    seat = str(seat_row.get("seat", ""))
                    direction = seat_row.get("direction", "")
                    buy_amt = seat_row.get("buy", 0)
                    sell_amt = seat_row.get("sell", 0)
                    net = seat_row.get("net", 0)

                    # 检查是否为知名游资
                    alias = self._match_famous(seat)

                    row_data = {
                        "date": dt,
                        "code": code,
                        "name": name,
                        "pct": pct,
                        "seat": seat,
                        "alias": alias,
                        "direction": direction,
                        "buy_amt": buy_amt,
                        "sell_amt": sell_amt,
                        "net": net,
                        "reason": reason,
                        "is_famous": alias != "",
                    }
                    all_raw.append(row_data)

                    # 知名游资买入 → 生成预警
                    if alias and direction == "买入":
                        alerts.append({
                            "date": dt,
                            "code": code,
                            "name": name,
                            "pct": pct,
                            "seat": seat,
                            "alias": alias,
                            "buy_amt": buy_amt,
                            "net": net,
                            "reason": reason,
                            "level": "high" if buy_amt > 5000 else "mid",
                        })

        prog.empty()

        raw_df = pd.DataFrame(all_raw) if all_raw else pd.DataFrame()

        # 构建席位统计
        summary_df = self._build_seat_summary(raw_df) if not raw_df.empty else pd.DataFrame()

        return alerts, summary_df, raw_df

    def _match_famous(self, seat_name):
        """匹配是否为知名游资席位"""
        seat_name = str(seat_name)
        for kw, alias in self.reverse_map.items():
            if kw in seat_name:
                return alias
        return ""

    def _build_seat_summary(self, raw_df):
        """构建席位买入后次日胜率统计"""
        buy_df = raw_df[raw_df["direction"] == "买入"].copy()
        if buy_df.empty:
            return pd.DataFrame()

        stats = []
        for seat, grp in buy_df.groupby("seat"):
            alias = grp.iloc[0].get("alias", "")
            total = len(grp)
            codes = grp["code"].unique().tolist()

            # 计算次日表现（简化：拉取K线看买入日后一天）
            win = 0
            next_pcts = []
            for _, r in grp.head(10).iterrows():  # 限制API调用
                kl = api.get_kline(r["code"], days=10)
                if kl.empty:
                    continue
                kl["ds"] = kl["date"].dt.strftime("%Y-%m-%d")
                buy_date = str(r["date"])[:10]
                found = False
                for ki in range(len(kl) - 1):
                    if kl.iloc[ki]["ds"] == buy_date:
                        next_pct = kl.iloc[ki + 1]["change_pct"]
                        next_pcts.append(next_pct)
                        if next_pct > 0:
                            win += 1
                        found = True
                        break

            win_rate = (win / len(next_pcts) * 100) if next_pcts else 0
            avg_next = np.mean(next_pcts) if next_pcts else 0

            stats.append({
                "seat": seat[:30],
                "alias": alias,
                "trades": total,
                "sampled": len(next_pcts),
                "win_rate": round(win_rate, 1),
                "avg_next1d": round(avg_next, 2),
                "stocks": ", ".join(codes[:5]),
            })

        return pd.DataFrame(stats).sort_values("trades", ascending=False)


# ═══════════════════════════════════════════════════════════
#  模块3：大宗交易监控
# ═══════════════════════════════════════════════════════════

class BlockTradeMonitor:
    """监控大宗交易折价买入 + 次日拉升的关联"""

    def scan(self, days=30):
        """
        返回 (alerts_list, detail_df, stats_df)
        """
        alerts = []
        df = api.get_block_trades(days=days)
        if df.empty:
            return alerts, pd.DataFrame(), pd.DataFrame()

        # 确保数值列
        for c in ["premium_pct", "deal_amount", "next1d", "next5d"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")

        # 折价交易
        if "premium_pct" in df.columns:
            discount = df[df["premium_pct"] <= BLOCK_DISCOUNT_THRESHOLD].copy()
        else:
            discount = pd.DataFrame()

        if "deal_amount" in df.columns:
            df["deal_wan"] = df["deal_amount"] / 1e4
        else:
            df["deal_wan"] = 0

        # 折价 + 次日涨的异常交易
        for _, r in discount.iterrows():
            next1 = r.get("next1d", 0)
            if pd.isna(next1):
                next1 = 0
            disc = r.get("premium_pct", 0)
            amt = r.get("deal_wan", 0)

            if next1 > 3 and amt > BLOCK_AMOUNT_MIN:
                lvl = "critical" if next1 > 7 else "high" if next1 > 5 else "mid"
                alerts.append({
                    "date": str(r.get("date", ""))[:10],
                    "code": r.get("code", ""),
                    "name": r.get("name", ""),
                    "discount": round(disc, 2),
                    "deal_wan": round(amt, 0),
                    "buyer": str(r.get("buyer", ""))[:30],
                    "seller": str(r.get("seller", ""))[:30],
                    "next1d": round(next1, 2),
                    "next5d": round(r.get("next5d", 0) if pd.notna(r.get("next5d")) else 0, 2),
                    "level": lvl,
                })

        alerts.sort(key=lambda x: x.get("next1d", 0), reverse=True)

        # 买方统计（谁在频繁折价接盘）
        buyer_stats = pd.DataFrame()
        if not discount.empty and "buyer" in discount.columns:
            bs = discount.groupby("buyer").agg(
                trades=("buyer", "count"),
                avg_discount=("premium_pct", "mean"),
                avg_next1d=("next1d", "mean"),
                total_amount=("deal_wan", "sum"),
            ).reset_index()
            bs = bs.sort_values("trades", ascending=False).head(20)
            bs["avg_discount"] = bs["avg_discount"].round(2)
            bs["avg_next1d"] = bs["avg_next1d"].round(2)
            bs["total_amount"] = bs["total_amount"].round(0)
            buyer_stats = bs

        return alerts, df, buyer_stats


# ═══════════════════════════════════════════════════════════
#  模块4：高管精准减持检测
# ═══════════════════════════════════════════════════════════

class InsiderReductionDetector:
    """检测高管/大股东减持后出现利空的精准减持行为"""

    def scan(self, max_stocks=50):
        """
        返回 (alerts_list, detail_df)
        """
        alerts = []
        rows = []

        # 获取减持数据
        red_df = api.get_holder_changes("减持", size=200)
        if red_df.empty:
            return alerts, pd.DataFrame()

        red_df = red_df.drop_duplicates(subset=["code"], keep="first").head(max_stocks)

        prog = st.progress(0, text="扫描精准减持...")
        n = len(red_df)

        for i, (_, r) in enumerate(red_df.iterrows()):
            prog.progress((i + 1) / n, text=f"扫描 {r.get('name', '')}...")
            res = self._check_precision(r)
            if res:
                alerts.append(res)
                rows.append(res)
        prog.empty()

        alerts.sort(key=lambda x: x.get("post_drop", 0))  # 跌幅越大越前
        return alerts, pd.DataFrame(rows) if rows else pd.DataFrame()

    def _check_precision(self, r):
        """检查单只股票减持后走势"""
        code = r.get("code", "")
        if not code or len(code) != 6:
            return None

        end_date = str(r.get("end_date", ""))[:10]
        if not end_date:
            return None

        kl = api.get_kline(code, days=90)
        if kl.empty or len(kl) < 10:
            return None

        kl["ds"] = kl["date"].dt.strftime("%Y-%m-%d")

        # 找到减持结束日在K线中的位置
        red_idx = None
        for j in range(len(kl)):
            if kl.iloc[j]["ds"] >= end_date:
                red_idx = j
                break
        if red_idx is None:
            return None

        # 减持后30日走势
        post = kl.iloc[red_idx:min(red_idx + 30, len(kl))]
        if post.empty:
            return None

        # 减持后最大跌幅
        start_price = post.iloc[0]["close"]
        if start_price <= 0:
            return None
        min_price = post["low"].min()
        max_drop = (min_price - start_price) / start_price * 100

        # 减持后累计涨跌幅
        end_price = post.iloc[-1]["close"]
        total_chg = (end_price - start_price) / start_price * 100

        # 减持前涨幅（减持前20日）
        pre_start = max(0, red_idx - 20)
        pre = kl.iloc[pre_start:red_idx]
        pre_chg = 0
        if not pre.empty and pre.iloc[0]["open"] > 0:
            pre_chg = (pre.iloc[-1]["close"] - pre.iloc[0]["open"]) / pre.iloc[0]["open"] * 100

        # 精准减持判定：减持前涨 + 减持后跌
        is_precision = pre_chg > 5 and max_drop < -10
        if not is_precision and max_drop > -5:
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
            "holder_type": r.get("holder_type", ""),
            "end_date": end_date,
            "change_ratio": r.get("change_ratio", 0),
            "pre_change": round(pre_chg, 1),
            "post_drop": round(max_drop, 1),
            "post_total": round(total_chg, 1),
            "level": lvl,
            "is_precision": is_precision,
        }


# ═══════════════════════════════════════════════════════════
#  模块5：融资融券异动
# ═══════════════════════════════════════════════════════════

class MarginAnomalyDetector:
    """检测融券余额暴增（做空信号）和融资暴增（做多信号）"""

    def scan(self, top_n=50):
        """
        返回 (short_alerts, long_alerts, detail_df)
        """
        short_alerts = []
        long_alerts = []

        # 获取融资融券排名（按融券卖出量排序）
        rq_df = api.get_margin_ranking(sort_by="RQMCL", size=top_n)
        rz_df = api.get_margin_ranking(sort_by="RZMRE", size=top_n)

        # 分析融券异动（做空信号）
        if not rq_df.empty:
            short_alerts = self._detect_short_spike(rq_df)

        # 分析融资异动（做多信号）
        if not rz_df.empty:
            long_alerts = self._detect_long_spike(rz_df)

        # 合并展示
        all_data = pd.concat([rq_df.head(30), rz_df.head(30)], ignore_index=True)
        all_data = all_data.drop_duplicates(subset=["code"], keep="first") if "code" in all_data.columns else all_data

        return short_alerts, long_alerts, all_data

    def _detect_short_spike(self, df):
        """检测融券卖出量暴增"""
        alerts = []
        if "code" not in df.columns:
            return alerts

        for _, r in df.head(30).iterrows():
            code = r.get("code", "")
            name = r.get("name", "")
            if not code:
                continue

            # 拉取该股历史融资融券数据
            hist = api.get_margin_detail(code=code, size=20)
            if hist.empty or len(hist) < 5:
                continue

            for c in ["rq_sell", "rq_vol", "rq_bal"]:
                if c in hist.columns:
                    hist[c] = pd.to_numeric(hist[c], errors="coerce").fillna(0)

            if "rq_sell" not in hist.columns:
                continue

            latest = hist.iloc[0]["rq_sell"]
            avg = hist.iloc[1:11]["rq_sell"].mean()

            if avg > 0 and latest > 0:
                ratio = latest / avg
                if ratio >= MARGIN_SPIKE_RATIO:
                    # 查看同期股价变动
                    kl = api.get_kline(code, days=10)
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
                        "code": code,
                        "name": name,
                        "rq_sell_today": latest,
                        "rq_sell_avg": round(avg, 0),
                        "spike_ratio": round(ratio, 1),
                        "rq_balance": hist.iloc[0].get("rq_bal", 0),
                        "price_chg": round(price_chg, 2),
                        "level": lvl,
                        "signal": "做空预警",
                    })

        alerts.sort(key=lambda x: x.get("spike_ratio", 0), reverse=True)
        return alerts

    def _detect_long_spike(self, df):
        """检测融资买入额暴增"""
        alerts = []
        if "code" not in df.columns:
            return alerts

        for _, r in df.head(20).iterrows():
            code = r.get("code", "")
            name = r.get("name", "")
            if not code:
                continue

            hist = api.get_margin_detail(code=code, size=20)
            if hist.empty or len(hist) < 5:
                continue

            if "rz_buy" in hist.columns:
                hist["rz_buy"] = pd.to_numeric(hist["rz_buy"], errors="coerce").fillna(0)
            else:
                continue

            latest = hist.iloc[0]["rz_buy"]
            avg = hist.iloc[1:11]["rz_buy"].mean()

            if avg > 0 and latest > 0:
                ratio = latest / avg
                if ratio >= MARGIN_SPIKE_RATIO:
                    kl = api.get_kline(code, days=10)
                    price_chg = 0
                    if not kl.empty:
                        price_chg = kl.iloc[-1]["change_pct"]

                    lvl = "high" if ratio >= 4 else "mid"

                    alerts.append({
                        "code": code,
                        "name": name,
                        "rz_buy_today": latest,
                        "rz_buy_avg": round(avg, 0),
                        "spike_ratio": round(ratio, 1),
                        "rz_balance": hist.iloc[0].get("rz_bal", 0),
                        "price_chg": round(price_chg, 2),
                        "level": lvl,
                        "signal": "做多信号",
                    })

        alerts.sort(key=lambda x: x.get("spike_ratio", 0), reverse=True)
        return alerts


# ═══════════════════════════════════════════════════════════
#  综合扫描器
# ═══════════════════════════════════════════════════════════

class SmartMoneyScanner:
    """一键运行全部5个模块"""

    def __init__(self):
        self.scanner1 = PreAnnounceScanner()
        self.scanner2 = DragonTigerTracker()
        self.scanner3 = BlockTradeMonitor()
        self.scanner4 = InsiderReductionDetector()
        self.scanner5 = MarginAnomalyDetector()

    def run_all(self):
        """
        运行全部模块，返回字典
        """
        results = {}

        st.info("▶ 模块1/5：公告前异动扫描...")
        a1, d1 = self.scanner1.scan()
        results["pre_announce"] = {"alerts": a1, "detail": d1}

        st.info("▶ 模块2/5：龙虎榜席位追踪...")
        a2, s2, r2 = self.scanner2.scan(days=5)
        results["dragon_tiger"] = {"alerts": a2, "summary": s2, "raw": r2}

        st.info("▶ 模块3/5：大宗交易监控...")
        a3, d3, b3 = self.scanner3.scan(days=30)
        results["block_trade"] = {"alerts": a3, "detail": d3, "buyer_stats": b3}

        st.info("▶ 模块4/5：高管精准减持...")
        a4, d4 = self.scanner4.scan()
        results["insider"] = {"alerts": a4, "detail": d4}

        st.info("▶ 模块5/5：融资融券异动...")
        a5s, a5l, d5 = self.scanner5.scan()
        results["margin"] = {"short_alerts": a5s, "long_alerts": a5l, "detail": d5}

        return results
