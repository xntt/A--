import streamlit as st
import pandas as pd
import requests
from datetime import datetime
import re
import json
import traceback

# 必须放在第一行：页面配置
st.set_page_config(page_title="量化交易雷达系统", layout="wide")

# ================= 全局防崩溃外壳 =================
try:
    # 1. 状态初始化
    if "found_stocks" not in st.session_state:
        st.session_state.found_stocks = []
    if "current_strategy" not in st.session_state:
        st.session_state.current_strategy = "尚未选择"

    # ================= 纯血新浪引擎 1：获取全市场股票名单 =================
    def fetch_all_stock_codes():
        url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
        params = {"page": "1", "num": "6000", "sort": "symbol", "asc": "1", "node": "hs_a", "symbol": "", "_s_r_a": "init"}
        try:
            res = requests.get(url, params=params, timeout=5)
            text = re.sub(r'([{,])\s*([a-zA-Z_0-9]+)\s*:', r'\1"\2":', res.text)
            data = json.loads(text)
            valid_stocks = []
            if isinstance(data, list):
                for item in data:
                    c = item.get("symbol", "")
                    n = item.get("name", "")
                    if c and n and not n.startswith("ST") and not n.startswith("*ST"):
                        valid_stocks.append({'f12': c[-6:], 'f14': n})
            return valid_stocks
        except Exception:
            return []

    # ================= 纯血新浪引擎 2：获取单只股票K线 =================
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
        "🎯 阶段一：全市场海选 (粗筛)", 
        "🏆 阶段二：导入表格与深度打分", 
        "🔍 阶段三：个股形态复诊"
    ])

    # ================= 阶段一：全市场海选 =================
    if mode == "🎯 阶段一：全市场海选 (粗筛)":
        st.title("🎯 全市场潜伏雷达 (安全稳定版)")
        strategy = st.radio("选择策略：", ["趋势低吸", "底部启动", "稳健波段"])
        scan_limit = st.slider("扫描数量（取消多线程，建议先少扫一点测试）：", 50, 2000, 100, step=50)
        
        if st.button("🚀 启动安全扫描", type="primary"):
            st.session_state.current_strategy = strategy
            st.session_state.found_stocks = [] 
            
            with st.spinner("正在从新浪获取全市场名单..."):
                all_stocks = fetch_all_stock_codes()
                
            if not all_stocks:
                st.error("🚨 致命错误：获取名单失败，请检查网络！")
                st.stop()
            else:
                st.success(f"✅ 成功获取到 {len(all_stocks)} 只股票名单！开始稳定逐个扫描...")

            col1, col2, col3, col4 = st.columns(4)
            count_total = col1.metric("已扫描", "0")
            count_api_fail = col2.metric("❌无数据", "0")
            count_logic_fail = col3.metric("📉形态不符", "0")
            count_success = col4.metric("🎉成功入选", "0")
            
            progress_bar = st.progress(0)
            found_list = []
            stats = {"total": 0, "api_fail": 0, "logic_fail": 0, "success": 0}
            test_stocks = all_stocks[:scan_limit] 
            test_total = len(test_stocks)
            
            # 【核心修改】：彻底剔除多线程，改为最原始但100%安全的单步 for 循环
            for count, stock_info in enumerate(test_stocks, 1):
                code = stock_info['f12']
                name = stock_info['f14']
                
                hist = fetch_kline_data_sina(code, days=65) 
                
                if hist.empty or len(hist) < 2: 
                    stats["api_fail"] += 1
                else:
                    df = calculate_indicators(hist)
                    latest = df.iloc[-1]
                    prev1 = df.iloc[-2]
                    is_match = False
                    
                    try:
                        if "趋势低吸" in strategy and (latest['MA20'] > latest['MA60'] and abs(latest['Close'] - latest['MA20']) / latest['MA20'] < 0.02 and latest['Volume'] < latest['VMA5'] * 0.7): is_match = True
                        elif "底部启动" in strategy and (latest['Close'] > latest['MA60'] and prev1['Close'] <= prev1['MA60'] and latest['Volume'] > latest['VMA20'] * 2.5): is_match = True
                        elif "稳健波段" in strategy and (latest['MA5'] > latest['MA10'] > latest['MA20'] > latest['MA60'] and latest['Close'] > latest['MA5'] and latest['Volume'] > latest['VMA5']): is_match = True
                    except Exception:
                        pass
                    
                    if is_match:
                        stats["success"] += 1
                        found_list.append({"股票代码": code, "股票名称": name, "当前价": round(latest['Close'], 2), "逻辑": strategy})
                    else:
                        stats["logic_fail"] += 1

                stats["total"] += 1
                
                # 更新UI
                if count % 2 == 0 or count == test_total:
                    progress_bar.progress(int((count / test_total) * 100))
                    count_total.metric("已扫描", f"{stats['total']} / {test_total}")
                    count_api_fail.metric("❌无数据", stats['api_fail'])
                    count_logic_fail.metric("📉形态不符", stats['logic_fail'])
                    count_success.metric("🎉成功入选", stats['success'])
            
            st.session_state.found_stocks = found_list
            if found_list:
                st.balloons()
                df_result = pd.DataFrame(found_list)
                st.dataframe(df_result, use_container_width=True)
                csv_data = df_result.to_csv(index=False).encode('utf-8-sig')
                st.download_button("💾 下载海选结果", data=csv_data, file_name="海选结果.csv", mime="text/csv")
            else:
                st.warning("⚠️ 扫描结束，当前批次没有符合该策略的股票。")

    # ================= 阶段二：导入表格与深度打分 =================
    elif mode == "🏆 阶段二：导入表格与深度打分":
        st.title("🏆 本地股票池深度打分 (支持 CSV/Excel)")
        st.info("💡 无论是在【阶段一】下载的结果，还是同花顺/通达信导出的表格，只要包含【代码】列即可识别。")
        
        uploaded_file = st.file_uploader("📂 请上传包含股票名单的表格文件：", type=["csv", "xlsx"])
        
        if uploaded_file is not None:
            df_upload = pd.DataFrame()
            try:
                if uploaded_file.name.endswith('.csv'):
                    # 【核心修改】：防止同花顺导出的GBK格式CSV引发崩溃白屏
                    try:
                        df_upload = pd.read_csv(uploaded_file, encoding='utf-8', dtype=str)
                    except UnicodeDecodeError:
                        uploaded_file.seek(0)
                        df_upload = pd.read_csv(uploaded_file, encoding='gbk', dtype=str)
                else:
                    df_upload = pd.read_excel(uploaded_file, dtype=str)
                    
                st.write("📄 **上传的文件预览：**")
                st.dataframe(df_upload.head(3))
                
                code_col = None
                for col in df_upload.columns:
                    if "代码" in col or "code" in col.lower() or "f12" in col:
                        code_col = col
                        break
                        
                if not code_col:
                    st.error("❌ 解析失败：找不到包含 '代码' 或 'code' 的列头！请修改表头后重新上传。")
                else:
                    st.success(f"✅ 成功识别代码列：【{code_col}】，共 {len(df_upload)} 只股票！")
                    
                    if st.button("🚀 开始对上传文件进行 AI 深度打分", type="primary"):
                        scored_stocks = []
                        progress_bar = st.progress(0)
                        total_upload = len(df_upload)
                        
                        for i, row in df_upload.iterrows():
                            raw_code = str(row[code_col]).strip()
                            clean_code = ''.join(filter(str.isdigit, raw_code))[-6:] 
                            
                            if len(clean_code) == 6:
                                df = fetch_kline_data_sina(clean_code, days=30)
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
                        else:
                            st.warning("⚠️ 打分失败，可能未能成功提取有效代码。")
            except Exception as e:
                st.error(f"❌ 读取文件出错：{str(e)}。这可能是因为你的 Excel 缺少支持库，建议先另存为 CSV 格式再上传！")

    # ================= 阶段三：个股形态复诊 =================
    elif mode == "🔍 阶段三：个股形态复诊":
        st.title("🔍 个股形态复诊 (X光看诊)")
        
        manual_input = st.text_input("✍️ 请输入要诊断的 6 位纯数字代码（如 000001）：")
        
        if st.button("📊 生成诊断报告", type="primary"):
            target_code = manual_input.strip()
                
            if not target_code or not target_code.isdigit() or len(target_code) != 6:
                st.warning("⚠️ 请输入正确的6位纯数字股票代码！")
            else:
                with st.spinner("正在获取新浪K线数据..."):
                    df = fetch_kline_data_sina(target_code, days=120)
                    
                if df.empty:
                    st.error("❌ 获取数据失败，该代码不存在或新浪接口暂无数据！")
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
                    
                    st.info("📝 **AI 提示：** 蓝线为收盘价，只要收盘价在MA20（均线）之上，说明处于多头行情。")

# 如果系统层面发生严重异常，捕捉它并在页面显示，绝不白屏
except Exception as e:
    st.error(f"🚨 界面渲染崩溃，出现严重错误：{str(e)}")
    st.code(traceback.format_exc())
    st.warning("请截图此红色报错信息发给我，我来帮你排查！")
