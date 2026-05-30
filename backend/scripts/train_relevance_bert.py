"""BERT RelevanceGate 训练脚本 — 二分类（ignore / should_enter）。

使用 hfl/chinese-macbert-base 训练极简二分类模型。
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import train_test_split
from torch.utils.data import DataLoader, Dataset
from tqdm import tqdm
from torch.optim import AdamW
from transformers import BertModel, BertTokenizer, get_linear_schedule_with_warmup

SEED = 42
random.seed(SEED)
np.random.seed(SEED)
torch.manual_seed(SEED)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Device: {DEVICE}")

MODEL_NAME = "hfl/chinese-macbert-base"
MAX_LEN = 64
BATCH_SIZE = 32
EPOCHS = 8
LR = 2e-5

# ═══════════════════════════════════════════════════════════════
# 数据集构建 — 大量 ignore 样本 + should_enter 样本
# ═══════════════════════════════════════════════════════════════

SEED_SAMPLES = [
    # ====== ignore: 纯寒暄 / 问候 / 感谢 / 情绪 / 应答 ======
    ("律师你好", 0), ("您好", 0), ("王律师您好", 0), ("早上好", 0),
    ("下午好", 0), ("晚上好", 0), ("嗨", 0), ("打扰了", 0),
    ("谢谢", 0), ("谢谢您", 0), ("非常感谢", 0), ("辛苦了", 0),
    ("麻烦您了", 0), ("再见", 0), ("下次见", 0), ("好的", 0),
    ("没问题", 0), ("嗯嗯", 0), ("对", 0), ("是的", 0),
    ("明白了", 0), ("知道了", 0), ("理解", 0), ("我理解", 0),
    ("您说得对", 0), ("听您的", 0), ("那就这样吧", 0), ("可以", 0),
    ("行", 0), ("嗯", 0), ("哦", 0), ("好吧", 0),
    ("保重身体", 0), ("祝您顺利", 0), ("加油", 0),
    ("别太担心", 0), ("别担心，有我在", 0), ("放轻松", 0),
    ("一切都会好起来的", 0), ("我相信你", 0),
    ("您先喝口水", 0), ("请坐", 0), ("慢走", 0),
    ("回头联系", 0), ("保持联系", 0), ("方便的时候说", 0),
    ("有空再聊", 0), ("久仰大名", 0), ("失敬失敬", 0),
    ("见到您真荣幸", 0), ("请问怎么称呼", 0), ("您贵姓", 0),
    ("我叫张三", 0), ("今年多大了", 0), ("您看起来挺年轻的", 0),
    ("气色不错", 0), ("最近瘦了啊", 0), ("减肥成功了吧", 0),
    ("这件衣服挺好看的", 0), ("您这包什么牌子的", 0),
    ("手机是最新款吗", 0), ("手表挺贵的吧", 0),
    ("车停在地下吗", 0), ("地铁几号线过来的", 0),
    ("打车来的吧", 0), ("路上堵不堵", 0), ("高架通车了吗", 0),
    ("今天挺热的", 0), ("降温了注意保暖", 0),
    ("昨天下了大雨", 0), ("雾霾太严重了", 0),
    ("空气质量还行", 0), ("最近流感挺严重的", 0),
    ("戴口罩了吗", 0), ("疫苗打了吗", 0), ("核酸检测做了吗", 0),
    ("健康码是绿的吧", 0), ("小区封了吗", 0),
    ("居家办公多久了", 0), ("复工复产了吗", 0),
    ("行业不景气啊", 0), ("经济下行压力大", 0),
    ("股市又跌了", 0), ("基金亏了不少", 0),
    ("房市降温了", 0), ("贷款利率下调了", 0),
    ("学区房还值钱吗", 0), ("二胎政策开放了", 0),
    ("三胎有人生吗", 0), ("人口负增长了啊", 0),
    ("老龄化严重了", 0), ("养老金够用吗", 0),
    ("考公务员热啊", 0), ("研究生扩招了", 0),
    ("就业形势严峻", 0), ("应届生找不到工作", 0),
    ("大厂都在裁员", 0), ("互联网寒冬", 0),
    ("35岁危机是真的", 0), ("程序员吃青春饭", 0),
    ("考个证吧", 0), ("学点新技能", 0),
    ("转行做什么好", 0), ("创业风险太大了", 0),
    ("合伙做生意小心", 0), ("加盟都是割韭菜", 0),
    ("直播带货还行吗", 0), ("短视频风口过了", 0),
    ("AI会取代人类吗", 0), ("ChatGPT好用吗", 0),
    ("自动驾驶靠谱吗", 0), ("元宇宙凉了吧", 0),
    ("区块链是骗局吗", 0), ("虚拟币不能碰", 0),
    ("NFT还有人买吗", 0), ("电子烟禁售了", 0),
    ("槟榔不让卖了", 0), ("预制菜健康吗", 0),
    ("食品添加剂可怕", 0), ("转基因能吃吗", 0),
    ("保健品别乱吃", 0), ("中医靠谱吗", 0),
    ("体检一年做一次", 0), ("挂号太难了", 0),
    ("专家号抢不到", 0), ("私立医院贵吗", 0),
    ("医美风险大", 0), ("整容需谨慎", 0),
    ("近视手术安全吗", 0), ("植发有用吗", 0),
    ("牙套要戴多久", 0), ("心理咨询贵不贵", 0),
    ("抑郁症能好吗", 0), ("安眠药有依赖", 0),
    ("褪黑素管用吗", 0), ("健身办卡别冲动", 0),
    ("私教课值得买吗", 0), ("瑜伽能减肥吗", 0),
    ("跑步伤膝盖吗", 0), ("游泳是最好的运动", 0),
    ("夜跑注意安全", 0), ("马拉松别轻易尝试", 0),
    ("徒步旅行有意思", 0), ("自驾游很自由", 0),
    ("跟团游太坑了", 0), ("签证好办吗", 0),
    ("护照过期了", 0), ("机票涨价了", 0),
    ("高铁方便多了", 0), ("民宿比酒店便宜", 0),
    ("露营最近很火", 0),

    # ── 对抗：长但无意义的 ignore ──
    ("今天天气真不错，早上出门的时候太阳特别大，您过来路上堵车了吗？", 0),
    ("我最近身体不太好，老是失眠，医生让我多休息，您也要注意身体啊。", 0),
    ("这个茶还不错吧，是我朋友从云南带回来的普洱，您多喝点。", 0),
    ("对了，您孩子今年高考吧，考的怎么样，报哪个学校了？", 0),
    ("哎其实我也遇到过类似的事，当时特别难受，后来慢慢想开了。", 0),
    ("您这办公室装修得真不错，光线特别好，视野也开阔。", 0),
    ("昨天那个新闻您看了吗，太离谱了，现在社会真是乱。", 0),
    ("我来的路上在地铁站看到一只流浪猫，特别可爱，想养但是没条件。", 0),
    ("您中午吃什么，附近有家川菜馆味道还行，要不要一起？", 0),
    ("疫情期间真不容易，大家都不好过，不过现在总算过去了。", 0),
    ("您这律师袍真精神，穿上特别有气场，我跟您说啊我年轻时就特别崇拜律师。", 0),
    ("咱们先把这些放一放，不着急，慢慢来，您先调整一下情绪。", 0),
    ("其实我也不太清楚为什么要来找律师，就是朋友推荐的，说您特别厉害。", 0),
    ("我老婆不同意我来，说浪费钱，但我就是想问问，也没想真打。", 0),
    ("您这空调开得有点低，我能把外套穿上吗，不好意思啊。", 0),

    # ── 边界模糊：带法律名词但实际是寒暄/废话 ──
    ("律师就是厉害啊", 0), ("法官也挺辛苦的", 0),
    ("现在打官司的人真多", 0), ("法律程序太复杂了", 0),
    ("你们律师收入挺高的吧", 0), ("我有个朋友也是律师", 0),
    ("现在学法的人好多啊", 0), ("电视上那些律师挺帅的", 0),
    ("法考是不是特别难", 0), ("律师行业竞争很激烈吧", 0),
    ("你们平时案子多吗", 0), ("法院是不是特别忙", 0),
    ("现在律师行业挺火的", 0), ("法院门口总是很多人", 0),
    ("法官这工作挺累的吧", 0), ("打官司是不是特别贵", 0),
    ("法律节目挺好看的", 0), ("我看过一个法律纪录片", 0),
    ("罗翔老师讲刑法挺有意思的", 0), ("现在学法是不是不好就业", 0),
    ("你们平时加班多吗", 0), ("做律师是不是要经常出差", 0),
    ("您考了多少年才过的司法考试", 0), ("律师和法官哪个收入高", 0),
    ("法律援助是免费的吗", 0), ("现在网上也能立案了吧", 0),
    ("电子合同有法律效力吗", 0), ("AI以后能替代律师吗", 0),
    ("ChatGPT也能写合同吧", 0), ("机器人法官听着挺科幻的", 0),
    ("我觉得法律应该再简化一点", 0), ("国外法律跟中国差别大吗", 0),

    # ====== should_enter: 事实陈述 / 案情描述 ======
    ("我被公司违法解除了。", 1), ("律师，我老公被警察抓了。", 1),
    ("我签了三年的劳动合同。", 1), ("月薪税前两万五。", 1),
    ("5月1号口头通知的。", 1), ("还没有书面通知。", 1),
    ("说我不能胜任工作。", 1), ("有绩效考核记录，都是合格的。", 1),
    ("收到了拘留通知书，写的是涉嫌盗窃罪。", 1),
    ("有5次，都是进超市偷东西。", 1), ("大概值3万多。", 1),
    ("从去年1月到4月，每个月一次。", 1),
    ("他一个人干的，没有同伙。", 1),
    ("大部分卖了，还剩一些烟酒在家。", 1),
    ("已经刑满释放了。", 1), ("有个孩子5岁。", 1),
    ("月收入加起来8千左右。", 1),
    ("欠了5万左右没还，是高利贷。", 1),
    ("房子是我的婚前财产。", 1), ("婚后一起还贷。", 1),
    ("对方出轨，我有聊天记录。", 1), ("孩子一直跟我生活。", 1),
    ("房产证写的是我的名字。", 1),
    ("借款金额10万，年利率24%。", 1),
    ("写了借条，没写还款日期。", 1),
    ("追尾了，对方全责。", 1), ("交警认定对方全责。", 1),
    ("维修费花了2万。", 1), ("对方保险公司拒赔。", 1),

    # ── 对抗：极短的 should_enter ──
    ("被打了。", 1), ("被辞了。", 1), ("离婚了。", 1),
    ("欠钱了。", 1), ("撞车了。", 1), ("被抓了。", 1),
    ("受伤了。", 1), ("被骗了。", 1),
    ("合同呢？", 1), ("工资多少？", 1), ("几年了？", 1),
    ("有证据吗？", 1), ("报警了吗？", 1), ("赔多少？", 1),
    ("能赢吗？", 1), ("怎么办？", 1), ("怎么算？", 1),
    ("多久？", 1), ("谁的责任？", 1), ("怎么分？", 1),
    ("违约了。", 1), ("超时了。", 1), ("不干了。", 1),
    ("他跑了。", 1), ("我告他。", 1),

    # ── 对抗：看起来像寒暄但实际是 should_enter ──
    ("您好，我想咨询一下离婚财产分割的问题。", 1),
    ("谢谢，那请问仲裁需要准备哪些材料呢？", 1),
    ("好的，公司的工商信息我可以去哪里查？", 1),
    ("明白了，那如果对方转移财产我该怎么办？", 1),
    ("没问题，我想问下加班费是按基本工资还是实发工资算？", 1),
    ("辛苦了，另外想问取保候审需要什么条件？", 1),
    ("保重，还有上次说的那个借条，格式对吗？", 1),
    ("您说得对，那赔偿金额一般怎么计算？", 1),

    # ====== should_enter: 法律询问 / 诉求 ======
    ("违法解除赔多少？", 1), ("我该怎么做？", 1),
    ("N+1怎么算？", 1), ("竞业限制最长多久？", 1),
    ("加班费按什么标准？", 1), ("能赢吗？", 1),
    ("需要准备哪些证据？", 1), ("盗窃罪怎么量刑？", 1),
    ("3万多算数额较大还是巨大？", 1), ("累犯会加重吗？", 1),
    ("能取保候审吗？", 1), ("我该请律师还是等法律援助？", 1),
    ("认罪认罚能减多少？", 1), ("大概会判多久？", 1),
    ("房子怎么分？", 1), ("我能拿到抚养权吗？", 1),
    ("抚养费一般多少？", 1), ("他能多分财产吗？", 1),
    ("诉讼时效多久？", 1), ("可以起诉吗？", 1),
    ("利息合法吗？", 1), ("怎么强制执行？", 1),
    ("对方转移财产怎么办？", 1), ("可以保全吗？", 1),
    ("精神损失能赔多少？", 1), ("工伤怎么认定？", 1),
    ("社保没缴怎么办？", 1), ("赔偿金要交税吗？", 1),
    ("仲裁要多久？", 1), ("一审不服怎么办？", 1),
    ("录音能当证据吗？", 1), ("微信聊天记录算证据吗？", 1),
    ("对方不出庭怎么办？", 1), ("公告送达要多久？", 1),

    # ====== should_enter: 策略讨论 / 律师指导 ======
    ("先准备证据清单。", 1), ("建议尽快请律师。", 1),
    ("可以申请重新鉴定。", 1), ("建议调解，省时省力。", 1),
    ("先不要签任何文件。", 1), ("保留好所有原件。", 1),
    ("注意录音取证。", 1), ("可以申请财产保全。", 1),
    ("先劳动仲裁，不能直接起诉。", 1),
    ("建议做伤情鉴定。", 1), ("收集转账记录。", 1),
    ("让对方写个书面确认。", 1),
    ("这是格式条款，可以主张无效。", 1),
    ("公司违法裁员，可以主张2N。", 1),
    ("根据劳动合同法第47条。", 1),
    ("需要先到劳动监察投诉。", 1),
    ("可以申请支付令。", 1),
    ("建议固定证据后再谈判。", 1),
    ("注意别超过诉讼时效。", 1),
    ("可以先发律师函。", 1),

    # ── 对抗：口语化 / 不完整 / 带错别字 ──
    ("那个，我老板把我开了，没给赔钱", 1),
    ("我老公被抓进去了，说是偷东西", 1),
    ("我跟人撞车了，他跑了我咋办", 1),
    ("借钱给人要不回来了，有欠条", 1),
    ("公司不交社保，我能告吗", 1),
    ("离婚的话房子能归我不，我买的", 1),
    ("娃儿一直跟我，他爹不管", 1),
    ("加班费一分钱没给过", 1),
    ("合同签的三年，干了两年被辞", 1),
    ("对方把我拉黑了，联系不上", 1),
    ("工伤认定他们不认，说我自己摔的", 1),
    ("仲裁完了公司不给钱", 1),
    ("对方上诉了，二审会改判吗", 1),
    ("我想离婚但他不同意", 1),
    ("被人打了，现在住院呢", 1),
    ("公司逼着签自愿离职", 1),
    ("彩礼能要回来吗，没结婚", 1),
    ("房东不退押金，合同到期了", 1),
    ("网购东西假货，商家不理我", 1),
    ("邻居装修把我墙震裂了", 1),
]


# ── 模板扩充 ignore ──
ignore_templates = []

greet_base = ["你好", "您好", "早上好", "下午好", "晚上好", "嗨"]
names = ["王律师", "李律师", "张律师", "律师", "陈律师", "刘律师", "赵律师", ""]
for g in greet_base:
    for n in names:
        ignore_templates.append(f"{n}{g}".strip())
        ignore_templates.append(f"{g}，{n}")

thanks_base = ["谢谢", "感谢", "麻烦您了", "辛苦了", "多亏您了"]
for t in thanks_base:
    ignore_templates.append(t)
    ignore_templates.append(f"{t}啊")
    ignore_templates.append(f"{t}您")
    ignore_templates.append(f"非常{t}")
    ignore_templates.append(f"太{t}了")

comfort = ["别担心", "别紧张", "放轻松", "别急", "慢慢来", "想开点"]
for c in comfort:
    ignore_templates.append(c)
    ignore_templates.append(f"{c}，会好的")
    ignore_templates.append(f"{c}，有我呢")
    ignore_templates.append(f"{c}，一切都会过去的")

resp = ["嗯", "对", "好的", "没问题", "明白", "知道", "可以", "行", "哦", "好吧"]
for r in resp:
    ignore_templates.append(r)
    ignore_templates.append(f"嗯{r}")
    ignore_templates.append(f"{r}的")
    ignore_templates.append(f"{r}知道了")

# 更多 ignore 闲聊
ignore_long = [
    "今天天气真不错", "最近身体不太好", "这个茶还不错",
    "对了，您孩子今年上学了吧", "其实我也遇到过类似的事",
    "您这办公室装修得真不错", "昨天那个新闻您看了吗",
    "我来的路上在地铁站看到一只流浪猫", "您中午吃什么",
    "疫情期间真不容易", "咱们先把这些放一放",
    "其实我也不太清楚为什么要来找律师", "我老婆不同意我来",
    "就是朋友推荐的", "也没想真打",
    "您这空调开得有点低", "我先喝口水",
    "不好意思我来晚了", "这椅子坐着挺舒服的",
    "我手机快没电了", "您这地方不好找啊",
    "楼下停车费真贵", "现在北京房价太贵了",
    "最近股市跌得真惨", "我养了一只狗",
    "您平时有什么爱好", "我老家是四川的",
    "现在外卖太慢了", "最近那个电视剧特别火",
    "孩子学习压力太大了", "工作太累了",
    "想换工作了", "考虑买房",
    "准备结婚", "刚生完孩子",
    "父母身体不太好", "老家拆迁了",
    "想投资理财", "准备出国",
    "学外语", "考驾照",
    "装修房子", "买家具",
    "养宠物", "种花",
    "做饭", "健身",
    "看电影", "听音乐",
    "打游戏", "刷抖音",
    "看小说", "写博客",
    "拍照", "旅游",
    "爬山", "钓鱼",
    "下棋", "打牌",
    "唱歌", "跳舞",
    "画画", "弹琴",
    "练书法", "做手工",
    "烘焙", "瑜伽",
    "太极", "跑步",
    "游泳", "骑车",
    "滑雪", "冲浪",
    "潜水", "跳伞",
    "攀岩", "蹦极",
    "漂流", "徒步",
    "露营", "野餐",
    "烧烤", "火锅",
    "日料", "西餐",
    "川菜", "湘菜",
    "粤菜", "鲁菜",
    "淮扬菜", "东北菜",
    "新疆菜", "云南菜",
    "泰国菜", "印度菜",
    "意大利菜", "法国菜",
    "墨西哥菜", "韩国菜",
    "越南菜", "土耳其菜",
    "希腊菜", "西班牙菜",
]
ignore_templates.extend(ignore_long)

# 带法律名词的闲聊
legal_chitchat = [
    "律师就是厉害啊", "法官也挺辛苦的",
    "现在打官司的人真多", "法律程序太复杂了",
    "你们律师收入挺高的吧", "我有个朋友也是律师",
    "现在学法的人好多啊", "电视上那些律师挺帅的",
    "法考是不是特别难", "律师行业竞争很激烈吧",
    "你们平时案子多吗", "法院是不是特别忙",
    "现在律师行业挺火的", "法院门口总是很多人",
    "法官这工作挺累的吧", "打官司是不是特别贵",
    "法律节目挺好看的", "我看过一个法律纪录片",
    "罗翔老师讲刑法挺有意思的", "现在学法是不是不好就业",
    "你们平时加班多吗", "做律师是不是要经常出差",
    "您考了多少年才过的司法考试", "律师和法官哪个收入高",
    "法律援助是免费的吗", "现在网上也能立案了吧",
    "电子合同有法律效力吗", "AI以后能替代律师吗",
    "ChatGPT也能写合同吧", "机器人法官听着挺科幻的",
    "我觉得法律应该再简化一点", "国外法律跟中国差别大吗",
    "诉讼法改了吗", "刑法修正案通过了吗",
    "民法典实施了吗", "公司法修订了吗",
    "劳动法保护劳动者吗", "消费者权益保护法有用吗",
    "环保法执行严格吗", "食品安全法处罚重吗",
    "交通法规越来越严", "税法每年都变",
    "知识产权法完善了吗", "数据安全法出台了",
    "个人信息保护法生效", "反垄断法修订",
    "外商投资法影响大吗", "跨境电商法",
    "网络安全法", "电子商务法",
    "社会保险法", "住房公积金条例",
]
ignore_templates.extend(legal_chitchat)

# ── 模板扩充 should_enter ──
enter_templates = []

# 劳动纠纷
labor = [
    "被辞退", "被裁员", "被开除了", "被优化了", "被劝退了",
    "没签劳动合同", "合同到期不续签", "强迫辞职", "逼我走人",
    "拖欠工资", "克扣工资", "少发工资", "工资发少了",
    "不给加班费", "周末加班没调休", "法定节假日加班",
    "没交社保", "社保基数不对", "公积金没缴",
    "工伤认定", "劳动能力鉴定", "职业病", "工亡",
    "竞业限制补偿", "培训违约金", "服务期未满",
    "N怎么算", "2N赔偿", "N+1补偿", "经济补偿金",
    "试用期被辞退", "转正前被开", "试用期不合格",
    "调岗降薪", "单方面调岗", "工作地点变更",
    "末位淘汰", "PIP绩效改进", "公司搬迁",
    "哺乳期", "孕期", "病假", "医疗期",
    "劳务派遣", "外包员工", "实习生",
    "入职押金", "扣押身份证", "扣押毕业证",
    "保密协议", "竞业协议", "股权激励", "期权",
    "离职证明", "档案转移", "社保转移",
    "失业金", "灵活就业", "个税退税",
    "年终奖", "劳务报酬", "老板跑路",
    "公司注销", "破产清算", "重整",
]

# 刑事
criminal = [
    "被刑事拘留", "被取保候审", "被逮捕了", "在看守所",
    "盗窃", "抢劫", "诈骗", "故意伤害", "寻衅滋事",
    "醉驾", "酒驾", "肇事逃逸", "危险驾驶",
    "聚众斗殴", "敲诈勒索", "绑架",
    "容留卖淫", "组织卖淫", "传播淫秽物品",
    "非法经营", "非法集资", "传销", "洗钱",
    "贩毒", "吸毒", "持有毒品",
    "杀人", "过失致人死亡", "正当防卫", "防卫过当",
    "累犯", "从犯", "主犯", "自首", "立功", "坦白",
    "认罪认罚", "缓刑", "减刑", "假释", "保外就医",
    "逃税", "虚开发票", "骗取出口退税", "走私",
    "职务侵占", "挪用资金", "非国家工作人员受贿",
    "侵犯商业秘密", "假冒注册商标", "侵犯著作权",
    "侵犯公民个人信息", "拒不履行判决裁定",
    "妨害公务", "交通肇事", "重大责任事故",
    "污染环境", "非法捕捞", "盗伐林木",
]

# 婚姻家庭
family = [
    "离婚", "起诉离婚", "协议离婚", "诉讼离婚",
    "财产分割", "房产分割", "婚前财产", "婚后共同财产",
    "抚养权", "抚养费", "探视权", "赡养费",
    "出轨", "家暴", "重婚", "同居", "分居",
    "彩礼", "嫁妆", "婚前协议", "忠诚协议",
    "遗产继承", "遗嘱", "法定继承", "代位继承",
    "亲子鉴定", "收养", "监护权",
]

# 借贷/合同
contract = [
    "借款", "欠款", "借条", "欠条", "收条",
    "利息", "高利贷", "砍头息", "复利", "逾期",
    "担保", "抵押", "质押", "保证", "连带责任",
    "合同纠纷", "违约", "违约金", "定金", "订金",
    "解除合同", "继续履行", "损害赔偿",
    "工程款", "实际施工人", "挂靠", "转包", "违法分包",
    "质保金", "缺陷责任期", "保修期",
]

# 交通/侵权
traffic = [
    "交通事故", "肇事", "全责", "主责", "同责",
    "保险理赔", "保险公司拒赔", "定损", "贬值损失",
    "人身损害", "伤残鉴定", "误工费", "护理费",
    "营养费", "精神损害赔偿", "后续治疗费",
]

# 诉讼/程序
procedure = [
    "起诉", "应诉", "反诉", "上诉", "再审", "申诉",
    "立案", "管辖", "诉讼时效", "证据保全", "财产保全",
    "强制执行", "列入失信", "限制高消费", "司法拘留",
    "仲裁", "调解", "和解", "司法确认",
    "公告送达", "缺席判决", "撤诉", "变更诉讼请求",
]

all_topics = labor + criminal + family + contract + traffic + procedure

q_prefix = ["怎么", "如何", "能否", "可以", "应该", "需要", "想", "要"]
q_suffix = ["吗", "呢", "么", "怎么办", "怎么弄", "怎么处理"]
for topic in all_topics:
    for p in q_prefix:
        enter_templates.append(f"{p}{topic}")
        enter_templates.append(f"{topic}{p}办")
    for s in q_suffix:
        enter_templates.append(f"{topic}{s}")
    enter_templates.append(f"涉及{topic}")
    enter_templates.append(f"关于{topic}")
    enter_templates.append(f"有个{topic}的问题")

s_prefix = ["发生了", "遇到了", "碰到了", "摊上", "卷入"]
for topic in all_topics:
    for p in s_prefix:
        enter_templates.append(f"{p}{topic}")
    enter_templates.append(f"{topic}了")
    enter_templates.append(f"被{topic}了")
    enter_templates.append(f"因为{topic}")
    enter_templates.append(f"存在{topic}")
    enter_templates.append(f"发现{topic}")

# 口语化 should_enter
colloquial = [
    "老板把我开了", "公司不要我了", "让我滚蛋",
    "钱没给我", "少给我钱了", "扣我工资",
    "加班不给钱", "周末还得上班", "节假日也加班",
    "没给我交社保", "社保交的最低档",
    "我老公进去了", "人被带走了", "关起来了",
    "偷东西了", "抢钱了", "打人了", "被骗了",
    "喝多开车被抓", "撞了人跑了",
    "过不下去了要离婚", "他想离我不想", "打架了想离婚",
    "他打我了", "有家暴", "出轨了", "在外面有人",
    "孩子归我", "我要孩子", "他不给抚养费",
    "房子是我的", "婚前买的", "一起还贷",
    "彩礼还没退", "嫁妆在他家",
    "钱借出去要不回来", "赖着不还", "躲着不见",
    "有借条", "没写欠条", "口头借的",
    "利息太高了", "利滚利", "砍头息",
    "撞车了", "被撞了", "对方跑了", "他全责",
    "保险不赔", "定损太低", "修车钱自己垫的",
    "受伤了住院", "骨折了", "脑震荡",
    "误工费怎么算", "护理费多少钱", "营养费多少",
    "告他", "起诉", "仲裁", "报案", "举报",
    "强制执行", "把他列入黑名单", "限制他消费",
    "他不执行判决", "转移财产了", "房子卖了",
    "找不到他人", "跑了", "失联了",
    "证据不够", "没证据", "只有聊天记录",
    "证人不愿意出庭", "监控坏了", "录音不清楚",
]
enter_templates.extend(colloquial)

# 去重
ignore_templates = list(set(ignore_templates))
enter_templates = list(set(enter_templates))

# 组合全部样本
all_texts = [t for t, _ in SEED_SAMPLES] + ignore_templates + enter_templates
all_labels = ([l for _, l in SEED_SAMPLES] + [0] * len(ignore_templates) + [1] * len(enter_templates))

seen = set()
unique_data = []
for t, l in zip(all_texts, all_labels):
    if t not in seen:
        seen.add(t)
        unique_data.append((t, l))

texts = [d[0] for d in unique_data]
labels = [d[1] for d in unique_data]

print(f"总样本数（去重后）: {len(texts)}")
print(f"ignore: {sum(1 for l in labels if l == 0)}")
print(f"should_enter: {sum(1 for l in labels if l == 1)}")

# 划分
train_texts, temp_texts, train_labels, temp_labels = train_test_split(
    texts, labels, test_size=0.2, random_state=42, stratify=labels
)
val_texts, test_texts, val_labels, test_labels = train_test_split(
    temp_texts, temp_labels, test_size=0.5, random_state=42, stratify=temp_labels
)

print(f"训练集: {len(train_texts)}, 验证集: {len(val_texts)}, 测试集: {len(test_texts)}")


# ═══════════════════════════════════════════════════════════════
# Tokenizer & Dataset
# ═══════════════════════════════════════════════════════════════

tokenizer = BertTokenizer.from_pretrained(MODEL_NAME)


class IntentDataset(Dataset):
    def __init__(self, texts, labels, tokenizer, max_len):
        self.texts = texts
        self.labels = labels
        self.tokenizer = tokenizer
        self.max_len = max_len

    def __len__(self):
        return len(self.texts)

    def __getitem__(self, idx):
        text = str(self.texts[idx])
        label = self.labels[idx]
        encoding = self.tokenizer(
            text,
            max_length=self.max_len,
            padding="max_length",
            truncation=True,
            return_tensors="pt",
        )
        return {
            "input_ids": encoding["input_ids"].squeeze(),
            "attention_mask": encoding["attention_mask"].squeeze(),
            "label": torch.tensor(label, dtype=torch.long),
        }


train_ds = IntentDataset(train_texts, train_labels, tokenizer, MAX_LEN)
val_ds = IntentDataset(val_texts, val_labels, tokenizer, MAX_LEN)
test_ds = IntentDataset(test_texts, test_labels, tokenizer, MAX_LEN)

train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True)
val_loader = DataLoader(val_ds, batch_size=BATCH_SIZE)
test_loader = DataLoader(test_ds, batch_size=BATCH_SIZE)


# ═══════════════════════════════════════════════════════════════
# 模型定义
# ═══════════════════════════════════════════════════════════════

class IntentClassifier(nn.Module):
    def __init__(self, model_name, num_classes=2, dropout=0.3):
        super().__init__()
        self.bert = BertModel.from_pretrained(model_name)
        self.dropout = nn.Dropout(dropout)
        self.classifier = nn.Linear(self.bert.config.hidden_size, num_classes)

    def forward(self, input_ids, attention_mask):
        outputs = self.bert(input_ids=input_ids, attention_mask=attention_mask)
        pooled = outputs.pooler_output
        pooled = self.dropout(pooled)
        logits = self.classifier(pooled)
        return logits


model = IntentClassifier(MODEL_NAME, num_classes=2).to(DEVICE)
print(f"模型参数: {sum(p.numel() for p in model.parameters()) / 1e6:.1f}M")


# ═══════════════════════════════════════════════════════════════
# 训练配置
# ═══════════════════════════════════════════════════════════════

from collections import Counter

label_counts = Counter(train_labels)
total = sum(label_counts.values())
class_weights = torch.tensor([
    total / label_counts[0],
    total / label_counts[1]
], dtype=torch.float).to(DEVICE)
class_weights = class_weights / class_weights.sum() * 2

criterion = nn.CrossEntropyLoss(weight=class_weights)
optimizer = AdamW(model.parameters(), lr=LR, weight_decay=0.01)

total_steps = len(train_loader) * EPOCHS
warmup_steps = int(total_steps * 0.1)
scheduler = get_linear_schedule_with_warmup(
    optimizer, num_warmup_steps=warmup_steps, num_training_steps=total_steps
)

print(f"类别权重: ignore={class_weights[0]:.3f}, should_enter={class_weights[1]:.3f}")
print(f"总步数: {total_steps}, warmup: {warmup_steps}")


# ═══════════════════════════════════════════════════════════════
# 训练循环
# ═══════════════════════════════════════════════════════════════

history = {"train_loss": [], "val_loss": [], "val_f1": []}
best_f1 = 0

from sklearn.metrics import f1_score

for epoch in range(EPOCHS):
    model.train()
    total_loss = 0
    for batch in tqdm(train_loader, desc=f"Epoch {epoch+1}/{EPOCHS}"):
        input_ids = batch["input_ids"].to(DEVICE)
        attention_mask = batch["attention_mask"].to(DEVICE)
        labels_b = batch["label"].to(DEVICE)

        optimizer.zero_grad()
        logits = model(input_ids, attention_mask)
        loss = criterion(logits, labels_b)
        loss.backward()
        optimizer.step()
        scheduler.step()

        total_loss += loss.item()

    avg_train_loss = total_loss / len(train_loader)

    model.eval()
    val_loss = 0
    all_preds, all_labels_list = [], []
    with torch.no_grad():
        for batch in val_loader:
            input_ids = batch["input_ids"].to(DEVICE)
            attention_mask = batch["attention_mask"].to(DEVICE)
            labels_b = batch["label"].to(DEVICE)

            logits = model(input_ids, attention_mask)
            loss = criterion(logits, labels_b)
            val_loss += loss.item()

            preds = torch.argmax(logits, dim=1)
            all_preds.extend(preds.cpu().numpy())
            all_labels_list.extend(labels_b.cpu().numpy())

    avg_val_loss = val_loss / len(val_loader)
    val_f1 = f1_score(all_labels_list, all_preds, average="binary")

    history["train_loss"].append(avg_train_loss)
    history["val_loss"].append(avg_val_loss)
    history["val_f1"].append(val_f1)

    print(f"\nEpoch {epoch+1}: train_loss={avg_train_loss:.4f}, val_loss={avg_val_loss:.4f}, val_f1={val_f1:.4f}")

    if val_f1 > best_f1:
        best_f1 = val_f1
        torch.save(model.state_dict(), "/tmp/best_relevance.pt")
        print(f"  → 保存最佳模型 (f1={best_f1:.4f})")

print(f"\n训练完成，最佳验证 F1: {best_f1:.4f}")


# ═══════════════════════════════════════════════════════════════
# 测试集评估
# ═══════════════════════════════════════════════════════════════

model.load_state_dict(torch.load("/tmp/best_relevance.pt"))
model.eval()

all_probs, all_preds, all_true = [], [], []
with torch.no_grad():
    for batch in test_loader:
        input_ids = batch["input_ids"].to(DEVICE)
        attention_mask = batch["attention_mask"].to(DEVICE)
        labels_b = batch["label"].to(DEVICE)

        logits = model(input_ids, attention_mask)
        probs = torch.softmax(logits, dim=1)[:, 1]
        preds = torch.argmax(logits, dim=1)

        all_probs.extend(probs.cpu().numpy())
        all_preds.extend(preds.cpu().numpy())
        all_true.extend(labels_b.cpu().numpy())

print("\n===== 测试集报告 =====\n")
print(classification_report(all_true, all_preds, target_names=["ignore", "should_enter"]))


# ═══════════════════════════════════════════════════════════════
# 导出模型
# ═══════════════════════════════════════════════════════════════

output_dir = Path(__file__).resolve().parent.parent / "__modles__" / "intent_router_bert_binary"
output_dir.mkdir(parents=True, exist_ok=True)

model.bert.save_pretrained(output_dir)
tokenizer.save_pretrained(output_dir)
torch.save(model.classifier.state_dict(), output_dir / "classifier.pt")

with open(output_dir / "classifier_config.json", "w", encoding="utf-8") as f:
    json.dump({"num_classes": 2, "dropout": 0.3}, f)

print(f"\n模型已导出到 {output_dir}")
