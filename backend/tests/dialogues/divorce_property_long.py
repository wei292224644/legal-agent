"""长剧本 — 复杂离婚财产分割（38 轮）

场景：结婚 8 年，涉及公司股权、两套房产、股票账户、孩子抚养权。
特点：情感波动大，财产复杂，多次策略讨论和风险评估。
"""

turns = [
    # 背景信息（大量 record_only）
    ("lawyer", "您好，请坐。今天咨询什么问题？", "ignore", "none"),
    ("client", "律师好，我想离婚，财产分割比较复杂。", "simple", "record_only"),
    ("lawyer", "结婚多久了，有孩子吗？", "ignore", "none"),
    ("client", "结婚 8 年，有一个儿子 6 岁。", "simple", "record_only"),
    ("lawyer", "主要财产有哪些？", "ignore", "none"),
    ("client", "两套房子，一套婚前他买的，一套婚后共同买的。", "simple", "record_only"),
    ("lawyer", "婚后这套房子登记在谁名下？", "ignore", "none"),
    ("client", "登记在他一个人名下，但首付是我们一起出的。", "simple", "record_only"),
    ("lawyer", "还有其他财产吗？", "ignore", "none"),
    ("client", "他名下有一家公司，股权应该值不少钱。", "simple", "record_only"),
    ("lawyer", "公司是他婚前成立的还是婚后的？", "ignore", "none"),
    ("client", "婚后第三年成立的，注册资金 100 万，他占 80%。", "simple", "record_only"),
    ("lawyer", "公司盈利情况怎么样？", "ignore", "none"),
    ("client", "去年净利润大概 200 万，但他说公司亏钱。", "simple", "record_only"),
    ("lawyer", "您参与公司经营了吗？", "ignore", "none"),
    ("client", "没有，我一直在国企上班，没管过公司的事。", "simple", "record_only"),
    ("lawyer", "您自己的收入情况呢？", "ignore", "none"),
    ("client", "年薪 15 万左右，比较稳定。", "simple", "record_only"),
    ("lawyer", "他的收入呢？", "ignore", "none"),
    ("client", "工资卡上每月 2 万，但公司分红他不告诉我。", "simple", "record_only"),
    ("lawyer", "有股票、基金这些吗？", "ignore", "none"),
    ("client", "有一个股票账户，婚后开的，里面大概 30 万。", "simple", "record_only"),
    ("lawyer", "存款呢？", "ignore", "none"),
    ("client", "我知道的联名账户有 20 万，他个人账户我不清楚。", "simple", "record_only"),
    ("lawyer", "债务情况呢，有没有共同债务？", "ignore", "none"),
    ("client", "婚后房子还有 80 万贷款没还完，其他不知道。", "simple", "record_only"),
    # 简单法律问题
    ("client", "婚前那套房子我能分吗？", "simple", "query_law"),
    ("lawyer", "婚前财产原则上归个人，但婚后还贷部分及增值可以要求补偿。", "ignore", "none"),
    ("client", "公司股份我能分多少？", "simple", "query_law"),
    ("lawyer", "婚后取得的股权属于共同财产，原则上一人一半，但实务中可能折价补偿。", "ignore", "none"),
    ("client", "孩子抚养权一般怎么判？", "simple", "query_law"),
    ("lawyer", "6 岁孩子法院会综合考虑抚养能力、孩子意愿，您收入稳定是有利因素。", "ignore", "none"),
    # 复杂策略
    ("client", "我怎么查清他到底有多少财产？", "complex", "strategy_advice"),
    ("lawyer", "可以申请法院调查令，查银行流水、股票账户、公司账册。", "ignore", "none"),
    ("client", "他转移财产怎么办？", "simple", "query_law"),
    ("lawyer", "可以申请财产保全，如果能证明他恶意转移，可以少分或不分给他。", "ignore", "none"),
    # 风险评估
    ("client", "如果走诉讼，我大概能拿到多少？", "complex", "risk_evaluation"),
    ("lawyer", "要看财产查清情况，粗略估计婚后共同财产部分您能分到 40% 到 60%。", "ignore", "none"),
    ("client", "抚养权我能拿到吗？", "complex", "risk_evaluation"),
    ("lawyer", "您收入稳定、孩子年龄小，胜率较高，但最终要看具体证据。", "ignore", "none"),
    # 策略
    ("client", "我该先协议还是直接起诉？", "complex", "strategy_advice"),
    ("lawyer", "建议先摸清财产底细再谈判，谈不拢再起诉，避免被动。", "ignore", "none"),
    ("client", "谈判的时候要注意什么？", "complex", "strategy_advice"),
    ("lawyer", "不要暴露底线，所有承诺要求书面确认，最好有律师在场。", "ignore", "none"),
    # 结尾
    ("client", "谢谢律师，我回去整理一下材料。", "ignore", "none"),
]
