"""长剧本 — 劳动纠纷咨询（31 轮，原基准剧本）

场景：员工被公司以"不胜任工作"为由口头辞退，咨询赔偿和维权策略。
特点：信息收集密集，穿插简单计算和复杂策略。
"""

turns = [
    ("lawyer", "你好，请坐。今天想咨询什么问题？", "ignore", "none"),
    ("client", "王律师您好，我被公司违法解除了。", "complex", "query_law"),
    ("lawyer", "您在公司工作多久了？", "ignore", "none"),
    ("client", "两年三个月。", "simple", "record_only"),
    ("lawyer", "月薪是多少，税前还是税后？", "ignore", "none"),
    ("client", "税前两万五。", "simple", "record_only"),
    ("lawyer", "解除通知是什么时候收到的？", "ignore", "none"),
    ("client", "5月1号口头通知的。", "simple", "record_only"),
    ("lawyer", "有书面解除通知吗？", "ignore", "none"),
    ("client", "还没有，只是主管口头说的。", "ignore", "none"),
    ("lawyer", "劳动合同签了吗，几年期？", "ignore", "none"),
    ("client", "签了，三年期的。", "simple", "record_only"),
    ("lawyer", "公司给出的解除理由是什么？", "ignore", "none"),
    ("client", "说我不胜任工作。", "simple", "record_only"),
    ("lawyer", "之前有没有绩效考核记录？", "ignore", "none"),
    ("client", "有的，但都是合格的。", "ignore", "none"),
    ("client", "我能拿多少赔偿？", "simple", "compute_compensation"),
    ("lawyer", "违法解除的话一般是2N。", "ignore", "none"),
    ("client", "N+1怎么算？", "simple", "compute_compensation"),
    ("lawyer", "N是工作年限，每满一年一个月工资。", "ignore", "none"),
    ("client", "那我该怎么跟公司谈？", "complex", "strategy_advice"),
    ("lawyer", "先准备证据清单。", "ignore", "none"),
    ("client", "需要准备哪些证据？", "complex", "query_law"),
    ("lawyer", "劳动合同、工资流水、解除通知、考勤记录。", "ignore", "none"),
    ("client", "竞业限制最长多久？", "simple", "query_law"),
    ("lawyer", "两年。", "ignore", "none"),
    ("client", "加班费按什么标准？", "simple", "query_law"),
    ("lawyer", "工作日1.5倍，周末2倍，法定节假日3倍。", "ignore", "none"),
    ("client", "能赢吗？", "complex", "risk_evaluation"),
    ("lawyer", "证据充分的话胜率很高，不用太担心。", "ignore", "none"),
    ("client", "谢谢王律师，我回去准备材料。", "ignore", "none"),
]
