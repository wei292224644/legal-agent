"""短剧本 — 试用期辞退咨询（8 轮）

场景：员工试用期被公司以"不符合录用条件"辞退，客户咨询是否合法。
特点：问题聚焦，律师快速判断合法性。
"""

turns = [
    ("lawyer", "您好，什么情况？", "ignore", "none"),
    ("client", "律师好，我在试用期被公司辞退了。", "complex", "query_law"),
    ("lawyer", "试用期多长，入职多久了？", "ignore", "none"),
    ("client", "三个月试用期，入职两个月，昨天收到的辞退通知。", "simple", "record_only"),
    ("lawyer", "辞退理由写的是什么？", "ignore", "none"),
    ("client", "写的是不符合录用条件，但从来没告诉我录用条件是什么。", "complex", "risk_evaluation"),
    ("client", "这合法吗，我能要求赔偿吗？", "complex", "risk_evaluation"),
    ("lawyer", "不合法。试用期辞退必须证明不符合录用条件，且录用条件需事先告知。", "ignore", "none"),
]
