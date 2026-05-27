"""Zero-shot binary intent classification with bge-large-zh + context."""

import time
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from collections import deque

# ── Intent definitions ──────────────────────────────────────────────────────────

INTENTS = {
    "none": (
        "日常问候、寒暄、闲聊、与法律完全无关的话题。"
        "如：你好、谢谢、再见、今天天气不错、吃饭了吗、我先接个电话、你们收费吗"
    ),
    "legal": (
        "任何涉及中国大陆法律事务的对话内容，包括但不限于："
        "劳动合同签订与解除、工资与加班费、社保公积金缴纳、工伤认定与赔偿、"
        "辞退与经济补偿、竞业限制、年假与病假、试用期规定、"
        "公司规章制度合法性、劳动仲裁与诉讼、证据收集、"
        "法律事实陈述（入职时间、合同情况、工资标准等）、"
        "法律问题咨询（违法吗、怎么办、赔多少、合法吗）"
    ),
}

# ── Test cases ──────────────────────────────────────────────────────────────────

CASES = [
    # === none ===
    ("你好", "none"),
    ("谢谢律师", "none"),
    ("今天天气真不错", "none"),
    ("我先去接个电话", "none"),
    ("你们这个服务收费吗", "none"),
    ("好的，我知道了", "none"),
    ("下次再约时间吧", "none"),

    # === legal (facts) ===
    ("我去年11月入职的", "legal"),
    ("公司没跟我签劳动合同", "legal"),
    ("已经干了半年了，工资照发", "legal"),
    ("每天加班到晚上9点，没给过加班费", "legal"),
    ("老板口头说下个月不用来了", "legal"),
    ("我社保从今年3月就没交过", "legal"),
    ("当时签了竞业限制协议", "legal"),
    ("工伤认定书下来了，但公司不认", "legal"),
    ("试用期三个月，月薪打八折", "legal"),
    ("公司说经营困难，全员降薪20%", "legal"),

    # === legal (questions) ===
    ("试用期最长不能超过多久", "legal"),
    ("公司不签合同怎么办", "legal"),
    ("加班费按什么标准算", "legal"),
    ("被辞退能拿多少补偿", "legal"),
    ("合同到期不续签有赔偿吗", "legal"),
    ("年假没休完离职可以折现吗", "legal"),
    ("工伤期间工资怎么发", "legal"),
    ("病假扣工资合法吗", "legal"),

    # === legal (complex) ===
    ("公司逼我签自愿离职，还威胁不给离职证明", "legal"),
    ("工伤后公司拒赔，认定一直拖着，要去哪里告", "legal"),
    ("竞业限制全国两年不让去同行，合法吗能打掉吗", "legal"),
    ("公司要裁我不给N+1，说可以转岗降薪，我能拒绝吗", "legal"),
    ("试用期最后一天被通知不通过，怀疑因为举报了财务违规", "legal"),
    ("外包两年，甲方要求转另一家外包，不转就自动离职", "legal"),
    ("公司改考勤每天工作10小时，说弹性工作制不算加班", "legal"),
]


class IntentRouter:
    def __init__(self, context_size: int = 3):
        self.model = SentenceTransformer("BAAI/bge-large-zh-v1.5")
        self.intent_names = list(INTENTS.keys())
        self.intent_embeddings = np.array([
            self.model.encode(desc, normalize_embeddings=True)
            for desc in INTENTS.values()
        ])
        self.context_size = context_size

    def build_input(self, context: list[str], current_text: str) -> str:
        recent = context[-self.context_size:]
        if recent:
            return "\n".join(recent) + "\n" + f"客户: {current_text}"
        return current_text

    def classify(self, text: str, context: list[str] | None = None) -> str:
        if context:
            text = self.build_input(context, text)
        emb = self.model.encode(text, normalize_embeddings=True)
        sims = cosine_similarity([emb], self.intent_embeddings)[0]
        return self.intent_names[int(np.argmax(sims))]

    def classify_with_scores(self, text: str, context: list[str] | None = None) -> list[tuple[str, float]]:
        if context:
            text = self.build_input(context, text)
        emb = self.model.encode(text, normalize_embeddings=True)
        sims = cosine_similarity([emb], self.intent_embeddings)[0]
        return sorted(
            zip(self.intent_names, sims), key=lambda x: x[1], reverse=True
        )


def main():
    print("Loading bge-large-zh-v1.5...")
    t0 = time.time()
    router = IntentRouter()
    print(f"  Loaded in {time.time()-t0:.1f}s")

    # ── Test without context ─────────────────────────────────────────────────
    print("\n=== 无上下文（单句）===\n")
    y_true, y_pred = [], []
    for text, expected in CASES:
        pred = router.classify(text)
        y_true.append(expected)
        y_pred.append(pred)
        scores = router.classify_with_scores(text)
        score_str = " | ".join(f"{n}:{s:.3f}" for n, s in scores)
        status = "✓" if pred == expected else "✗"
        print(f"  {status} {text[:55]}")
        if pred != expected:
            print(f"       {score_str}")

    acc = sum(1 for t, p in zip(y_true, y_pred) if t == p) / len(y_true)
    print(f"\n  准确率: {acc:.1%}")

    # ── Test with context ────────────────────────────────────────────────────
    print("\n\n=== 模拟对话上下文 ===\n")
    context = deque(maxlen=3)

    DIALOGUE = [
        ("你好，请问有什么可以帮助您的？", "律师", "none"),
        ("我去年11月入职的，公司没跟我签合同", "客户", "legal"),
        ("好的，还有其他情况吗？", "律师", "none"),
        ("还有就是每天加班，不给加班费", "客户", "legal"),
        ("了解了。那您在公司干了多久了？", "律师", "none"),
        ("已经半年了，工资倒是照发的", "客户", "legal"),
        ("合同没签的话，您有什么想问的吗？", "律师", "none"),
        ("公司不签合同，我能告他们吗", "客户", "legal"),
    ]

    d_true, d_pred = [], []
    for text, speaker, expected in DIALOGUE:
        context.append(f"{speaker}: {text}")
        pred = router.classify(text, list(context))

        if speaker == "客户":
            d_true.append(expected)
            d_pred.append(pred)

        scores = router.classify_with_scores(text, list(context))
        score_str = " | ".join(f"{n}:{s:.3f}" for n, s in scores)
        status = "✓" if pred == expected else "✗"
        print(f"  {status} [{speaker}] {text[:55]}")
        if pred != expected:
            print(f"       {score_str}")

    d_acc = sum(1 for t, p in zip(d_true, d_pred) if t == p) / len(d_true)
    print(f"\n  客户话语准确率: {d_acc:.1%}")

    # ── Latency stats ────────────────────────────────────────────────────────
    print("\n=== 延迟统计 ===")
    times = []
    for _ in range(100):
        t0 = time.perf_counter()
        router.classify("公司不签合同怎么办")
        times.append((time.perf_counter() - t0) * 1000)
    print(f"  平均: {np.mean(times):.1f}ms, P50: {np.median(times):.1f}ms, "
          f"P99: {np.percentile(times, 99):.1f}ms")


if __name__ == "__main__":
    main()
