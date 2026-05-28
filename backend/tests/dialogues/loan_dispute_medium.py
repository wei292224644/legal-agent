"""中剧本 — 民间借贷纠纷（16 轮）

场景：朋友借钱 10 万不还，没有借条，客户咨询如何追回。
特点：证据缺失问题突出，涉及诉讼时效、利息计算。
"""

turns = [
    ("lawyer", "您好，请说。", "ignore", "none"),
    ("client", "律师好，朋友借了我 10 万，三年了一直不还。", "simple", "record_only"),
    ("lawyer", "有借条或者转账记录吗？", "ignore", "none"),
    ("client", "没有借条，只有微信转账记录，分三次转的。", "simple", "record_only"),
    ("lawyer", "聊天记录里有没有提到这是借款？", "ignore", "none"),
    ("client", '有，微信上他说"借我 10 万周转一下，明年还"，有截图。', "simple", "record_only"),
    ("lawyer", "最后一次催款是什么时候？", "ignore", "none"),
    ("client", "半年前微信催过，他说再缓缓，之后就没回复了。", "simple", "record_only"),
    ("client", "没有借条能打赢吗？", "complex", "risk_evaluation"),
    ("lawyer", "有转账记录和借款合意聊天记录，证据链基本完整，胜率较高。", "ignore", "none"),
    ("client", "利息怎么算？", "simple", "compute_compensation"),
    ("lawyer", "没有约定利息的话，法院只支持逾期利息，按 LPR 计算。", "ignore", "none"),
    ("client", "过了诉讼时效吗？", "simple", "query_law"),
    ("lawyer", "没有。诉讼时效三年，您半年前催款导致时效中断，重新计算。", "ignore", "none"),
    ("client", "我该先起诉还是先调解？", "complex", "strategy_advice"),
    ("lawyer", "可以先申请诉前调解，不成再立案，调解不成不影响诉讼。", "ignore", "none"),
]
