# modules/dragon_tiger_tracker.py
"""
模块2：龙虎榜席位追踪器
核心逻辑：
  1. 抓取每日龙虎榜
  2. 提取营业部席位
  3. 构建席位画像（胜率/偏好/时间/金额）
  4. 知名游资出现时实时预警
  5. 追踪席位后续N日收益
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Tuple
from dataclasses import dataclass, field
import streamlit as st

from data.eastmoney_api import api
from config import FAMOUS_SEATS, SEAT_WIN_RATE_THRESHOLD, SEAT_TRACK_DAYS


@dataclass
class SeatProfile:
    """席位画像"""
    seat_name: str
    alias: str                    # 别名(如"作手新一")
    total_trades: int             # 总交易次数
    win_count: int                # 盈利次数（次日收阳）
    win_rate: float               # 胜率%
    avg_buy_amount: float         # 平均买入额(万)
    avg_next_1d_pct: float        # 平均次日涨幅%
    avg_next_3d_pct: float        # 平均3日涨幅%
    preferred_industries: List[str]  # 偏好行业
    recent_stocks: List[dict]     # 近期操作


@dataclass
class DragonTigerAlert:
    """龙虎榜预警"""
    trade_date: str
    stock_code: str
    stock_name: str
    seat_name: str
    seat_alias: str
    direction: str             # 买入/卖出
    amount: float              # 金额(万)
    change_pct: float          # 当日涨幅
    reason: str                # 上榜原因
    seat_win_rate: float       # 席位历史胜率
    alert_level: str
    detail: str


class DragonTigerTracker:
    """龙虎榜追踪引擎"""

    def __init__(self):
        self.api = api
        # 反向映射：营业部名 → 别名
        self.seat_alias_map = {}
