# app.py

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime

from config import FAMOUS_SEATS
from eastmoney_api import api
from analyzer import (
    PreAnnounceScanner, DragonTigerTracker,
    BlockTradeMonitor, InsiderReductionDetector,
    MarginAnomalyDetector, SmartMoneyScanner,
)

# ══════════ 页面配置 ══════════

st.set_page_config(
    page_title="A股聪明钱检测器",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ══════════ 样式 ══════════

st.markdown(
    "<style>"
    ".acrit{background:#CC0000;color:#fff;padding:10px 14px;"
    "border-radius:6px;margin:4px 0;font-weight:bold;border-left:5px solid #880000;}"
    ".ahigh{background:#DD3333;color:#fff;padding:10px 14px;"
    "border-radius:6px;margin:4px 0;font-weight:bold;border-left:5px solid #AA0000;}"
    ".amid{background:#DD7700;color:#fff;padding:9px 14px;"
    "border-radius:6px;margin:4px 0;border-left:5px solid #AA5500;}"
    ".alow{background:#CCAA00;color:#333;padding:9px 14px;"
    "border-radius:6px;margin:4px 0;border-left:5px solid #998800;}"
    ".mcard{background:#1a1a2e;color:#fff;padding:16px;"
    "border-radius:10px;text-align:center;margin:4px 0;border:1px solid #333;}"
    ".mcard h3{margin:0;font-size:24px;}"
    ".mcard p{margin:4px 0 0 0;font-size:12px;color:#aaa;}"
    ".shdr{background:linear-gradient(90deg,#1a1a2e,#16213e);"
    "color:#00D4FF;padding:8px 16px;border-radius:6px;"
    "font-size:16px;font-weight:bold;margin:16px 0 8px 0;"
    "border-left:4px solid #00D4FF;}"
    "</style>",
    unsafe_allow_html=True,
)


# ══════════ 工具函数 ══════════

def alert_box(text, level="mid"):
    cls = {"critical": "acrit", "high": "ahigh", "mid": "amid", "low": "alow"}
    c = cls.get(level, "amid")
    st.markdown(f'<div class="{c}">{text}</div>', unsafe_allow_html=True)


def metric_box(title, value, sub=""):
    h = f'<div class="mcard"><h3>{value}</h3><p>{title}</p>'
    if sub:
        h += f'<p style="color:#FF8800">{sub}</p>'
    h += '</div>'
    st.markdown(h, unsafe_allow_html=True)


def section(title):
    st.markdown(f'<div class="shdr">{title}</div>', unsafe_allow_html=True)


def emoji(level):
    return {"critical": "🚨", "high": "🔴", "mid": "🟠", "low": "🟡"}.get(level, "ℹ️")


def sv(d, k, default=0):
    v = d.get(k, default)
    if pd.isna(v):
        return default
    return v


# ══════════ 侧边栏 ══════════

with st.sidebar:
    st.title("🔍 A股聪明钱检测器")
    st.caption(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    st.divider()

    page = st.radio("选择模块", [
        "🩺 API诊断",
        "📊 总览仪表盘",
        "📢 公告前异动",
        "🐉 龙虎榜追踪",
        "📦 大宗交易",
        "👔 精准减持",
        "📈 融资融券",
        "🚀 一键全扫描",
    ])

    st.divider()
    st.markdown("**预警等级**")
    st.markdown("🚨 CRITICAL  🔴 HIGH  🟠 MID  🟡 LOW")
    st.divider()
    st.markdown("**监控游资**")
    for a in FAMOUS_SEATS:
        st.markdown(f"• {a}")


# ══════════ 诊断页 ══════════

if page == "🩺 API诊断":
    st.title("🩺 API接口诊断")
    st.markdown("> 逐个测试东方财富数据接口是否可用")

    if st.button("▶ 运行诊断", type="primary", use_container_width=True):
        with st.spinner("测试中..."):
            results = api.run_diagnostics()

        section("诊断结果")
        for name, status in results.items():
            if "✅" in status:
                st.success(f"{name}: {status}")
            else:
                st.error(f"{name}: {status}")

        section("详细日志")
        logs = api.get_debug_log()
        for log in logs:
            if "✅" in log:
                st.text(log)
            elif "⚠️" in log:
                st.warning(log)
            else:
                st.error(log)

        st.info("如果大部分接口显示❌，说明Streamlit Cloud无法访问东方财富（海外IP被拦截），"
                "请尝试部署到国内服务器。")


# ══════════ 总览仪表盘 ══════════

elif page == "📊 总览仪表盘":
    st.title("📊 市场总览仪表盘")

    section("💰 板块资金流向")
    col_type = st.selectbox("板块类型", ["concept", "industry"],
                            format_func=lambda x: "概念板块" if x == "concept" else "行业板块")

    with st.spinner("加载板块资金流..."):
        flow_df = api.get_sector_flow(stype=col_type, size=50)

    if not flow_df.empty and "main_flow" in flow_df.columns:
        flow_df["main_flow"] = pd.to_numeric(flow_df["main_flow"], errors="coerce")
        inflow = flow_df[flow_df["main_flow"] > 0]["main_flow"].sum()
        outflow = flow_df[flow_df["main_flow"] < 0]["main_flow"].sum()

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            metric_box("净流入板块数", f"{(flow_df['main_flow'] > 0).sum()}个")
        with c2:
            metric_box("总净流入", f"{inflow:.1f}亿")
        with c3:
            metric_box
