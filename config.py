# config.py

from datetime import datetime, timedelta

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Referer": "https://data.eastmoney.com/",
    "Accept": "*/*",
}

VOLUME_ANOMALY_RATIO = 2.5
AMOUNT_ANOMALY_RATIO = 2.5
PRE_ANNOUNCE_WINDOW = 5
BASELINE_WINDOW = 20

POSITIVE_KEYWORDS = [
    "收购", "重组", "增持", "回购", "中标", "签约",
    "战略合作", "业绩预增", "高送转", "股权激励", "合作"
]
NEGATIVE_KEYWORDS = [
    "减持", "业绩预减", "亏损", "处罚", "退市", "违规", "立案", "风险"
]

FAMOUS_SEATS = {
    "作手新一": "拉萨团结路第二",
    "炒股养家": "泰然九路",
    "赵老哥": "宛平南路",
    "方新侠": "银河证券绍兴",
    "佛山无影脚": "佛山季华六路",
    "欢乐海岸": "欢乐海岸",
    "金田路": "金田路",
}

BLOCK_DISCOUNT_THRESHOLD = -3.0
BLOCK_AMOUNT_MIN = 300
MARGIN_SPIKE_RATIO = 1.8
