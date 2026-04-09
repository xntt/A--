# app.py

import streamlit as st
import pandas as pd
from datetime import datetime
from config import FAMOUS_SEATS
from eastmoney_api import api
from analyzer import (
    PreAnnounceScanner, DragonTigerTracker,
    BlockTradeMonitor, InsiderReductionDetector,
    MarginAnomalyDetector, SmartMoneyScanner,
)

st.set_page_config(page_title="A股聪明钱检测器", page_icon="🔍", layout="wide")


def alert_box(text, level="mid"):
    colors = {
        "critical": "background:#CC0000;color:#fff;",
        "high": "background:#DD3333;color:#fff;",
        "mid": "background:#DD7700;color:#fff;",
        "low": "background:#CCAA00;color:#333;",
    }
    s = colors.get(level, colors["mid"])
    st.markdown(
        '<div style="' + s + 'padding:10px;border-radius:6px;margin:4px 0;'
        'font-size:14px;border-left:5px solid #000">' + str(text) + '</div>',
        unsafe_allow_html=True,
    )


def emoji(level):
    return {"critical": "🚨", "high": "🔴", "mid": "🟠", "low": "🟡"}.get(level, "ℹ️")


# ══════ 侧边栏 ══════

with st.sidebar:
    st.title("🔍 聪明钱检测器")
    st.caption(datetime.now().strftime("%Y-%m-%d %H:%M"))
    page = st.radio("模块", [
        "🩺 API诊断",
        "📊 总览",
        "📢 成交量异动",
        "🐉 龙虎榜",
        "📦 大宗交易",
        "👔 精准减持",
        "📈 融资融券",
        "🚀 全扫描",
    ])
    st.divider()
    st.markdown("**监控游资**")
    for a in FAMOUS_SEATS:
        st.text("• " + a)


# ══════ 诊断 ══════

if page == "🩺 API诊断":
    st.title("🩺 API诊断")
    if st.button("运行诊断", type="primary"):
        with st.spinner("测试中..."):
            res = api.run_diagnostics()
        for name, status in res.items():
            if "OK" in str(status):
                st.success(name + ": " + str(status))
            else:
                st.error(name + ": " + str(status))
        st.subheader("详细日志")
        for log in api.get_debug_log():
            st.text(log)


# ══════ 总览 ══════

elif page == "📊 总览":
    st.title("📊 市场总览")

    stype = st.selectbox("板块类型", ["industry", "concept"],
                         format_func=lambda x: "行业" if x == "industry" else "概念")

    with st.spinner("加载中..."):
        flow_df = api.get_sector_flow(stype=stype, size=50)

    if flow_df.empty:
        st.error("板块数据为空，请先运行API诊断")
    else:
        st.success("获取到 " + str(len(flow_df)) + " 个板块")

        if "pct" in flow_df.columns:
            flow_df["pct"] = pd.to_numeric(flow_df["pct"], errors="coerce").fillna(0)
            c1, c2, c3 = st.columns(3)
            c1.metric("上涨板块", str((flow_df["pct"] > 0).sum()) + "个")
            c2.metric("下跌板块", str((flow_df["pct"] < 0).sum()) + "个")
            if len(flow_df) > 0:
                c3.metric("最强板块", str(flow_df.iloc[0].get("board_name", "")))

        st.dataframe(flow_df, use_container_width=True, height=500)

    st.subheader("🔴 涨停池")
    with st.spinner("加载涨停..."):
        lim = api.get_limit_up()
    if lim.empty:
        st.info("暂无涨停数据（可能非交易时间）")
    else:
        st.success("涨停 " + str(len(lim)) + " 只")
        st.dataframe(lim, use_container_width=True, height=400)


# ══════ 成交量异动 ══════

elif page == "📢 成交量异动":
    st.title("📢 成交量异动扫描")
    st.markdown("检测成交量相对20日均量放大2倍以上的股票")

    max_s = st.slider("扫描数量", 10, 50, 20)
    if st.button("开始扫描", type="primary"):
        scanner = PreAnnounceScanner()
        alerts, detail_df = scanner.scan(max_stocks=max_s)
        if alerts:
            st.success("发现 " + str(len(alerts)) + " 个异动")
            for a in alerts:
                e = emoji(a.get("level", "mid"))
                t = (e + " **" + a["name"] + "**(" + a["code"] + ") "
                     + "量比:" + str(a["vol_ratio"]) + "x "
                     + "涨幅:" + str(a["change"]) + "% "
                     + "置信度:" + str(a["confidence"]))
                alert_box(t, a["level"])
            if not detail_df.empty:
                st.subheader("详细数据")
                st.dataframe(detail_df, use_container_width=True)
        else:
            st.info("未发现明显异动")


# ══════ 龙虎榜 ══════

elif page == "🐉 龙虎榜":
    st.title("🐉 龙虎榜追踪")

    if st.button("开始扫描", type="primary"):
        tracker = DragonTigerTracker()
        alerts, summary_df, raw_df = tracker.scan(days=3)

        if alerts:
            st.success("知名游资出手 " + str(len(alerts)) + " 次")
            for a in alerts:
                e = emoji(a.get("level", "mid"))
                t = (e + " **【" + a["alias"] + "】** 买入 "
                     + a["name"] + "(" + a["code"] + ") "
                     + "涨幅:" + str(a["pct"]) + "% "
                     + "日期:" + a["date"])
                alert_box(t, a["level"])
        else:
            st.info("近期未发现知名游资上榜")

        if not raw_df.empty:
            st.subheader("龙虎榜全部明细")
            show_famous = st.checkbox("仅知名游资")
            if show_famous and "is_famous" in raw_df.columns:
                st.dataframe(raw_df[raw_df["is_famous"]], use_container_width=True)
            else:
                st.dataframe(raw_df, use_container_width=True, height=500)
        else:
            st.warning("龙虎榜明细数据为空")


# ══════ 大宗交易 ══════

elif page == "📦 大宗交易":
    st.title("📦 大宗交易监控")

    block_days = st.slider("回溯天数", 7, 60, 30)
    if st.button("开始扫描", type="primary"):
        monitor = BlockTradeMonitor()
        alerts, detail_df, buyer_stats = monitor.scan(days=block_days)

        if alerts:
            st.success("折价套利信号 " + str(len(alerts)) + " 条")
            for a in alerts:
                e = emoji(a.get("level", "mid"))
                t = (e + " **" + str(a.get("name", "")) + "**(" + str(a.get("code", "")) + ") "
                     + "折价:" + str(a.get("discount", 0)) + "% "
                     + "次日涨:" + str(a.get("next1d", 0)) + "% "
                     + "买方:" + str(a.get("buyer", "")) + " "
                     + "日期:" + str(a.get("date", "")))
                alert_box(t, a["level"])
        else:
            st.info("未发现折价套利信号")

        if not detail_df.empty:
            st.subheader("全部大宗交易")
            st.dataframe(detail_df, use_container_width=True, height=500)


# ══════ 精准减持 ══════

elif page == "👔 精准减持":
    st.title("👔 精准减持检测")

    max_s = st.slider("扫描数量", 10, 50, 25)
    if st.button("开始扫描", type="primary"):
        detector = InsiderReductionDetector()
        alerts, detail_df = detector.scan(max_stocks=max_s)

        if alerts:
            st.success("减持信号 " + str(len(alerts)) + " 条")
            for a in alerts:
                e = emoji(a.get("level", "mid"))
                tag = " 🎯精准" if a.get("is_precision") else ""
                t = (e + tag + " **" + a["name"] + "**(" + a["code"] + ") "
                     + "减持人:" + str(a.get("holder", "")) + " "
                     + "减持前涨:" + str(a.get("pre_change", 0)) + "% "
                     + "减持后跌:" + str(a.get("post_drop", 0)) + "%")
                alert_box(t, a["level"])
            if not detail_df.empty:
                st.subheader("详细数据")
                st.dataframe(detail_df, use_container_width=True)
        else:
            st.info("未发现精准减持")


# ══════ 融资融券 ══════

elif page == "📈 融资融券":
    st.title("📈 融资融券异动")

    top_n = st.slider("扫描TOP N", 5, 30, 15)
    if st.button("开始扫描", type="primary"):
        detector = MarginAnomalyDetector()
        short_a, long_a, detail_df = detector.scan(top_n=top_n)

        if short_a:
            st.subheader("🔻 做空预警 " + str(len(short_a)) + " 条")
            for a in short_a:
                e = emoji(a["level"])
                t = (e + " **" + a["name"] + "**(" + a["code"] + ") "
                     + "融券暴增 " + str(a["spike_ratio"]) + "倍")
                alert_box(t, a["level"])
        else:
            st.info("未发现融券异常")

        if long_a:
            st.subheader("🔺 做多信号 " + str(len(long_a)) + " 条")
            for a in long_a:
                e = emoji(a["level"])
                t = (e + " **" + a["name"] + "**(" + a["code"] + ") "
                     + "融资暴增 " + str(a["spike_ratio"]) + "倍")
                alert_box(t, a["level"])
        else:
            st.info("未发现融资异常")

        if not detail_df.empty:
            st.subheader("融资融券原始数据")
            st.dataframe(detail_df, use_container_width=True, height=400)


# ══════ 全扫描 ══════

elif page == "🚀 全扫描":
    st.title("🚀 一键全扫描")
    if st.button("启动", type="primary"):
        scanner = SmartMoneyScanner()
        results = scanner.run_all()
        st.success("扫描完成")

        n1 = len(results.get("m1", {}).get("alerts", []))
        n2 = len(results.get("m2", {}).get("alerts", []))
        n3 = len(results.get("m3", {}).get("alerts", []))
        n4 = len(results.get("m4", {}).get("alerts", []))
        n5s = len(results.get("m5", {}).get("short", []))
        n5l = len(results.get("m5", {}).get("long", []))

        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("量异动", n1)
        c2.metric("游资", n2)
        c3.metric("大宗", n3)
        c4.metric("减持", n4)
        c5.metric("做空", n5s)
        c6.metric("做多", n5l)

        for a in results.get("m1", {}).get("alerts", [])[:5]:
            msg = emoji(a["level"]) + " " + a["name"] + " 量比" + str(a["vol_ratio"]) + "x"
            alert_box(msg, a["level"])

        for a in results.get("m2", {}).get("alerts", [])[:5]:
            msg = emoji(a["level"]) + " 【" + a["alias"] + "】买入 " + a["name"]
            alert_box(msg, a["level"])

        for a in results.get("m3", {}).get("alerts", [])[:5]:
            msg = emoji(a["level"]) + " " + str(a["name"]) + " 折价" + str(a["discount"]) + "% 次日+" + str(a["next1d"]) + "%"
            alert_box(msg, a["level"])

        for a in results.get("m4", {}).get("alerts", [])[:5]:
            msg = emoji(a["level"]) + " " + a["name"] + " 减持后跌" + str(a["post_drop"]) + "%"
            alert_box(msg, a["level"])

        for a in results.get("m5", {}).get("short", [])[:3]:
            msg = emoji(a["level"]) + " " + a["name"] + " 融券暴增" + str(a["spike_ratio"]) + "倍"
            alert_box(msg, a["level"])

        for a in results.get("m5", {}).get("long", [])[:3]:
            msg = emoji(a["level"]) + " " + a["name"] + " 融资暴增" + str(a["spike_ratio"]) + "倍"
            alert_box(msg, a["level"])
