## 后端代码审阅报告

**审阅范围：** `backend/src/` + `backend/main.py` + 关键测试文件
**审阅维度：** 架构完善性、逻辑完整性、过度判断/嵌套、类型安全、隐藏漏洞、错误监听

---

## 审阅概览

整体架构清晰，分层合理（Agent / DB / Diarization / Repository / Session / STT），事件驱动设计解耦良好。Orchestrator 作为纯机械管道的定位准确，Repository 模式隔离了数据访问。但存在**测试文件严重过时**、**生产代码混用 print**、**CORS 配置安全隐患**等必须修复的问题。

---

## 亮点

- **分层清晰**：STT → Bus → Orchestrator → (Gate + PA + HA) 的流水线职责分明，main.py 只做接线。
- **错误降级策略成熟**：Gate 失败按 False 处理、PA 失败只打日志不阻塞、_spawn_inflight 的 done_callback 捕获未处理异常。
- **会话恢复机制完整**：SessionManager 支持 WS 重连时的 runtime 复用，detach_ws 带竞态保护。
- **事件契约统一**：OutboundEvent 用 Pydantic 的 Annotated Union + discriminator，类型安全且易于扩展。
- **Repository 原子操作**：每个方法独立 session + commit，调用方无需管理事务边界。

---

## 需要关注的问题

### 🔴 [blocking] `e2e_full_pipeline.py` 引用已废弃模块，完全无法运行

`tests/e2e_full_pipeline.py:52` 仍 `from agent.intent_router import IntentRouter`，但项目中该模块已被 `agent.relevance_gate.RelevanceGate` 取代。此外第111行 `HeavyAgent(ctx)` 缺少必须的 `session_id` 和 `user_id` 参数（`__init__` 签名要求）。

**后果**：该 E2E 测试一运行即 ImportError / TypeError，全链路回归能力失效。

**修复**：
1. 将 `IntentRouter` 引用改为 `RelevanceGate`
2. `HeavyAgent(ctx)` 改为 `HeavyAgent(ctx, session_id=..., user_id=...)`
3. 确认 `jlogger.wrap_ir/wrap_pa/wrap_ha` 接口与新类兼容

---

### 🔴 [blocking] `funasr_stream.py` 生产代码使用 `print()` 输出诊断信息

第255、313、325、329、332行大量使用 `print(...)`。生产环境无法分级、过滤和重定向，且高并发时 stdout 竞争会导致日志乱序。

**修复**：全部替换为 `logger.debug(...)` 或 `logger.info(...)`，由调用方通过 `logging.basicConfig` 控制级别。

---

### 🔴 [blocking] CORS 配置 `allow_origins=["*"]` + `allow_credentials=True` 存在安全隐患

`main.py:47-52`：当 `allow_credentials=True` 时，浏览器会拒绝 `Origin: *` 的通配符 CORS 响应（带 cookie/token 的请求不允许通配符）。FastAPI 虽然不会报错，但前端在特定场景下会遭遇 CORS 失败。更关键的是，若后续前端需要携带认证信息，此配置会成为障碍。

**修复**：将 `allow_origins` 改为显式的前端域名白名单（如 `http://localhost:5173`），或在开发环境保留 `*` 但将 `allow_credentials=False`。

---

### 🟡 [important] `ContextStore._profile_worker` 异常日志缺少 traceback

`src/agent/context_store.py:150-151`：
```python
except Exception as exc:
    logger.warning("Profile worker dropped entry: %s", exc)
```

只打印了异常消息，没有 `exc_info=True`。画像 worker 是后台异步任务，失败时若只看日志很难定位问题源。

**修复**：改为 `logger.warning("...", exc, exc_info=True)` 或 `logger.exception(...)`。

---

### 🟡 [important] `Orchestrator.confirm_analysis` 中 requirement 部分 confirm 失败后仍继续运行

`src/agent/orchestrator.py:302-307`：
```python
for req in pending.run_output.active_requirements or []:
    try:
        req.confirm()
    except Exception:
        logger.warning("requirement.confirm() failed", exc_info=True)
```

如果某个 `req.confirm()` 失败，循环继续，后续仍会调用 `acontinue_run`。但 Agno 的语义是：所有 active_requirements 都必须 confirm 后才能 continue。部分 confirm 可能导致 run 状态不一致，甚至 `acontinue_run` 内部抛不可预期的异常。

**修复**：若任一 confirm 失败，应立即 `_abandon_run(pending)` 并返回 False，不要继续跑。

---

### 🟡 [important] `VoiceprintState` / AutoModel 单例缺乏并发保护

`src/diarization/voiceprint.py:18-22` 和 `src/stt/funasr_stream.py:39-45` 的全局单例 `_model`、`_vad_model`、`_asr_model` 均无锁保护。虽然 asyncio 是单线程的，但 `asyncio.to_thread` 会把模型推理扔到线程池。若多个流同时触发首次加载，`if _model is None:` 判定和赋值之间可能产生竞争，构造多个 AutoModel 实例。FunASR 的底层 PyTorch 模型并发 init 可能不稳定。

**修复**：用 `threading.Lock()` 或 `asyncio.Lock()` 保护单例初始化。

---

### 🟡 [important] `main.py` WS handler 的 `finally` 块过度 suppress Exception

`main.py:391-407` 中连续使用 `with contextlib.suppress(Exception):`。虽然这是为了确保清理链完整，但 `suppress(Exception)` 会吞掉 **所有** 异常——包括编程错误（NameError、AttributeError）。这意味着如果清理代码本身有 bug，日志中完全不会体现。

**修复**：将 `Exception` 缩小为预期的异常类型，如 `(RuntimeError, asyncio.CancelledError, OSError)`。对 truly unexpected 的异常仍应至少打一行 `logger.exception`。

---

### 🟡 [important] `PendingRequest.run_output: Any` 和 `SessionRuntime.ctx: object` 类型逃逸

`src/agent/orchestrator.py:74` 和 `src/session/models.py:19-20` 使用了 `Any` / `object` 作为类型注解。虽然注释解释了原因（Agno RunOutput 无法序列化、避免循环导入），但 `Any` 会绕过静态类型检查的所有保护。

**修复建议**：
- `SessionRuntime` 可用 `TYPE_CHECKING` 导入真实类型，或定义一个轻量 Protocol。
- `PendingRequest.run_output` 可用 `typing.Protocol` 描述 Agno RunOutput 的最小接口（`is_paused`、`run_id`、`active_requirements`、`requirements` 等），不需要依赖 Agno 包。

---

### 🟡 [important] `orchestrator.py` `requirements` 参数缺失类型注解

`src/agent/heavy_agent.py:72`：
```python
async def acontinue_run(self, run_id: str, requirements):
```

`requirements` 没有类型。结合 `orchestrator.py:303` 的使用方式 `pending.run_output.requirements`，调用方无法通过类型检查确认传参正确。

**修复**：标注为 `list[Any] | None` 或定义 Protocol。

---

### 🟢 [nit] `ProfileAgent.extract` 参数 `history: list` 无泛型

`src/agent/profile_agent.py:40`：`history: list` 应改为 `list[Utterance]` 以匹配实际使用。

---

### 🟢 [nit] `_DbRepoWriter` 参数类型缺失

`main.py:197-198`：`preview_topic, preview_rationale` 无类型标注。应为 `str | None`。

---

### 🟢 [nit] `orchestrator.py` `_run_child` 嵌套可简化

当前 `_run_child` 先 `asyncio.create_task(self._ha.arun(utt))` 再 `await asyncio.wait_for(task, timeout=...)`。可以直接：
```python
run = await asyncio.wait_for(self._ha.arun(utt), timeout=RUN_TIMEOUT)
```

但当前写法是为了在 TimeoutError 后能 `task.cancel()`。实际上 `asyncio.wait_for` 超时后已经会 cancel 内部的 future。额外包一层 `create_task` 的必要性不足，多了一层嵌套。

---

### 🟢 [nit] `funasr_stream.py` / `funasr_stream_v2.py` `spec_asr` dict 没有清理机制

如果某个 ASR task 因为边界抖动创建了 key 但从未被 `await`（比如 VAD 结果在后续轮次中偏移了，旧的 key 不再匹配），该 task 会一直留在 `spec_asr` 中直到 stream 结束。stream 末尾会 `task.cancel()`，但在长会话中可能累积大量未消费的 task。

**修复**：在 `_emit_stable_or_final` 中定期清理 `spec_asr` 里比 `yielded_until_ms` 早很多（如 >10s）的陈旧 task。

---

## 隐藏漏洞专项

| 位置 | 风险 | 严重程度 |
|------|------|----------|
| `main.py` CORS | `allow_origins=["*"]` + `allow_credentials=True` 在浏览器层可能失效，且过度开放 | 中 |
| `voiceprint.py` / `funasr_stream.py` 单例 | 并发 init 竞争可能导致多实例或底层崩溃 | 中 |
| `orchestrator.py` confirm 部分失败 | 部分 requirement confirm 后 continue_run 可能状态不一致 | 中 |
| `context_store.py` profile_worker | 异常无 traceback，后台静默丢数据 | 低 |
| `e2e_full_pipeline.py` | 引用废弃模块，回归测试完全失效 | **高** |

---

## 错误监听能力评估

| 层级 | 机制 | 评价 |
|------|------|------|
| **WS 层** | `main.py` `logger.exception` + `contextlib.suppress` | 良好，异常不会杀进程 |
| **STT 层** | `consume_stt` 外包裹 try/except + logger.exception | 良好，stream 崩溃可观测 |
| **Orchestrator 层** | `_spawn_inflight` done_callback 捕获未处理异常；`_safe_gate` 降级为 False | **优秀**，所有分支都有降级策略 |
| **Agent 层** | `ProfileAgent.extract` 异常由 Orchestrator catch；`HeavyAgent` 异常由 `_run_child` catch | 良好 |
| **DB 层** | Repository 每个操作独立 commit，异常向上抛，由调用方处理 | 良好 |
| **画像 Worker** | 异常被 catch 但 **无 traceback**，后台静默丢数据 | **待改进** |
| **TTL 扫描** | 异常被 catch 且打 log | 良好 |

---

## 结论

**整体评价**：架构设计成熟，错误降级策略完善，核心路径上的异常监听和恢复能力较强。

**阻塞项（必须修）**：
1. `e2e_full_pipeline.py` 废弃引用修复
2. `funasr_stream.py` 所有 `print` 改为 `logger`
3. `main.py` CORS `allow_origins` 收紧或关闭 `allow_credentials`

**重要项（建议修）**：
4. `profile_worker` 异常加 `exc_info=True`
5. `confirm_analysis` 部分 confirm 失败后立即 abandon
6. AutoModel 单例加锁保护
7. `finally` 块 `suppress(Exception)` 缩小范围
8. `Any` / `object` 类型逃逸用 Protocol 收敛

**次要项**：补齐部分函数参数的类型注解；清理 `spec_asr` 陈旧 task。
