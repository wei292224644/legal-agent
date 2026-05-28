"""短剧本 — 交通事故快速咨询（10 轮）

场景：电动车与机动车碰撞，客户（伤者）咨询赔偿。
特点：客户目的明确、问答紧凑，以计算赔偿为主。
"""

turns = [
    # 开场 + 事实陈述
    ("lawyer", "您好，请坐。发生了交通事故？", "ignore", "none"),
    ("client", "律师好，我骑电动车被小轿车撞了。", "ignore", "none"),
    ("lawyer", "事故责任认定书怎么判的？", "ignore", "none"),
    ("client", "对方全责，交警已经出认定书了。", "simple", "record_only"),
    ("lawyer", "伤情怎么样，住院了吗？", "ignore", "none"),
    ("client", "右腿骨折，住院 15 天，医生建议休息三个月。", "simple", "record_only"),
    ("lawyer", "医疗费花了多少？", "ignore", "none"),
    ("client", "目前 3 万多，后续还要拆钢板。", "simple", "record_only"),
    ("client", "这种情况能赔多少？", "simple", "compute_compensation"),
    ("lawyer", "具体要看伤残鉴定等级，十级的话赔偿在 15 到 25 万之间。", "ignore", "none"),
]
