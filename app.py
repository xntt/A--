import streamlit as st
import pandas as pd
import requests
import json
import re
import traceback

st.set_page_config(page_title="量化交易雷达系统", layout="wide")

# ================= 全局状态与断点续传 =================
if "found_stocks" not in st.session_state: st.session_state.found_stocks = []
if "scan_index" not in st.session_state: st.session_state.scan_index = 0
if "is_scanning" not in st.session_state: st.session_state.is_scanning = False
if "all_stocks" not in st.session_state: st.session_state.all_stocks = []
if "stats" not in st.session_state: st.session_state.stats = {"total": 0, "api_fail": 0, "logic_fail": 0, "success": 0}

# ================= 纯血新浪引擎 1：获取全市场名单 =================
def fetch_all_stock_codes_sina():
    valid_stocks = []
    for page in range(1, 80):
        url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
        params = {"page": str(page), "num": "80", "sort": "symbol", "asc": "1", "node": "hs_a", "symbol": "", "_s_r_a": "init"}
        try:
            res = requests.get(url, params=params, timeout=3)
            text = re.sub(r'([{,])\s*([a-zA-Z_0-9]+)\s*:', r'\1"\2":', res.text)
            data = json.loads(text)
            if not data or not isinstance(data, list) or len(data) == 0: break
            for item in data:
                c = item.get("symbol", "")
                n = item.get("name", "")
                if c and n and not n.startswith("ST") and not n.startswith("*ST"):
                    valid_stocks.append({'code': c[-6:], 'name': n})
        except Exception:
            break
    return valid_stocks

# ================= 纯血新浪引擎 2：获取K线 =================
def fetch_kline_data_sina(stock_code, days=65):
    code_str = str(stock_code).strip().zfill(6)
    prefix = 'sh' if code_str.startswith('6') or code_str.startswith('9') else 'sz'
    symbol = prefix + code_str 
    
    url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {"symbol": symbol, "scale": "240", "ma": "no", "datalen": str(days)}
    try:
        res = requests.get(url, params=params, timeout=3)
        text = re.sub(r'([{,])\s*([a-zA-Z_0-9]+)\s*:', r'\1"\2":', res.text)
        data = json.loads(text)
        if data and isinstance(data, list):
            parsed = []
            for k in data:
                parsed.append({
                    "Date": k.get("day"),
                    "Open": float(k.get("open", 0)),
                    "Close": float(k.get("close", 0)),
                    "Volume": float(k.get("volume", 0))
                })
            return pd.DataFrame(parsed)
    except Exception:
        pass
    return pd.DataFrame()

# ================= 核心指标计算 =================
def calculate_indicators(df):
    if df.empty: return df
    df['MA5'] = df['Close'].rolling(window=5, min_periods=1).mean()
    df['MA10'] = df['Close'].rolling(window=10, min_periods=1).mean()
    df['MA20'] = df['Close'].rolling(window=20, min_periods=1).mean()
    df['MA60'] = df['Close'].rolling(window=60, min_periods=1).mean()
    df['VMA5'] = df['Volume'].rolling(window=5, min_periods=1).mean()
    df['VMA20'] = df['Volume'].rolling(window=20, min_periods=1).mean()
    return df

# ================= 侧边栏导航 =================
st.sidebar.title("⚡ 智能量化交易工作流")
mode = st.sidebar.radio("选择操作阶段：", [
    "🎯 阶段一：全市场海选 (断点续传+全局归类)", 
    "🏆 阶段二：防追高打分与最佳买点计算", 
    "🔍 阶段三：个股形态复诊"
])

try:
    # ================= 阶段一：全市场海选 =================
    if mode == "🎯 阶段一：全市场海选 (断点续传+全局归类)":
        st.title("🎯 全市场潜伏雷达")
        scan_limit = st.slider("选择本次总扫描数量：", 100, 5500, 5000, step=100)
        
        col_btn1, col_btn2, col_btn3 = st.columns(3)
        with col_btn1:
            if st.button("▶️ 开始 / 继续扫描", type="primary"):
                st.session_state.is_scanning = True
                if not st.session_state.all_stocks:
                    with st.spinner("正在从新浪逐页拼接全市场名单..."):
                        st.session_state.all_stocks = fetch_all_stock_codes_sina()
        with col_btn2:
            if st.button("⏸️ 暂停扫描"): st.session_state.is_scanning = False
        with col_btn3:
            if st.button("🔄 重置进度清空数据"):
                st.session_state.is_scanning = False
                st.session_state.scan_index = 0
                st.session_state.found_stocks = []
                st.session_state.stats = {"total": 0, "api_fail": 0, "logic_fail": 0, "success": 0}
                st.session_state.all_stocks = []
                st.rerun()

        col1, col2, col3, col4 = st.columns(4)
        metric_total = col1.empty()
        metric_api_fail = col2.empty()
        metric_logic_fail = col3.empty()
        metric_success = col4.empty()
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        total_target = min(scan_limit, len(st.session_state.all_stocks)) if st.session_state.all_stocks else scan_limit
        curr_total = st.session_state.stats["total"]
        metric_total.metric("已扫描进度", str(curr_total) + " / " + str(total_target))
        metric_api_fail.metric("❌无数据/停牌", st.session_state.stats["api_fail"])
        metric_logic_fail.metric("📉形态不符", st.session_state.stats["logic_fail"])
        metric_success.metric("🎉成功入选", st.session_state.stats["success"])
        if total_target > 0: progress_bar.progress(curr_total / total_target)

        if st.session_state.is_scanning and st.session_state.all_stocks:
            target_stocks = st.session_state.all_stocks[:scan_limit]
            total_target = len(target_stocks)
            
            for i in range(st.session_state.scan_index, total_target):
                if not st.session_state.is_scanning: break 
                
                stock = target_stocks[i]
                code = stock['code']
                name = stock['name']
                hist = fetch_kline_data_sina(code, days=65)
                
                if hist.empty or len(hist) < 2:
                    st.session_state.stats["api_fail"] += 1
                else:
                    df = calculate_indicators(hist)
                    latest = df.iloc[-1]
                    prev1 = df.iloc[-2]
                    
                    matched_shapes = []
                    if latest['MA20'] > latest['MA60'] and abs(latest['Close'] - latest['MA20']) / latest['MA20'] < 0.04 and latest['Volume'] < latest['VMA5'] * 0.9:
                        matched_shapes.append("📉趋势低吸")
                    if latest['Close'] > latest['MA60'] and prev1['Close'] <= prev1['MA60'] and latest['Volume'] > latest['VMA20'] * 1.5:
                        matched_shapes.append("🚀底部启动")
                    if latest['MA5'] > latest['MA10'] > latest['MA20'] > latest['MA60'] and latest['Close'] > latest['MA5']:
                        matched_shapes.append("📈稳健波段")
                    
                    if matched_shapes:
                        st.session_state.stats["success"] += 1
                        st.session_state.found_stocks.append({
                            "股票代码": code, "股票名称": name, 
                            "当前价": round(latest['Close'], 2), "符合形态": " + ".join(matched_shapes)
                        })
                        status_text.success("🔥 最新发现：" + name + " -> " + " + ".join(matched_shapes))
                    else:
                        st.session_state.stats["logic_fail"] += 1

                st.session_state.stats["total"] += 1
                st.session_state.scan_index = i + 1
                
                if i % 10 == 0 or i == total_target - 1:
                    curr_total = st.session_state.stats["total"]
                    metric_total.metric("已扫描进度", str(curr_total) + " / " + str(total_target))
                    metric_api_fail.metric("❌无数据/停牌", st.session_state.stats["api_fail"])
                    metric_logic_fail.metric("📉形态不符", st.session_state.stats["logic_fail"])
                    metric_success.metric("🎉成功入选", st.session_state.stats["success"])
                    progress_bar.progress(curr_total / total_target)

            if st.session_state.scan_index >= total_target:
                st.session_state.is_scanning = False
                status_text.info("✅ 本次扫描任务已全部完成！")
                st.balloons()
                st.rerun()

        if st.session_state.found_stocks:
            st.subheader("🏆 海选入围名单")
            df_result = pd.DataFrame(st.session_state.found_stocks)
            st.dataframe(df_result, use_container_width=True)
            csv_data = df_result.to_csv(index=False).encode('utf-8-sig')
            st.download_button("💾 下载表格 (用于阶段二)", data=csv_data, file_name="全市场归类结果.csv", mime="text/csv")


    # ================= 阶段二：防追高打分与最佳买点计算 =================
    elif mode == "🏆 阶段二：防追高打分与最佳买点计算":
        st.title("🏆 AI 防追高过滤 & 黄金买点测算")
        st.info("💡 剔除暴涨高位股！计算每只股票的最佳潜伏价（MA20附近），并按买入安全性为您排名。")
        
        uploaded_file = st.file_uploader("📂 请上传阶段一生成的表格 (或包含代码列的CSV/Excel)：", type=["csv", "xlsx"])
        
        if uploaded_file is not None:
            df_upload = pd.DataFrame()
            try:
                if uploaded_file.name.endswith('.csv'):
                    try: df_upload = pd.read_csv(uploaded_file, encoding='utf-8', dtype=str)
                    except UnicodeDecodeError: df_upload = pd.read_csv(uploaded_file, encoding='gbk', dtype=str)
                else: df_upload = pd.read_excel(uploaded_file, dtype=str)
                
                code_col = None
                for col in df_upload.columns:
                    if "代码" in col or "code" in col.lower() or "f12" in col:
                        code_col = col; break
                        
                if not code_col: st.error("❌ 找不到包含 '代码' 的列！")
                else:
                    st.success("成功载入 " + str(len(df_upload)) + " 只股票，准备进行防追高诊断！")
                    
                    if st.button("🚀 开始过滤并计算买点", type="primary"):
                        scored_stocks = []
                        progress_bar = st.progress(0)
                        total_upload = len(df_upload)
                        
                        for i, row in df_upload.iterrows():
                            raw_code = str(row[code_col]).strip()
                            clean_code = ''.join(filter(str.isdigit, raw_code))[-6:] 
                            stock_name = row.get('股票名称', row.get('name', '未知'))
                            
                            if len(clean_code) == 6:
                                df = fetch_kline_data_sina(clean_code, days=65)
                                if not df.empty and len(df) >= 30:
                                    df = calculate_indicators(df)
                                    latest = df.iloc[-1]
                                    
                                    # 基础分设定 (满分100)
                                    score = 50 
                                    if latest['MA5'] > latest['MA20']: score += 15 # 短期多头
                                    if latest['MA20'] > latest['MA60']: score += 15 # 中期多头
                                    if latest['Close'] > latest['MA5']: score += 10 # 站上5日线
                                    if latest['Volume'] > latest['VMA5']: score += 10 # 放量
                                    
                                    # 核心计算：乖离率 (距离最佳买点MA20的百分比)
                                    close_price = latest['Close']
                                    ma20_price = latest['MA20']
                                    bias_percent = ((close_price - ma20_price) / ma20_price) * 100
                                    
                                    # 【防追高惩罚机制】
                                    if bias_percent > 8:
                                        score -= 30 # 偏离均线超8%，大概率在山顶，重罚！
                                    elif bias_percent > 5:
                                        score -= 10 # 偏高
                                    elif bias_percent < 0:
                                        score -= 10 # 跌破生命线，形态破坏
                                        
                                    # 判定操作建议
                                    action = ""
                                    if 0 <= bias_percent <= 2.5: action = "⭐⭐⭐ 绝佳潜伏 (紧贴均线)"
                                    elif 2.5 < bias_percent <= 5: action = "⭐⭐ 可轻仓 (稍微偏高)"
                                    elif bias_percent > 5: action = "❌ 极度高估 (切勿追高)"
                                    else: action = "⚠️ 破位风险 (跌破生命线)"
                                    
                                    scored_stocks.append({
                                        "股票代码": clean_code,
                                        "股票名称": stock_name,
                                        "当前价格": round(close_price, 2),
                                        "最佳买入价(MA20)": round(ma20_price, 2),
                                        "距离买点溢价(%)": round(bias_percent, 2),
                                        "AI 综合得分": score,
                                        "操作建议": action
                                    })
                                    
                            progress_bar.progress(int(((i + 1) / total_upload) * 100))
                            
                        if scored_stocks:
                            # 排序逻辑：先挑出及格的(>=70分)，然后按“距离买点百分比”从小到大排！最贴近买点的在最上面！
                            df_scored = pd.DataFrame(scored_stocks)
                            df_good = df_scored[df_scored['AI 综合得分'] >= 70].copy()
                            
                            # 按偏离度绝对值排序（谁最接近0，谁排第一）
                            df_good['偏离度绝对值'] = df_good['距离买点溢价(%)'].abs()
                            df_final = df_good.sort_values(by="偏离度绝对值", ascending=True).drop(columns=['偏离度绝对值'])
                            
                            st.success("✅ 计算完成！已剔除追高风险股。以下是最安全、最接近【黄金买点】的优质标的：")
                            st.dataframe(df_final, use_container_width=True)
            except Exception as e:
                st.error("❌ 处理出错：" + str(e))

    # ================= 阶段三：个股形态复诊 =================
    elif mode == "🔍 阶段三：个股形态复诊":
        st.title("🔍 个股形态复诊 (X光看诊)")
        manual_input = st.text_input("✍️ 请输入要诊断的 6 位代码（如 000001）：")
        if st.button("📊 生成诊断报告", type="primary"):
            target_code = manual_input.strip()
            if not target_code or not target_code.isdigit() or len(target_code) != 6:
                st.warning("⚠️ 请输入正确的6位代码！")
            else:
                with st.spinner("获取K线数据..."):
                    df = fetch_kline_data_sina(target_code, days=120)
                if df.empty:
                    st.error("❌ 获取失败！")
                else:
                    df = calculate_indicators(df)
                    latest = df.iloc[-1]
                    st.subheader(target_code + " 近期走势分析")
                    chart_data = df.set_index('Date')[['Close', 'MA10', 'MA20']]
                    st.line_chart(chart_data)
                    
                    colA, colB, colC = st.columns(3)
                    colA.metric("当前收盘价", round(latest['Close'], 2))
                    colB.metric("20日均线(最佳买点)", round(latest['MA20'], 2))
                    bias = round(((latest['Close'] - latest['MA20'])/latest['MA20'])*100, 2)
                    colC.metric("当前偏离度", str(bias) + "%")

except Exception as e:
    st.error("🚨 运行异常：" + str(e))
    st.code(traceback.format_exc())
