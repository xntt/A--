# config.py
"""全局配置"""
from datetime import datetime, timedelta

# ==================== API 配置 ====================
EASTMONEY_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://data.eastmoney.com/",
    "Accept": "application/json, text/plain, */*",
}

SINA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://finance.sina.com.cn/",
}

# ==================== 模块1：公告前异动 ====================
VOLUME_ANOMALY_RATIO = 3.0          # 成交量异常倍数（vs 20日均量）
AMOUNT_ANOMALY_RATIO = 3.0          # 成交额异常倍数
PRE_ANNOUNCE_WINDOW = 5             # 公告前检测窗口（交易日）
BASELINE_WINDOW = 20                # 基准计算窗口（交易日）
ANNOUNCE_KEYWORDS_POSITIVE = [
    "收购", "重组", "增持", "回购", "中标", "签约",
    "战略合作", "业绩预增", "高送转", "股权激励"
]
ANNOUNCE_KEYWORDS_NEGATIVE = [
    "减持", "业绩预减", "亏损", "处罚", "退市", "违规"
]

# ==================== 模块2：龙虎榜 ====================
FAMOUS_SEATS = {
    "作手新一": ["东方财富证券拉萨团结路第二证券营业部"],
    "炒股养家": ["国信证券深圳泰然九路证券营业部"],
    "赵老哥":   ["华鑫证券上海宛平南路证券营业部"],
    "方新侠":   ["中国银河证券绍兴证券营业部"],
    "小鳄鱼":   ["华泰证券深圳益田路荣超商务中心证券营业部"],
    "佛山无影脚": ["东方证券股份有限公司佛山季华六路证券营业部"],
    "欢乐海岸": ["中信证券深圳欢乐海岸证券营业部"],
    "金田路":   ["国信证券深圳金田路证券营业部"],
    "涅槃重生": ["华泰证券深圳香蜜湖路证券营业部"],
    "首板进击者": ["中信建投证券成都市南一环路证券营业部"],
}
SEAT_WIN_RATE_THRESHOLD = 60        # 席位胜率预警线(%)
SEAT_TRACK_DAYS = 90                # 席位回溯天数

# ==================== 模块3：大宗交易 ====================
BLOCK_DISCOUNT_THRESHOLD = -5.0     # 折价率预警线(%)
BLOCK_NEXT_DAY_GAIN_THRESHOLD = 3.0 # 次日涨幅关联阈值(%)
BLOCK_AMOUNT_THRESHOLD = 1000       # 大宗金额预警线(万元)

# ==================== 模块4：高管减持 ====================
REDUCTION_PRECISION_WINDOW = 30     # 减持后N日内出利空视为精准
REDUCTION_GAIN_BEFORE = 10.0        # 减持前N日涨幅阈值(%)
REDUCTION_LOOKBACK = 90             # 回溯天数

# ==================== 模块5：融资融券 ====================
MARGIN_SHORT_SPIKE_RATIO = 2.0      # 融券余额暴增倍数
MARGIN_LONG_SPIKE_RATIO = 1.5       # 融资余额暴增倍数
MARGIN_BASELINE_DAYS = 10           # 融资融券基准天数

# ==================== 预警等级 ====================
ALERT_COLORS = {
    "critical": "#FF0000",
    "high":     "#FF4444",
    "mid":      "#FF8800",
    "low":      "#FFCC00",
    "info":     "#00AAFF",
}

# ==================== 时间 ====================
TODAY = datetime.now().strftime("%Y-%m-%d")
TODAY_COMPACT = datetime.now().strftime("%Y%m%d")
