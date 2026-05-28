"""长剧本 — 盗窃罪刑事辩护咨询（50 轮）

场景：嫌疑人家属（妻子）咨询盗窃罪辩护，涉及多次盗窃、金额认定、累犯、取保、认罪认罚。
特点：情绪紧张，涉及程序问题多，辩护策略复杂。
"""

turns = [
    # 开场
    ("lawyer", "您好，请坐。是什么案件？", "ignore", "none"),
    ("client", "律师好，我老公被警察抓了，说是盗窃。", "simple", "record_only"),
    ("lawyer", "什么时候被抓的，现在关在哪里？", "ignore", "none"),
    ("client", "前天晚上在家被抓的，现在关在区看守所。", "simple", "record_only"),
    ("lawyer", "家属收到拘留通知书了吗？", "ignore", "none"),
    ("client", "收到了，写的是涉嫌盗窃罪，拘留期限 30 天。", "simple", "record_only"),
    # 案件事实
    ("lawyer", "他之前有没有案底？", "ignore", "none"),
    ("client", "有过，三年前因为盗窃判过半年，已经刑满释放了。", "simple", "record_only"),
    ("lawyer", "这次涉嫌盗窃了几次？", "ignore", "none"),
    ("client", "警察说查了监控，有 5 次，都是进超市偷东西。", "simple", "record_only"),
    ("lawyer", "偷的是什么东西，大概值多少钱？", "ignore", "none"),
    ("client", "都是烟酒和电子产品，具体金额我不清楚。", "simple", "record_only"),
    ("lawyer", "警方有没有告知涉案金额？", "ignore", "none"),
    ("client", "办案民警说初步认定 3 万多，但还没出正式鉴定。", "simple", "record_only"),
    ("lawyer", "5 次盗窃分别是什么时间？", "ignore", "none"),
    ("client", "从今年 1 月到 4 月，每个月一次，都是晚上去的。", "simple", "record_only"),
    ("lawyer", "他是怎么进超市的，撬锁还是翻墙？", "ignore", "none"),
    ("client", "他说后门没锁，推门进去的，没撬锁。", "simple", "record_only"),
    ("lawyer", "有没有同伙？", "ignore", "none"),
    ("client", "没有，他一个人干的。", "simple", "record_only"),
    ("lawyer", "赃物处理了吗，还在家里吗？", "ignore", "none"),
    ("client", "大部分卖了，还剩一些烟酒在家，警察已经搜走了。", "simple", "record_only"),
    ("lawyer", "销赃的钱还剩多少？", "ignore", "none"),
    ("client", "他说花了 1 万多，还剩几千块在银行卡里，已经被冻结了。", "simple", "record_only"),
    # 客户个人情况
    ("lawyer", "您老公现在的工作和家庭情况？", "ignore", "none"),
    ("client", "他之前在工地打工，我是超市收银员，有个孩子 5 岁。", "simple", "record_only"),
    ("lawyer", "家里经济条件怎么样？", "ignore", "none"),
    ("client", "一般，月收入加起来 8 千左右，没什么存款。", "simple", "record_only"),
    ("lawyer", "他为什么去偷，是欠了钱还是吸毒？", "ignore", "none"),
    ("client", "他说去年赌博欠了债，被催得紧，没办法才去偷的。", "simple", "record_only"),
    ("lawyer", "现在欠了多少赌债？", "ignore", "none"),
    ("client", "还有 5 万左右没还，高利贷。", "simple", "record_only"),
    # 简单法律问题
    ("client", "盗窃罪怎么量刑？", "simple", "query_law"),
    ("lawyer", "数额较大的三年以下，数额巨大的三到十年，数额特别巨大的十年以上。", "ignore", "none"),
    ("client", "3 万多算数额较大还是巨大？", "simple", "query_law"),
    ("lawyer", "各地标准不同，一般 3 万以上算数额巨大，基准刑三到十年。", "ignore", "none"),
    ("client", "累犯会加重吗？", "simple", "query_law"),
    ("lawyer", "累犯从重处罚，不能缓刑，一般加基准刑的 10% 到 40%。", "ignore", "none"),
    ("client", "多次盗窃会加重吗？", "simple", "query_law"),
    ("lawyer", "两年内三次以上盗窃就构成多次盗窃，属于入罪标准之一，也是从重情节。", "ignore", "none"),
    ("client", "能取保候审吗？", "complex", "query_law"),
    ("lawyer", "累犯取保比较难，但金额如果能有争议，或者有退赔情节，可以尝试。", "ignore", "none"),
    # 复杂策略
    ("client", "我该请律师还是等法律援助？", "complex", "strategy_advice"),
    ("lawyer", "建议尽快请律师，侦查阶段只有律师能会见，能了解案情和警方证据。", "ignore", "none"),
    ("client", "律师会见能做什么？", "simple", "query_law"),
    ("lawyer", "了解具体案情、核实证据、提供法律咨询、告知权利义务、安抚情绪。", "ignore", "none"),
    ("client", "金额鉴定有问题怎么办？", "complex", "strategy_advice"),
    ("lawyer", "可以申请重新鉴定，特别是对电子产品的价格认定，常有争议空间。", "ignore", "none"),
    ("client", "退赔能减刑吗？", "simple", "query_law"),
    ("lawyer", "退赔退赃是从轻情节，可以减少基准刑的 30% 以下，能退尽量退。", "ignore", "none"),
    ("client", "认罪认罚会更好吗？", "complex", "strategy_advice"),
    ("lawyer", "认罪认罚可以从宽，但要看证据是否确实充分，如果证据有漏洞，先别急着认。", "ignore", "none"),
    # 风险评估
    ("client", "大概会判多久？", "complex", "risk_evaluation"),
    ("lawyer", "如果 3 万认定无误且累犯成立，基准刑三到四年，退赔认罪的话可能减到两年半左右。", "ignore", "none"),
    ("client", "有机会争取缓刑吗？", "complex", "risk_evaluation"),
    ("lawyer", "累犯不能缓刑，这是硬性规定，但可以在刑期上争取从轻。", "ignore", "none"),
    ("client", "我该怎么做才能帮到他？", "complex", "strategy_advice"),
    ("lawyer", "尽快委托律师会见，准备退赔资金，收集家庭困难的证明材料。", "ignore", "none"),
    # 结尾
    ("client", "律师费大概多少？", "simple", "query_law"),
    ("lawyer", "侦查阶段一般 1 到 3 万，看案情复杂程度。", "ignore", "none"),
    ("client", "谢谢律师，我跟家里商量一下。", "ignore", "none"),
]
