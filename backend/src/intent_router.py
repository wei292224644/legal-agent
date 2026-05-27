"""BERT-based intent router for legal dialogue filtering.

Uses bge-large-zh-v1.5 for zero-shot binary classification (legal vs none).
Latency: ~21ms per classify call, model loaded once at init.
"""

import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity


INTENT_DESCRIPTIONS = {
    "none": (
        "日常问候、寒暄、闲聊、与法律完全无关的话题。"
        "如：你好、谢谢、再见、今天天气不错、吃饭了吗、接电话"
    ),
    "legal": (
        "任何涉及中国大陆法律事务的对话内容，包括："
        "劳动合同签订与解除、工资与加班费、社保公积金、工伤认定与赔偿、"
        "辞退与经济补偿、竞业限制、年假与病假、试用期、"
        "公司规章制度、劳动仲裁与诉讼、证据收集、"
        "法律事实陈述（入职时间、合同情况、工资标准）、"
        "法律问题咨询（违法吗、怎么办、赔多少、合法吗）"
    ),
}


class IntentRouter:
    def __init__(self, model_name: str = "BAAI/bge-large-zh-v1.5"):
        self._model = SentenceTransformer(model_name)
        self._intent_names = list(INTENT_DESCRIPTIONS.keys())
        self._intent_embeddings = np.array([
            self._model.encode(desc, normalize_embeddings=True)
            for desc in INTENT_DESCRIPTIONS.values()
        ])

    def classify(self, text: str) -> str:
        emb = self._model.encode(text, normalize_embeddings=True)
        sims = cosine_similarity([emb], self._intent_embeddings)[0]
        return self._intent_names[int(np.argmax(sims))]

    @property
    def legal_label(self) -> str:
        return "legal"

    @property
    def none_label(self) -> str:
        return "none"
