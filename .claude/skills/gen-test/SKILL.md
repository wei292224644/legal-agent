---
name: gen-test
description: 生成符合项目 conftest 模式和 fixture 约定的 pytest 测试骨架
disable-model-invocation: true
---

为给定模块生成 pytest 测试文件，遵循以下约定：

- 使用 `conftest.py` 中的 fixtures（`_preload_models`、音频 fixtures）
- 用 `AsyncMock`/`MagicMock` 模拟 LLM 调用
- async 测试使用 `pytest-asyncio`
- 超过 1 分钟的测试加 `@pytest.mark.slow`
- 遵循 ruff 行宽 120、双引号
- 测试意图必须体现「为什么要测这个」，而非仅验证行为
