import streamlit as st
import requests
import pandas as pd
import re
import time

# ==========================================
# 工具函数：通过新浪财经API获取实时数据
# ==========================================
def get_sina_data(stock_code):
    # 处理股票代码前缀 (新浪API需要 sh 或 sz)
    if stock_code.startswith('6'):
        full_code = f"sh{stock_code}"
    elif stock_code.startswith('0') or stock_code.startswith('3'):
        full_code = f"sz{stock_code}"
    else:
        return None

    url = f"http://hq.sinajs.cn/list={full_code}"
    # 新浪API需要加上 Referer 请求头，否则可能会被拒绝访问
    headers = {'Referer': 'https://finance.sina.com.cn'}
    
    try:
        response = requests.get(url, headers=headers, timeout=5)
        response.encoding = 'gbk' # 新浪接口编码是GBK
        
        # 解析返回的字符串 (例如: var hq_str_sh600519="贵州茅台,1700.00,1710.00...")
        match = re.search(r'=\"(.*)\"', response.text)
        if match:
            data_list = match.group(1).split(',')
            if len(data_list) > 30:
                name = data_list[0]
                open_price = float(data_list[1])
                yest_close = float(data_list[2])
                current_price = float(data_list[3])
                high_price = float(data_list[4])
                low_price = float(data_list[5])
                volume = float(data_list[8]) / 100 # 股数转为手
                amount = float(data_list[9]) / 10000 # 成交额转为万元
                
                # 计算涨跌幅
                if yest_close > 0:
                    pct_change = ((current_price - yest_close) / yest_close) * 100
                else:
                    pct_change = 0.0

                return {
                    "代码": stock_code,
                    "名称": name,
                    "现价": current_price,
                    "涨跌幅(%)": round(pct_change, 2),
                    "昨收": yest_close,
                    "今日开盘": open_price,
                    "最高": high_price,
                    "最低": low_price,
                    "成交量(手)": round(volume, 2),
                    "成交额(万)": round(amount, 2)
                }
    except Exception as e:
        return None
    return None

# ==========================================
# Streamlit 网页界面配置
# ==========================================
st.set_page_config(page_title="我的A股量化决策系统", layout="wide")
st.title("📈 个人量化选股与诊断系统")

# 创建两个标签页 (对应您的两个需求)
tab1, tab2 = st.tabs(["🔍 个股手动诊断", "🚀 优质股自动扫描"])

# ----------------- 模块一：手动诊断 -----------------
with tab1:
    st.header("个股状态快速体检")
    
    # 用户输入框
    input_code = st.text_input("请输入6位股票代码 (如: 600519, 300750)", max_chars=6)
    
    if st.button("开始诊断"):
        if len(input_code) == 6:
            with st.spinner('正在连接新浪财经获取数据...'):
                stock_data = get_sina_data(input_code)
                
                if stock_data:
                    st.success(f"成功获取 {stock_data['名称']} ({stock_data['代码']}) 的实时数据！")
                    
                    # 使用 Streamlit 的列布局展示核心数据
                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("当前价格", f"¥{stock_data['现价']}", f"{stock_data['涨跌幅(%)']}%")
                    col2.metric("今日开盘", f"¥{stock_data['今日开盘']}")
                    col3.metric("最高价", f"¥{stock_data['最高']}")
                    col4.metric("成交额", f"{stock_data['成交额(万)']} 万")
                    
                    # 诊断逻辑 (基于量价)
                    st.markdown("### 🤖 机器诊断结论")
                    if stock_data['涨跌幅(%)'] > 9.5:
                        st.warning("⚠️ 该股已涨停或接近涨停，风险极高，绝对不建议追高！")
                    elif stock_data['涨跌幅(%)'] < -5:
                        st.error("🩸 该股今日大跌，处于空头趋势，切勿盲目抄底 (接飞刀)！")
                    elif stock_data['现价'] < stock_data['昨收'] and stock_data['现价'] > stock_data['今日开盘']:
                        st.info("💡 假阴真阳：今日低开高走，有资金承接，可结合大盘环境观察。")
                    else:
                        st.info("📊 盘面暂无极端异动，请结合该公司的基本面 (ROE、现金流) 进一步判断。")
                else:
                    st.error("获取数据失败，请检查股票代码是否正确，或网络是否异常。")
        else:
            st.warning("请输入正确的6位数字股票代码！")

# ----------------- 模块二：自动扫描 -----------------
with tab2:
    st.header("自选股池异动扫描")
    st.write("说明：因新浪API频率限制，全市场5000只股票扫描会导致IP被封。此处演示对【自选股池】进行快速量价扫描。")
    
    # 让用户输入一批关注的股票代码
    default_pool = "600519, 300750, 000858, 601318, 002594"
    scan_input = st.text_area("请输入要扫描的股票池 (用逗号分隔)", value=default_pool)
    
    if st.button("一键扫描选股"):
        code_list = [code.strip() for code in scan_input.split(',')]
        
        results = []
        progress_bar = st.progress(0)
        
        with st.spinner("正在从新浪财经抓取并分析数据..."):
            for i, code in enumerate(code_list):
                if len(code) == 6:
                    data = get_sina_data(code)
                    if data:
                        # 在这里加入您的【过滤规则】，例如：只筛选出今天翻红的股票
                        if data['涨跌幅(%)'] > 0:
                            data['状态'] = "✅ 强势翻红"
                        else:
                            data['状态'] = "弱势调整"
                        results.append(data)
                
                # 进度条更新，并稍微延迟防封禁
                progress_bar.progress((i + 1) / len(code_list))
                time.sleep(0.2) 
                
        if results:
            df = pd.DataFrame(results)
            # 调整列的顺序
            df = df[['代码', '名称', '现价', '涨跌幅(%)', '成交额(万)', '状态']]
            
            st.markdown("### 🎯 扫描结果 (仅展示池内股票状态)")
            # 以交互式表格展示
            st.dataframe(df.style.applymap(
                lambda x: 'color: red' if isinstance(x, float) and x > 0 else ('color: green' if isinstance(x, float) and x < 0 else ''), 
                subset=['涨跌幅(%)']
            ), use_container_width=True)
            
            st.write("👉 **策略建议：** 重点关注红盘且大盘环境较好时的标的，剔除弱势调整标的。")
