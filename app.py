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

# ═══════════════════════════════════════════════════════════
#  自定义样式
# ═══════════════════════════════════════════════════════════

CSS = """
<style>
.alert-critical {
    background: linear-gradient(135deg, #FF0000 0%, #CC0000 100%);
    color: white; padding: 12px 16px; border-radius: 8px;
    margin: 6px 0; font-weight: bold; font-size: 14px;
    border-left: 5px solid #990000;
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
    background: linear-gradient(135deg, #FFCC00 0%, #DDAA00 100%);
    color: #333; padding: 10px 16px; border-radius: 8px;
    margin: 6px 0; font-size: 13px;
    border-left: 5px solid #AA8800;
}
.metric-card {
    background: #1E1E2E; color: white;
    padding: 20px; border-radius: 12px;
    text-align: center; margin: 5px 0;
    border: 1px solid #333;
}
.metric-card h2 { margin: 0; font-size: 28px; }
.metric-card p { margin: 5px 0 0 0; font-size: 13px; color: #AAA; }
.section-header {
    background: linear-gradient(90deg, #1a1a2e 0%, #16213e 100%);
    color: #00D4FF; padding: 10px 20px; border-radius: 8px;
    font-size: 18px; font-weight: bold; margin: 20px 0 10px 0;
    border-left: 4px solid #00D4FF;
}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════
#  工具函数
# ═══════════════════════════════════════════════════════════

def render_alert(text, level="mid"):
    """渲染预警条"""
    st.markdown(f'<div class="alert-{level}">{text}</div>', unsafe_allow_html=True)


def render_metric(title, value, sub=""):
    """渲染指标卡片"""
    html = f'<div class="metric-card"><h2>{value}</h2><p>{title}</p>'
    if sub:
        html += f'<p style="color:#FF8800;font-size:12px;">{sub}</p>'
    html += '</div>'
    st.markdown(html, unsafe_allow_html=True)


def render_section(title):
    """渲染区块标题"""
    st.markdown(f'<div class="section-header">{title}</div>', unsafe_allow_html=True)


def level_emoji(level):
    """预警等级对应的emoji"""
    m = {"critical": "🚨", "high": "🔴", "mid": "🟠", "low": "🟡"}
    return m.get(level, "ℹ️")


def safe_val(d, key, default=0):
    """安全取值"""
    v = d.get(key, default)
    if pd.isna(v):
        return default
    return v


# ═══════════════════════════════════════════════════════════
#  侧边栏
# ═══════════════════════════════════════════════════════════

with st.sidebar:
    st.title("🔍 A股聪明钱检测器")
    st.caption(f"当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    st.divider()

    page = st.radio("选择模块", [
        "📊 总览仪表盘",
        "📢 模块1: 公告前异动",
        "🐉 模块2: 龙虎榜追踪",
        "📦 模块3: 大宗交易",
        "👔 模块4: 精准减持",
        "📈 模块5: 融资融券",
        "🚀 一键全扫描",
    ])

    st.divider()
    st.markdown("**预警等级说明**")
    st.markdown("🚨 **CRITICAL** — 极高可疑度")
    st.markdown("🔴 **HIGH** — 高度异常")
    st.markdown("🟠 **MID** — 中度异常")
    st.markdown("🟡 **LOW** — 轻度异常")

    st.divider()
    st.markdown("**监控席位**")
    for alias in FAMOUS_SEATS:
        st.markdown(f"• {alias}")


# ═══════════════════════════════════════════════════════════
#  页面: 总览仪表盘
# ═══════════════════════════════════════════════════════════

if page == "📊 总览仪表盘":
    st.title("📊 市场总览仪表盘")

    # 板块资金流
    render_section("💰 板块资金流向 TOP20")
    col_type = st.selectbox("板块类型", ["concept", "industry"],
                            format_func=lambda x: "概念板块" if x == "concept" else "行业板块")

    flow_df = api.get_sector_flow(stype=col_type, size=50)
    if not flow_df.empty:
        # 顶部指标
        c1, c2, c3, c4 = st.columns(4)
        if "main_flow" in flow_df.columns:
            flow_df["main_flow"] = pd.to_numeric(flow_df["main_flow"], errors="coerce")
            inflow = flow_df[flow_df["main_flow"] > 0]["main_flow"].sum()
            outflow = flow_df[flow_df["main_flow"] < 0]["main_flow"].sum()
            top_name = flow_df.iloc[0].get("board_name", "N/A") if len(flow_df) > 0 else "N/A"
            top_flow = flow_df.iloc[0].get("main_flow", 0) if len(flow_df) > 0 else 0

            with c1:
                render_metric("净流入板块数", f"{(flow_df['main_flow']>0).sum()}个")
            with c2:
                render_metric("总净流入", f"{inflow:.1f}亿")
            with c3:
                render_metric("总净流出", f"{outflow:.1f}亿")
            with c4:
                render_metric("最强板块", top_name, f"净流入 {top_flow:.1f}亿")

        # 柱状图
        top20 = flow_df.head(20).copy()
        if "board_name" in top20.columns and "main_flow" in top20.columns:
            top20 = top20.sort_values("main_flow", ascending=True)
            colors = ["#00CC66" if v > 0 else "#CC3333"
                      for v in top20["main_flow"]]

            fig = go.Figure(go.Bar(
                x=top20["main_flow"],
                y=top20["board_name"],
                orientation="h",
                marker_color=colors,
                text=[f"{v:.1f}亿" for v in top20["main_flow"]],
                textposition="outside",
            ))
            fig.update_layout(
                title="板块主力净流入排名（亿元）",
                height=600,
                template="plotly_dark",
                xaxis_title="主力净流入（亿元）",
                yaxis_title="",
                margin=dict(l=150),
            )
            st.plotly_chart(fig, use_container_width=True)

        # 明细表
        with st.expander("📋 查看完整数据"):
            st.dataframe(flow_df, use_container_width=True, height=400)
    else:
        st.warning("板块资金流数据获取失败")

    # 涨停池
    render_section("🔴 今日涨停池")
    limit_df = api.get_limit_up()
    if not limit_df.empty:
        lc1, lc2, lc3 = st.columns(3)
        with lc1:
            render_metric("涨停股数", f"{len(limit_df)}只")
        with lc2:
            if "limit_days" in limit_df.columns:
                limit_df["limit_days"] = pd.to_numeric(limit_df["limit_days"], errors="coerce")
                multi = limit_df[limit_df["limit_days"] >= 2]
                render_metric("连板股数", f"{len(multi)}只")
            else:
                render_metric("连板股数", "N/A")
        with lc3:
            if "first_time" in limit_df.columns:
                render_metric("最早封板", str(limit_df.iloc[0].get("first_time", ""))[:8])
            else:
                render_metric("最早封板", "N/A")

        st.dataframe(limit_df, use_container_width=True, height=400)
    else:
        st.info("暂无涨停数据")


# ═══════════════════════════════════════════════════════════
#  页面: 模块1 — 公告前异动
# ═══════════════════════════════════════════════════════════

elif page == "📢 模块1: 公告前异动":
    st.title("📢 公告前异动扫描")
    st.markdown("> 检测重大公告发布前的成交量/成交额异常放大，识别可能的内幕交易信号")

    with st.form("scan1_form"):
        fc1, fc2 = st.columns(2)
        with fc1:
            days_back = st.slider("回溯天数", 7, 90, 30)
        with fc2:
            max_stocks = st.slider("最大扫描股票数", 10, 100, 30)
        submitted = st.form_submit_button("🔍 开始扫描", use_container_width=True)

    if submitted:
        scanner = PreAnnounceScanner()
        alerts, detail_df = scanner.scan(days_back=days_back, max_stocks=max_stocks)

        if alerts:
            render_section(f"⚠️ 发现 {len(alerts)} 个异动信号")

            for a in alerts:
                emoji = level_emoji(a.get("level", "low"))
                text = (
                    f"{emoji} <b>{a['name']}({a['code']})</b> | "
                    f"公告类型: {a['ann_type']} | "
                    f"异动提前: {a['days_before']}天 | "
                    f"量比: {a['vol_ratio']}x | "
                    f"额比: {a['amt_ratio']}x | "
                    f"公告前涨幅: {a['pre_change']:+.1f}% | "
                    f"置信度: {a['confidence']} | "
                    f"公告: {a['title']}"
                )
                render_alert(text, a.get("level", "low"))

            if not detail_df.empty:
                render_section("📋 详细数据表")
                st.dataframe(detail_df, use_container_width=True, height=400)

                # 散点图：量比 vs 置信度
                if "vol_ratio" in detail_df.columns and "confidence" in detail_df.columns:
                    fig = px.scatter(
                        detail_df, x="vol_ratio", y="confidence",
                        size="amt_ratio",
                        color="level",
                        hover_data=["code", "name", "title"],
                        color_discrete_map={
                            "critical": "#FF0000", "high": "#FF4444",
                            "mid": "#FF8800", "low": "#FFCC00",
                        },
                        title="异动分布：量比 vs 置信度",
                        template="plotly_dark",
                    )
                    fig.update_layout(height=500)
                    st.plotly_chart(fig, use_container_width=True)
        else:
            st.success("✅ 未发现明显异动信号")


# ═══════════════════════════════════════════════════════════
#  页面: 模块2 — 龙虎榜追踪
# ═══════════════════════════════════════════════════════════

elif page == "🐉 模块2: 龙虎榜追踪":
    st.title("🐉 龙虎榜席位追踪")
    st.markdown("> 追踪知名游资营业部买卖记录，计算席位胜率，预警知名游资出手")

    with st.form("scan2_form"):
        scan_days = st.slider("扫描天数", 1, 15, 5)
        submitted = st.form_submit_button("🔍 开始追踪", use_container_width=True)

    if submitted:
        tracker = DragonTigerTracker()
        alerts, summary_df, raw_df = tracker.scan(days=scan_days)

        # 知名游资预警
        if alerts:
            render_section(f"🔥 知名游资出手 — {len(alerts)} 条信号")
            for a in alerts:
                emoji = level_emoji(a.get("level", "mid"))
                buy_wan = safe_val(a, "buy_amt", 0)
                if isinstance(buy_wan, (int, float)):
                    buy_str = f"{buy_wan/10000:.0f}万" if buy_wan > 10000 else f"{buy_wan:.0f}"
                else:
                    buy_str = str(buy_wan)
                text = (
                    f"{emoji} <b>【{a['alias']}】</b> 买入 "
                    f"<b>{a.get('name', '')}({a.get('code', '')})</b> | "
                    f"买入额: {buy_str} | "
                    f"当日涨幅: {safe_val(a, 'pct', 0):+.1f}% | "
                    f"日期: {a.get('date', '')} | "
                    f"上榜原因: {a.get('reason', '')}"
                )
                render_alert(text, a.get("level", "mid"))
        else:
            st.info("近期未发现知名游资席位上榜")

        # 席位统计
        if not summary_df.empty:
            render_section("📊 席位胜率统计")
            st.dataframe(summary_df, use_container_width=True, height=400)

        # 原始数据
        if not raw_df.empty:
            render_section("📋 龙虎榜原始明细")
            famous_only = st.checkbox("仅显示知名游资", value=False)
            if famous_only and "is_famous" in raw_df.columns:
                display_df = raw_df[raw_df["is_famous"] == True]
            else:
                display_df = raw_df
            st.dataframe(display_df, use_container_width=True, height=400)


# ═══════════════════════════════════════════════════════════
#  页面: 模块3 — 大宗交易
# ═══════════════════════════════════════════════════════════

elif page == "📦 模块3: 大宗交易":
    st.title("📦 大宗交易折价监控")
    st.markdown("> 检测大宗交易折价买入后次日拉升的异常模式，识别内幕关联交易")

    with st.form("scan3_form"):
        block_days = st.slider("回溯天数", 7, 90, 30)
        submitted = st.form_submit_button("🔍 开始扫描", use_container_width=True)

    if submitted:
        monitor = BlockTradeMonitor()
        alerts, detail_df, buyer_stats = monitor.scan(days=block_days)

        if alerts:
            render_section(f"⚠️ 折价接盘+次日拉升 — {len(alerts)} 条信号")
            for a in alerts:
                emoji = level_emoji(a.get("level", "mid"))
                text = (
                    f"{emoji} <b>{a.get('name', '')}({a.get('code', '')})</b> | "
                    f"折价: {safe_val(a, 'discount', 0):.1f}% | "
                    f"金额: {safe_val(a, 'deal_wan', 0):.0f}万 | "
                    f"次日涨: {safe_val(a, 'next1d', 0):+.1f}% | "
                    f"5日涨: {safe_val(a, 'next5d', 0):+.1f}% | "
                    f"买方: {a.get('buyer', '')} | "
                    f"日期: {a.get('date', '')}"
                )
                render_alert(text, a.get("level", "mid"))
        else:
            st.success("✅ 未发现明显折价套利信号")

        # 折价 vs 次日涨幅散点图
        if not detail_df.empty:
            render_section("📊 折价率 vs 次日涨幅")
            plot_df = detail_df.copy()
            for c in ["premium_pct", "next1d"]:
                if c in plot_df.columns:
                    plot_df[c] = pd.to_numeric(plot_df[c], errors="coerce")

            if "premium_pct" in plot_df.columns and "next1d" in plot_df.columns:
                plot_df = plot_df.dropna(subset=["premium_pct", "next1d"])
                if not plot_df.empty:
                    fig = px.scatter(
                        plot_df, x="premium_pct", y="next1d",
                        hover_data=["code", "name"] if "code" in plot_df.columns else None,
                        title="折价率 vs 次日涨幅（左下角=折价接盘+次日涨）",
                        template="plotly_dark",
                    )
                    fig.add_hline(y=0, line_dash="dash", line_color="gray")
                    fig.add_vline(x=0, line_dash="dash", line_color="gray")
                    fig.update_layout(height=500)
                    st.plotly_chart(fig, use_container_width=True)

        # 买方统计
        if not buyer_stats.empty:
            render_section("🏢 高频折价接盘方排名")
            st.dataframe(buyer_stats, use_container_width=True, height=300)

        # 原始数据
        if not detail_df.empty:
            with st.expander("📋 查看全部大宗交易数据"):
                st.dataframe(detail_df, use_container_width=True, height=400)


# ═══════════════════════════════════════════════════════════
#  页面: 模块4 — 精准减持
# ═══════════════════════════════════════════════════════════

elif page == "👔 模块4: 精准减持":
    st.title("👔 高管精准减持检测")
    st.markdown("> 检测大股东/高管减持后股价暴跌的精准减持行为")

    with st.form("scan4_form"):
        max_s = st.slider("最大扫描数", 10, 100, 40)
        submitted = st.form_submit_button("🔍 开始扫描", use_container_width=True)

    if submitted:
        detector = InsiderReductionDetector()
        alerts, detail_df = detector.scan(max_stocks=max_s)

        if alerts:
            render_section(f"⚠️ 精准减持信号 — {len(alerts)} 条")
            for a in alerts:
                emoji = level_emoji(a.get("level", "mid"))
                precision_tag = " 🎯精准减持" if a.get("is_precision") else ""
                text = (
                    f"{emoji}{precision_tag} <b>{a.get('name', '')}({a.get('code', '')})</b> | "
                    f"减持人: {a.get('holder', '')} | "
                    f"减持前涨: {safe_val(a, 'pre_change', 0):+.1f}% | "
                    f"减持后最大跌: {safe_val(a, 'post_drop', 0):.1f}% | "
                    f"减持后累计: {safe_val(a, 'post_total', 0):+.1f}% | "
                    f"截止日: {a.get('end_date', '')}"
                )
                render_alert(text, a.get("level", "mid"))

            if not detail_df.empty:
                render_section("📋 详细数据")

                # 减持前涨幅 vs 减持后跌幅图
                if "pre_change" in detail_df.columns and "post_drop" in detail_df.columns:
                    detail_df["pre_change"] = pd.to_numeric(detail_df["pre_change"], errors="coerce")
                    detail_df["post_drop"] = pd.to_numeric(detail_df["post_drop"], errors="coerce")
                    plot_df = detail_df.dropna(subset=["pre_change", "post_drop"])
                    if not plot_df.empty:
                        fig = px.scatter(
                            plot_df, x="pre_change", y="post_drop",
                            color="level",
                            hover_data=["code", "name", "holder"],
                            color_discrete_map={
                                "critical": "#FF0000", "high": "#FF4444",
                                "mid": "#FF8800", "low": "#FFCC00",
                            },
                            title="减持前涨幅 vs 减持后跌幅（右下角=精准减持）",
                            template="plotly_dark",
                        )
                        fig.update_layout(height=500)
                        st.plotly_chart(fig, use_container_width=True)

                st.dataframe(detail_df, use_container_width=True, height=400)
        else:
            st.success("✅ 未发现明显精准减持信号")


# ═══════════════════════════════════════════════════════════
#  页面: 模块5 — 融资融券
# ═══════════════════════════════════════════════════════════

elif page == "📈 模块5: 融资融券":
    st.title("📈 融资融券异动检测")
    st.markdown("> 检测融券卖出暴增（做空预警）和融资买入暴增（做多信号）")

    with st.form("scan5_form"):
        top_n = st.slider("扫描TOP N股票", 10, 100, 50)
        submitted = st.form_submit_button("🔍 开始扫描", use_container_width=True)

    if submitted:
        detector = MarginAnomalyDetector()
        short_alerts, long_alerts, detail_df = detector.scan(top_n=top_n)

        # 做空预警
        if short_alerts:
            render_section(f"🔻 融券做空预警 — {len(short_alerts)} 条")
            for a in short_alerts:
                emoji = level_emoji(a.get("level", "mid"))
                text = (
                    f"{emoji} <b>{a.get('name', '')}({a.get('code', '')})</b> | "
                    f"融券卖出量: 今日 vs 均值 = <b>{safe_val(a, 'spike_ratio', 0):.1f}倍</b> | "
                    f"股价变动: {safe_val(a, 'price_chg', 0):+.1f}% | "
                    f"信号: {a.get('signal', '')}"
                )
                render_alert(text, a.get("level", "mid"))
        else:
            st.info("未发现融券异常做空信号")

        # 做多信号
        if long_alerts:
            render_section(f"🔺 融资做多信号 — {len(long_alerts)} 条")
            for a in long_alerts:
                emoji = level_emoji(a.get("level", "mid"))
                text = (
                    f"{emoji} <b>{a.get('name', '')}({a.get('code', '')})</b> | "
                    f"融资买入额: 今日 vs 均值 = <b>{safe_val(a, 'spike_ratio', 0):.1f}倍</b> | "
                    f"股价变动: {safe_val(a, 'price_chg', 0):+.1f}% | "
                    f"信号: {a.get('signal', '')}"
                )
                render_alert(text, a.get("level", "mid"))
        else:
            st.info("未发现融资异常做多信号")

        # 综合数据
        if not detail_df.empty:
            render_section("📋 融资融券明细数据")
            st.dataframe(detail_df, use_container_width=True, height=400)


# ═══════════════════════════════════════════════════════════
#  页面: 一键全扫描
# ═══════════════════════════════════════════════════════════

elif page == "🚀 一键全扫描":
    st.title("🚀 一键全市场扫描")
    st.markdown("> 同时运行全部5个检测模块，生成综合预警报告")

    if st.button("⚡ 启动全扫描", use_container_width=True, type="primary"):

        scanner = SmartMoneyScanner()
        results = scanner.run_all()

        st.success("✅ 全部模块扫描完成！")

        # ---- 汇总统计 ----
        render_section("📊 扫描结果汇总")
        n1 = len(results.get("pre_announce", {}).get("alerts", []))
        n2 = len(results.get("dragon_tiger", {}).get("alerts", []))
        n3 = len(results.get("block_trade", {}).get("alerts", []))
        n4 = len(results.get("insider", {}).get("alerts", []))
        n5s = len(results.get("margin", {}).get("short_alerts", []))
        n5l = len(results.get("margin", {}).get("long_alerts", []))
        total = n1 + n2 + n3 + n4 + n5s + n5l

        mc1, mc2, mc3, mc4, mc5, mc6 = st.columns(6)
        with mc1:
            render_metric("总预警数", str(total))
        with mc2:
            render_metric("公告异动", str(n1))
        with mc3:
            render_metric("游资出手", str(n2))
        with mc4:
            render_metric("大宗异常", str(n3))
        with mc5:
            render_metric("精准减持", str(n4))
        with mc6:
            render_metric("融券做空", str(n5s), f"融资做多: {n5l}")

        # ---- 模块1结果 ----
        a1 = results.get("pre_announce", {}).get("alerts", [])
        if a1:
            render_section(f"📢 公告前异动 ({n1}条)")
            for a in a1[:10]:
                emoji = level_emoji(a.get("level", "low"))
                text = (
                    f"{emoji} <b>{a.get('name', '')}({a.get('code', '')})</b> "
                    f"量比{a.get('vol_ratio', 0)}x "
                    f"提前{a.get('days_before', 0)}天 "
                    f"置信度{a.get('confidence', 0)} | "
                    f"{a.get('title', '')}"
                )
                render
