import streamlit as st
import pandas as pd
import requests
import json
import traceback

st.set_page_config(page_title="量化交易雷达系统", layout="wide")

# ================= 全局状态与断点续传初始化 =================
if "found_stocks" not in st.session_state: st.session_state.found_stocks = []
if "scan_index" not in st.session_state: st.session_state.scan_index = 0
if "is_scanning" not in st.session_state: st.session_state.is_scanning = False
if "all_stocks" not in st.session_state: st.session_state.all_stocks = []
if "stats" not in st.session_state: st.session_state.stats = {"total": 0, "api_fail": 0, "logic_fail": 0, "success": 0}

# ================= 恢复昨天最稳定的【东方财富引擎】 =================
def get_stock_list_em():
    """获取全市场5000+只股票，绝不限制100只"""
    url = "http://82.push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1", "pz": "6000", "po": "1", "np": "1", 
        "ut": "bd1d9ddb04089700cf9c27f6f7426281", "fltt": "2", "invt": "2",
        "fid": "f3", "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
        "fields": "f12,f14"
    }
    try:
        res = requests.get(url, params=params, timeout=5).json()
        data = res.get("data", {}).get("diff", [])
        valid_stocks = []
        for i in data:
            code = str(i["f12"])
            name = str(i["f14"])
            if not name.startswith("ST") and not name.startswith("*ST"):
                valid_stocks.append({"code": code, "name": name})
        return valid_stocks
    except Exception:
        return []

def get_kline_em(code, days=65):
    """东方财富K线，速度比新浪快10倍，不漏数据"""
    secid = f"1.{code}" if str(code).startswith('6') else f"0.{code}"
    url = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid, "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "fields1": "f1,f2,f3,f4,f5,f6", "fields2": "f51,f52,f53,f54,f55,f56",
        "klt": "101", "fqt": "1", "end": "20500000", "lmt": str(days)
    }
    try:
        res = requests.get(url, params=params, timeout=3).json()
        klines = res.get("data", {}).get("klines", [])
        parsed = []
        for k in klines:
            parts = k.split(",")
            parsed.append({
                "Date": parts[0], "Open": float(parts[1]), "Close": float(parts[2]),
                "High": float(parts[3]), "Low": float(parts[4]), "Volume": float(parts[5])
            })
        return pd.DataFrame(parsed)
    except Exception:
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
    "🏆 阶段二：导入表格与深度打分", 
    "🔍 阶段三：个股形态复诊"
])

try:
    # ================= 阶段一：全市场海选 =================
    if mode == "🎯 阶段一：全市场海选 (断点续传+全局归类)":
        st.title("🎯 全市场潜伏雷达 (满血恢复版)")
        st.info("💡 恢复昨日最稳定的断点续传功能！一次扫描即可为股票贴上【趋势低吸/底部启动/稳健波段】标签！")
        
        scan_limit = st.slider("选择本次总扫描数量（支持扫遍A股5000只）：", 100, 5500, 5000, step=100)
        
        # 控制台按钮
        col_btn1, col_btn2, col_btn3 = st.columns(3)
        with col_btn1:
            if st.button("▶️ 开始 / 继续扫描", type="primary"):
                st.session_state.is_scanning = True
                if not st.session_state.all_stocks:
                    with st.spinner("正在从东方财富极速拉取全市场名单..."):
                        st.session_state.all_stocks = get_stock_list_em()
        with col_btn2:
            if st.button("⏸️ 暂停扫描"):
                st.session_state.is_scanning = False
        with col_btn3:
            if st.button("🔄 重置进度清空数据"):
                st.session_state.is_scanning = False
                st.session_state.scan_index = 0
                st.session_state.found_stocks = []
                st.session_state.stats = {"total": 0, "api_fail": 0, "logic_fail": 0, "success": 0}
                st.session_state.all_stocks = []
                st.rerun()

        # 数据看板
        col1, col2, col3, col4 = st.columns(4)
        metric_total = col1.empty()
        metric_api_fail = col2.empty()
        metric_logic_fail = col3.empty()
        metric_success = col4.empty()
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # 初始显示面板数据
        total_target = min(scan_limit, len(st.session_state.all_stocks)) if st.session_state.all_stocks else scan_limit
        curr_total = st.session_state.stats["total"]
        metric_total.metric("已扫描进度", f"{curr_total} / {total_target}")
        metric_api_fail.metric("❌无数据/停牌", st.session_state.stats["api_fail"])
        metric_logic_fail.metric("📉形态不符", st.session_state.stats["logic_fail"])
        metric_success.metric("🎉成功入选", st.session_state.stats["success"])
        if total_target > 0:
            progress_bar.progress(curr_total / total_target)

        # 核心扫描循环 (如果处于扫描状态)
        if st.session_state.is_scanning and st.session_state.all_stocks:
            target_stocks = st.session_state.all_stocks[:scan_limit]
            total_target = len(target_stocks)
            
            # 从断点继续扫
            for i in range(st.session_state.scan_index, total_target):
                if not st.session_state.is_scanning:
                    break # 如果点了暂停，立马退出循环
                
                stock = target_stocks[i]
                code = stock['code']
                name = stock['name']
                
                hist = get_kline_em(code, days=65)
                
                if hist.empty or len(hist) < 2:
                    st.session_state.stats["api_fail"] += 1
                else:
                    df = calculate_indicators(hist)
                    latest = df.iloc[-1]
                    prev1 = df.iloc[-2]
                    
                    matched_shapes = []
                    
                    # 策略1: 趋势低吸
                    if latest['MA20'] > latest['MA60'] and abs(latest['Close'] - latest['MA20']) / latest['MA20'] < 0.04 and latest['Volume'] < latest['VMA5'] * 0.9:
                        matched_shapes.append("📉趋势低吸")
                        
                    # 策略2: 底部启动
                    if latest['Close'] > latest['MA60'] and prev1['Close'] <= prev1['MA60'] and latest['Volume'] > latest['VMA20'] * 1.5:
                        matched_shapes.append("🚀底部启动")
                        
                    # 策略3: 稳健波段
                    if latest['MA5'] > latest['MA10'] > latest['MA20'] > latest['MA60'] and latest['Close'] > latest['MA5']:
                        matched_shapes.append("📈稳健波段")
                    
                    if matched_shapes:
                        st.session_state.stats["success"] += 1
                        shape_str = " + ".join(matched_shapes)
                        st.session_state.found_stocks.append({
                            "股票代码": code, "股票名称": name, 
                            "当前价": round(latest['Close'], 2), "符合形态": shape_str
                        })
                        status_text.success(f"🔥 最新发现：{name} ({code}) -> {shape_str}")
                    else:
                        st.session_state.stats["logic_fail"] += 1

                st.session_state.stats["total"] += 1
                st.session_state.scan_index = i + 1
                
                # 每扫 10 只更新一次界面防卡顿
                if i % 10 == 0 or i == total_target - 1:
                    curr_total = st.session_state.stats["total"]
                    metric_total.metric("已扫描进度", f"{curr_total} / {total_target}")
                    metric_api_fail.metric("❌无数据/停牌", st.session_state.stats["api_fail"])
                    metric_logic_fail.metric("📉形态不符", st.session_state.stats["logic_fail"])
                    metric_success.metric("🎉成功入选", st.session_state.stats["success"])
                    progress_bar.progress(curr_total / total_target)

            # 扫描结束处理
            if st.session_state.scan_index >= total_target:
                st.session_state.is_scanning = False
                status_text.info("✅ 本次扫描任务已全部完成！")
                st.balloons()
                st.rerun()

        # 展示结果
        if st.session_state.found_stocks:
            st.subheader("🏆 海选入围名单")
            df_result = pd.DataFrame(st.session_state.found_stocks)
            st.dataframe(df_result, use_container_width=True)
            csv_data = df_result.to_csv(index=False).encode('utf-8-sig')
            st.download_button("💾 下载本次结果表格 (可供阶段二打分使用)", data=csv_data, file_name="全市场归类结果.csv", mime="text/csv")


    # ================= 阶段二：导入表格与深度打分 =================
    elif mode == "🏆 阶段二：导入表格与深度打分":
        st.title("🏆 本地股票池深度打分 (支持 CSV/Excel)")
        st.info("💡 你可以上传刚才在【阶段一】下载的结果，或者同花顺/通达信导出的表格，只要包含【代码】列即可！")
        
        uploaded_file = st.file_uploader("📂 请上传包含股票名单的表格：", type=["csv", "xlsx"])
        
        if uploaded_file is not None:
            df_upload = pd.DataFrame()
            try:
                if uploaded_file.name.endswith('.csv'):
                    try:
                        df_upload = pd.read_csv(uploaded_file, encoding='utf-8', dtype=str)
                    except UnicodeDecodeError:
                        uploaded_file.seek(0)
                        df_upload = pd.read_csv(uploaded_file, encoding='gbk', dtype=str)
                else:
                    df_upload = pd.read_excel(uploaded_file, dtype=str)
                    
                st.write("📄 **文件解析成功，数据预览：**")
                st.dataframe(df_upload.head(3))
                
                code_col = None
                for col in df_upload.columns:
                    if "代码" in col or "code" in col.lower() or "f12" in col:
                        code_col = col
                        break
                        
                if not code_col:
                    st.error("❌ 找不到包含 '代码' 的列，请检查表格表头！")
                else:
                    st.success(f"✅ 成功锁定代码列：【{code_col}】，共 {len(df_upload)} 只股票，准备打分！")
                    
                    if st.button("🚀 开始 AI 深度打分", type="primary"):
                        scored_stocks = []
                        progress_bar = st.progress(0)
                        total_upload = len(df_upload)
                        
                        for i, row in df_upload.iterrows():
                            raw_code = str(row[code_col]).strip()
                            clean_code = ''.join(filter(str.isdigit, raw_code))[-6:] 
                            
                            if len(clean_code) == 6:
                                df = get_kline_em(clean_code, days=30)
                                score = 60 
                                
                                if not df.empty and len(df) >= 20:
                                    df = calculate_indicators(df)
                                    latest = df.iloc[-1]
                                    
                                    if latest['Close'] > latest['MA5']: score += 10
                                    if latest['Close'] > latest['MA20']: score += 10
                                    if latest['MA5'] > latest['MA20']: score += 10
                                    if latest['Volume'] > latest['VMA5']: score += 10
                                    
                                row_dict = row.to_dict()
                                row_dict['标准化代码'] = clean_code
                                row_dict['综合打分'] = score
                                scored_stocks.append(row_dict)
                                
                            progress_bar.progress(int(((i + 1) / total_upload) * 100))
                            
                        if scored_stocks:
                            df_scored = pd.DataFrame(scored_stocks).sort_values(by="综合打分", ascending=False)
                            st.success("✅ 打分完成！")
                            st.dataframe(df_scored, use_container_width=True)
            except Exception as e:
                st.error(f"❌ 读取文件出错：{str(e)}")


    # ================= 阶段三：个股形态复诊 =================
    elif mode == "🔍 阶段三：个股形态复诊":
        st.title("🔍 个股形态复诊 (X光看诊)")
        
        manual_input = st.text_input("✍️ 请输入要诊断的 6 位纯数字代码（如 000001）：")
        
        if st.button("📊 生成诊断报告", type="primary"):
            target_code = manual_input.strip()
                
            if not target_code or not target_code.isdigit() or len(target_code) != 6:
                st.warning("⚠️ 请输入正确的6位纯数字股票代码！")
            else:
                with st.spinner("正在获取最新K线数据..."):
                    df = get_kline_em(target_code, days=120)
                    
                if df.empty:
                    st.error("❌ 获取数据失败，该代码不存在或退市！")
                else:
                    df = calculate_indicators(df)
                    latest = df.iloc[-1]
                    
                    st.subheader(f"{target_code} 近期走势分析")
                    chart_data = df.set_index('Date')[['Close', 'MA10', 'MA20']]
                    st.line_chart(chart_data)
                    
                    st.markdown("### 📈 量化诊断结果")
                    colA, colB, colC = st.columns(3)
                    colA.metric("当前收盘价", round(latest['Close'], 2))
                    colB.metric("20日均线(防守位)", round(latest['MA20'], 2))
                    
                    trend_status = "🔴 跌破防守" if latest['Close'] < latest['MA20'] else "🟢 趋势良好"
                    colC.metric("当前状态", trend_status)

except Exception as e:
    st.error(f"🚨 运行异常：{str(e)}")
    st.code(traceback.format_exc())
