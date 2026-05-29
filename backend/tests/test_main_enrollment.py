"""回归 main.py 的 enrollment 跨会话污染 bug。

matcher 的双声纹自举会写回 enrollment.client_embedding；若所有会话共享
同一个全局单例对象，会话 A 的客户声纹种子会泄漏污染会话 B 的说话人判定。
每个会话必须拿到独立副本。
"""

import numpy as np

import main
from diarization.enrollment import Enrollment


def test_each_session_gets_independent_enrollment(monkeypatch):
    base = Enrollment(embedding=np.array([1.0, 0.0, 0.0], dtype=np.float32))
    monkeypatch.setattr(main, "_lawyer_enrollment", base)

    e1 = main._session_enrollment()
    e2 = main._session_enrollment()

    # 模拟会话 A 的双声纹自举写回 client seed
    e1.client_embedding = np.array([0.0, 1.0, 0.0], dtype=np.float32)

    assert e1 is not e2
    assert e2.client_embedding is None, "会话间不应共享 client_embedding"
    assert base.client_embedding is None, "基准 enrollment 不应被会话污染"
