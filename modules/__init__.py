# modules/pre_announce_scanner.py
"""
模块1：公告前异动扫描器
核心逻辑：
  1. 抓取近期重大公告列表
  2. 回溯公告前5个交易日的成交量/成交额
  3. 与前20日均值对比
  4. 异常倍数超阈值 → 生成预警
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Tuple
from dataclasses import dataclass, field
import streamlit as st

from data.eastmoney_api import api
from config import (
    VOLUME_ANOMALY_RATIO, AMOUNT_ANOMALY_RATIO,
    PRE_ANNOUNCE_WINDOW, BASELINE_WINDOW,
    ANNOUNCE_KEYWORDS_POSITIVE, ANNOUNCE_KEYWORDS_NEGATIVE
)


@dataclass
class PreAnnounceAlert:
    """公告前异动预警"""
    stock_code: str
    stock_name: str
    ann_date: str              # 公告日期
    ann_title: str             # 公告标题
    ann_type: str              # 利好/利空
    anomaly_date: str          # 异动日期
    days_before_ann: int       # 异动发生在公告前几天
    volume_ratio: float        # 成交量倍数
    amount_ratio: float        # 成交额倍数
    price_change_before: float # 公告前累计涨幅
    alert_level: str           # critical/high/mid/low
    detail: str
    confidence: float          # 置信度 0~1


class PreAnnounceScanner:
    """公告前异动扫描引擎"""

    def __init__(self):
        self.api = api

    def scan(self, days_back: int = 30, max_stocks: int = 50) -> Tuple[List[PreAnnounceAlert], pd.DataFrame]:
        """
        全流程扫描
        1. 获取近期公告
        2. 筛选重大公告
        3. 回溯K线检测异动
        """
        alerts = []
        detail_rows = []

        # 获取公告
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        ann_df = self.api.get_announcements(start_date=start_date, end_date=end_date)

        if ann_df.empty:
            return alerts, pd.DataFrame()

        # 筛选重大公告（含关键词）
        major_anns = self._filter_major_announcements(ann_df)

        if major_anns.empty:
            return alerts, pd.DataFrame()

        # 去重：同一股票取最近一次公告
        major_anns = major_anns.drop_duplicates(subset=["stock_code"], keep="first")
        major_anns = major_anns.head(max_stocks)

        progress = st.progress(0, text="扫描公告前异动...")
        total = len(major_anns)

        for idx, (_, ann_row) in enumerate(major_anns.iterrows()):
            progress.progress((idx + 1) / total, text=f"扫描 {ann_row.get('stock_name', '')}...")

            stock_code = ann_row.get("stock_code", "")
            if not stock_code or len(stock_code) != 6:
                continue

            result = self._check_single_stock(ann_row)
            if result:
                alerts.append(result["alert"])
                detail_rows.append(result["detail_row"])

        progress.empty()

        # 按置信度排序
        alerts.sort(key=lambda x: x.confidence, reverse=True)

        detail_df = pd.DataFrame(detail_rows) if detail_rows else pd.DataFrame()
        return alerts, detail_df

    def _filter_major_announcements(self, ann_df: pd.DataFrame) -> pd.DataFrame:
        """筛选含关键词的重大公告"""
        all_keywords = ANNOUNCE_KEYWORDS_POSITIVE + ANNOUNCE_KEYWORDS_NEGATIVE

        mask = ann_df["title"].apply(
            lambda t: any(kw in str(t) for kw in all_keywords) if pd.notna(t) else False
        )
        return ann_df[mask].copy()

    def _classify_announcement(self, title: str) -> str:
        """判断公告是利好还是利空"""
        title = str(title)
        for kw in ANNOUNCE_KEYWORDS_POSITIVE:
            if kw in title:
                return "利好"
        for kw in ANNOUNCE_KEYWORDS_NEGATIVE:
            if kw in title:
                return "利空"
        return "中性"

    def _check_single_stock(self, ann_row: dict) -> dict:
        """检查单只股票公告前是否有异动"""
        stock_code = ann_row.get("stock_code", "")
        stock_name = ann_row.get("stock_name", "")
        ann_date = ann_row.get("ann_date", "")
        ann_title = ann_row.get("title", "")
        ann_type = self._classify_announcement(ann_title)

        # 获取K线数据（公告前60日）
        kline = self.api.get_stock_kline(stock_code, days=60)
        if kline.empty or len(kline) < BASELINE_WINDOW + PRE_ANNOUNCE_WINDOW:
            return None

        # 定位公告日期在K线中的位置
        kline["date_str"] = kline["date"].dt.strftime("%Y-%m-%d")
        ann_date_clean = str(ann_date)[:10]

        # 找到公告日或之后最近的交易日
        ann_idx = None
        for i, row in kline.iterrows():
            if row["date_str"] >= ann_date_clean:
                ann_idx = i
                break

        if ann_idx is None:
            ann_idx = len(kline) - 1

        # 基准窗口：公告前 BASELINE_WINDOW+PRE_ANNOUNCE_WINDOW 到 公告前 PRE_ANNOUNCE_WINDOW
        baseline_end = ann_idx - PRE_ANNOUNCE_WINDOW
        baseline_start = baseline_end - BASELINE_WINDOW

        if baseline_start < 0:
            return None

        baseline = kline.iloc[baseline_start:baseline_end]
        pre_window = kline.iloc[baseline_end:ann_idx]

        if baseline.empty or pre_window.empty:
            return None

        # 计算基准均值
        avg_volume = baseline["volume"].mean()
        avg_amount = baseline["amount"].mean()

        if avg_volume == 0 or avg_amount == 0:
            return None

        # 检测异动窗口内每日的倍数
        max_vol_ratio = 0
        max_amt_ratio = 0
        anomaly_date = ""
        days_before = 0

        for i, (_, row) in enumerate(pre_window.iterrows()):
            vol_ratio = row["volume"] / avg_volume if avg_volume > 0 else 0
            amt_ratio = row["amount"] / avg_amount if avg_amount > 0 else 0

            if vol_ratio > max_vol_ratio:
                max_vol_ratio = vol_ratio
                max_amt_ratio = amt_ratio
                anomaly_date = row["date_str"]
                days_before = ann_idx - baseline_end - i

        # 判断是否触发预警
        is_volume_anomaly = max_vol_ratio >= VOLUME_ANOMALY_RATIO
        is_amount_anomaly = max_amt_ratio >= AMOUNT_ANOMALY_RATIO

        if not (is_volume_anomaly or is_amount_anomaly):
            return None

        # 计算公告前累计涨幅
        price_before = pre_window.iloc[0]["open"]
        price_after = pre_window.iloc[-1]["close"]
        price_change = (price_after - price_before) / price_before * 100 if price_before > 0 else 0

        # 计算置信度
        confidence = self._calc_confidence(
            max_vol_ratio, max_amt_ratio, price_change, ann_type, days_before
        )

        # 预警等级
        if confidence >= 0.8:
            level = "critical"
        elif confidence >= 0.6:
            level = "high"
        elif confidence >= 0.4:
            level = "mid"
        else:
            level = "low"

        detail = (
            f"{'🚨' if level == 'critical' else '⚠️'} {stock_name}({stock_code}) "
            f"在{ann_type}公告前{days_before}日出现异动 | "
            f"成交量达{max_vol_ratio:.1f}倍均值 | "
            f"成交额达{max_amt_ratio:.1f}倍均值 | "
            f"公告前累涨{price_change:+.1f}% | "
            f"公告: {ann_title[:30]}"
        )

        alert = PreAnnounceAlert(
            stock_code=stock_code,
            stock_name=stock_name,
            ann_date=ann_date_clean,
            ann_title=ann_title,
            ann_type=ann_type,
            anomaly_date=anomaly_date,
            days_before_ann=days_before,
            volume_ratio=round(max_vol_ratio, 2),
            amount_ratio=round(max_amt_ratio, 2),
            price_change_before=round(price_change, 2),
            alert_level=level,
            detail=detail,
            confidence=round(confidence, 3),
        )

        detail_row = {
            "股票代码": stock_code,
            "股票名称": stock_name,
            "公告日期": ann_date_clean,
            "公告类型": ann_type,
            "公告标题": ann_title[:40],
            "异动日期": anomaly_date,
            "提前天数": days_before,
            "量比(倍)": round(max_vol_ratio, 1),
            "额比(倍)": round(max_amt_ratio, 1),
            "公告前涨幅%": round(price_change, 1),
            "置信度": round(confidence, 2),
            "预警等级": level,
        }

        return {"alert": alert, "detail_row": detail_row}

    def _calc_confidence(self, vol_ratio: float, amt_ratio: float,
                          price_change: float, ann_type: str,
                          days_before: int) -> float:
        """
        计算异动置信度
        综合考虑: 量比 + 额比 + 涨幅方向与公告类型一致性 + 提前天数
        """
        score = 0.0

        # 量比贡献 (0~0.3)
        score += min(vol_ratio / 10.0, 0.3)

        # 额比贡献 (0~0.2)
        score += min(amt_ratio / 10.0, 0.2)

        # 方向一致性 (0~0.3)
        if ann_type == "利好" and price_change > 3:
            score += 0.3
        elif ann_type == "利好" and price_change > 0:
            score += 0.15
        elif ann_type == "利空" and price_change < -3:
            score += 0.3
        elif ann_type == "利空" and price_change < 0:
            score += 0.15

        # 提前天数 (0~0.2) 越提前越可疑
        if 1 <= days_before <= 3:
            score += 0.2
        elif days_before <= 5:
            score += 0.1

        return min(score, 1.0)
