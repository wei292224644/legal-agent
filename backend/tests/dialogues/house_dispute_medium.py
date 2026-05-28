"""中剧本 — 房产买卖合同纠纷（20 轮）

场景：买家交了 20 万定金后，卖家以房价上涨为由拒绝过户，买家咨询维权。
特点：涉及定金罚则、违约金、合同条款解释，有策略讨论。
"""

turns = [
    # 事实铺陈
    ("lawyer", "您好，请坐。是什么纠纷？", "ignore", "none"),
    ("client", "律师好，我买房交了定金，卖家现在不卖了。", "simple", "record_only"),
    ("lawyer", "合同签了吗，定金多少？", "ignore", "none"),
    ("client", "签了买卖合同，定金 20 万，总价 280 万。", "simple", "record_only"),
    ("lawyer", "约定的过户时间是什么时候？", "ignore", "none"),
    ("client", "合同约定 6 月 30 号前过户，现在已经超期了。", "simple", "record_only"),
    ("lawyer", "卖家给的理由是什么？", "ignore", "none"),
    ("client", "说房价涨了，要加 30 万才肯卖，不加就解约。", "simple", "record_only"),
    ("lawyer", "您是想继续买房，还是解除合同要赔偿？", "ignore", "none"),
    ("client", "我还是想买这套房，房价已经涨了 50 万了。", "simple", "record_only"),
    # 法律问题
    ("client", "我能要求强制过户吗？", "simple", "query_law"),
    ("lawyer", "可以起诉要求继续履行合同并办理过户，法院一般会支持。", "ignore", "none"),
    ("client", "定金能退吗？", "simple", "query_law"),
    ("lawyer", "如果要求继续履行，定金转为房款；如果解约，可以要求双倍返还。", "ignore", "none"),
    ("client", "违约金怎么算？", "simple", "compute_compensation"),
    ("lawyer", "合同约定违约金是总价的 10%，即 28 万。", "ignore", "none"),
    # 策略讨论（复杂）
    ("client", "我该先起诉还是先协商？", "complex", "strategy_advice"),
    ("lawyer", "建议先发律师函催告，同时准备起诉材料。", "ignore", "none"),
    ("client", "如果卖家把房卖给别人了怎么办？", "simple", "query_law"),
    ("lawyer", "可以申请财产保全，查封房产防止一房二卖。", "ignore", "none"),
]
