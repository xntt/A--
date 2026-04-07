# app.py
"""Streamlit 主看板 — A股聪明钱检测器"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime

from config import COLORS, FAMOUS_SEATS
from eastmoney_api import api
from analyzer import (
    PreAnnounceScanner,
    DragonTigerTracker,
    BlockTradeMonitor,
    InsiderReductionDetector,
    MarginAnomalyDetector,
    SmartMoneyScanner,
)

# ═══════════════════════════════════════════════════════════
#  页面配置
# ═══════════════════════════════════════════════════════════

st.set_page_config(
    page_title="A股聪明钱检测器",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 自定义CSS
st.markdown("""
<style>
    .alert-critical {
        background: linear-gradient(135deg, #FF0000 0%, #CC0000 100%);
        color: white; padding: 12px 16px; border-radius: 8px;
        margin: 6px 0; font-weight: bold; font-size: 14px;
        border-left: 5px solid #990000;
        animation: pulse 2s infinite;
    }
    .alert-high {
        background: linear-gradient(135deg, #FF4444 0%, #CC3333 100%);
        color: white; padding: 12px 16px; border-radius: 8px;
        margin: 6px 0; font-weight: bold; font-size: 14px;
        border-left: 5px solid #AA0000;
    }
    .alert-mid {
        background: linear-gradient(135deg, #FF8800 0%, #DD6600 100%);
        color: white; padding: 10px 16px; border-radius: 8px;
        margin: 6px 0; font-size: 13px;
        border-left: 5px solid #AA5500;
    }
    .alert-low {
        background: linear-gradient(135deg, #FFCC00 0%, #DDAA00
