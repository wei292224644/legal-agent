# Handoff: legal-agent — T10 声纹注册后端 API

**日期:** 2026-05-26 | **分支:** main | **前置任务:** T7

## 任务目标

实现 `POST /api/voiceprint/register` — 接收律师朗读音频，提取声纹 embedding，持久化存储。

## 依赖

- T7 中的 pyannote embedding 模型已就绪
- 前端 VoiceprintRegister 页面已实现（`frontend/src/pages/VoiceprintRegister.tsx`）

## 文件

```
backend/voiceprint.py  — 新增
```

## API 设计

```
POST /api/voiceprint/register
Content-Type: multipart/form-data

请求:
  audio: File (webm/wav, ~15s 朗读音频)
  user_id: string

响应 200:
  { "status": "ok", "user_id": "xxx", "embedding_size": 256 }

响应 400:
  { "status": "error", "message": "音频时长不足，需要至少10秒" }
```

## 实现要点

```python
from pyannote.audio import Model
import numpy as np

# 加载模型（模块级，启动时加载一次）
embedding_model = Model.from_pretrained("pyannote/embedding")

def extract_voiceprint(audio_path: str) -> np.ndarray:
    """从音频文件提取 256 维声纹向量"""
    ...

def save_voiceprint(user_id: str, embedding: np.ndarray):
    """存储为 voiceprints/{user_id}.npy"""
    ...

def compare_voiceprint(embedding: np.ndarray, stored: np.ndarray) -> float:
    """余弦相似度，>0.85 判定为同一人"""
    ...
```

## 测试

- 正常注册：15s 音频 → embedding 非空 → 文件落盘
- 音频太短 <10s → 返回 400
- 重复注册 → 覆盖旧声纹
- 比对同一个人 → 相似度 >0.85
- 比对不同人 → 相似度 <0.50

## 估时

human ~30min / CC ~10min
