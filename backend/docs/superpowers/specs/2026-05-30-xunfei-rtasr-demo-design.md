# 讯飞实时语音转写大模型 Demo 设计

## 背景与目标

当前系统采用本地 FunASR（paraformer-zh 转写 + cam++ 声纹提取 + 自研 SCD 切换检测）处理实时会谈音频。本 demo 旨在验证讯飞云端「实时语音转写大模型 + 声纹注册」方案是否能在效果或工程成本上优于现有本地方案。

验证维度：
1. 转写准确率（尤其法律领域术语）
2. 说话人分离准确度（与 cam++ 对比）
3. 接口延迟与稳定性
4. 工程维护成本（云端 vs 本地模型部署）

## 方案概述

采用独立 Python 脚本，零侵入现有业务代码，用已有测试音频离线调用讯飞接口，快速获取可对比的结果数据。

## 文件位置

`backend/scripts/demo_xunfei_rtasr.py`

## 核心流程

```
1. 加载测试音频（tests/fixtures/律师声纹注册.wav）
   → 转换为 16kHz、16bit、单声道 PCM 字节流

2. 声纹注册
   → 取音频 10s~60s 片段，标准 base64 编码
   → HTTP POST https://office-api-personal-dx.iflyaisol.com/res/feature/v1/register
   → Query: appId, accessKeyId, dateTime, signatureRandom + header signature
   → Body: audio_data, audio_type="raw", uid（可选）
   → 拿到 feature_id

3. 实时语音转写
   → 生成带签名的 WebSocket 握手 URL
   → 签名规则：参数按 key 升序 → URL 编码 → "key=value&" 拼接 → HmacSHA1(accessKeySecret) → Base64
   → 连接 wss://office-api-ast-dx.iflyaisol.com/ast/communicate/v1
   → 握手参数：appId, accessKeyId, uuid, utc, signature, lang=autodialect, audio_encode=pcm_s16le, samplerate=16000, role_type=2, feature_ids={feature_id}, pd=court
   → 按 40ms / 1280 字节分块发送音频 binary message
   → 音频发完后发送 JSON 结束标识：{"end": true, "sessionId": "..."}
   → 持续接收服务端 JSON 消息直到连接关闭

4. 结果解析与输出
   → action="started"：握手成功
   → action="result"：解析 data.cn.st.rt.ws.cw 数组
     - w：词文本
     - wb/we：词开始/结束时间（ms）
     - rl：角色分离标识（1/2/3... 切换说话人，0 继续上一说话人）
     - wp：词标识（n 普通词，p 标点，g 分段）
   → action="error"：打印错误码和描述
   → 终端格式化输出每句文本 + 说话人标签 + 时间范围
```

## 接口细节

### 声纹注册 HTTP 接口

- 地址：`POST https://office-api-personal-dx.iflyaisol.com/res/feature/v1/register`
- 请求头：`Content-Type: application/json`，`signature: {签名}`
- Query 参数（URL 中）：`appId`, `accessKeyId`, `dateTime`（`yyyy-MM-dd'T'HH:mm:ss±HHmm`）, `signatureRandom`
- Body：`{"audio_data": "base64...", "audio_type": "raw", "uid": "可选"}`
- 成功返回：`{"code": "000000", "data": {"feature_id": "...", "status": 1}}`

### 实时转写 WebSocket 接口

- 地址：`wss://office-api-ast-dx.iflyaisol.com/ast/communicate/v1?{参数}`
- 所有参数 key/value 均需 URL encode
- 音频要求：PCM 16bit、单声道、16kHz
- 发送频率：每 40ms 发送 1280 字节
- 超时：音频发送间隔超过 15s 服务端报错断开

### 签名算法

1. 收集所有请求参数（不含 signature）
2. 按参数名 ASCII 升序排序
3. 对每个 key 和 value 分别做 URL 编码
4. 拼接为 `key1=value1&key2=value2&...` 格式（注意最后无 &）
5. 以 `accessKeySecret` 为密钥，对拼接串做 HmacSHA1 加密
6. 对结果做 Base64 编码，得到最终 signature

## 可调参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `role_type` | 2 | 0=关闭分离，2=实时角色分离（盲分） |
| `feature_ids` | 注册结果 | 声纹 ID 列表，英文逗号分隔 |
| `eng_spk_match` | 不传 | 1=强制结果角色全部来自声纹库，0=关闭 |
| `pd` | court | 领域优化：court=法律 |
| `lang` | autodialect | autodialect=中英+202种方言，autominor=37语种 |
| `eng_vad_mdn` | 不传 | 1=远场，2=近场 |

## 输出格式

终端打印示例：

```
[声纹注册] feature_id: xxxx
[握手成功] sid: xxxx
[说话人1] 00:02.340 - 00:05.120
  您好，我是王律师。
[说话人2] 00:05.340 - 00:08.560
  您好，我是来咨询离婚财产分割的。
...
[完成] 总句数: 12, 平均延迟: xxx ms
```

## 依赖

- `websockets`：WebSocket 客户端
- `numpy`：音频数组处理
- `soundfile` 或标准库 `wave`：音频文件读取与重采样
- `python-dotenv`（可选）：从 `.env` 读取凭证

## 凭证管理

- 脚本不硬编码任何凭证
- 从环境变量读取：`XUNFEI_APPID`、`XUNFEI_APIKEY`、`XUNFEI_APISECRET`
- 或从 `backend/.env` 读取（`.env` 已在 `.gitignore` 中）

## 已知限制

1. 声纹注册要求音频 10s~60s，若测试音频时长不足需报错提示
2. 单说话人音频无法验证声纹分离效果，需用多说话人会话音频补充测试
3. 云端方案有网络延迟，本地无网络环境无法运行
4. 讯飞免费额度有限，频繁测试可能触发限流

## 验收标准

- [ ] 声纹注册成功并返回有效 feature_id
- [ ] WebSocket 握手成功，签名算法正确
- [ ] 音频完整发送后能收到 action=result 的确定性结果（type=0）
- [ ] 终端输出包含：每句文本、说话人标签、起止时间戳
- [ ] 开启 role_type=2 + feature_ids 后，rl 字段能正确反映说话人切换
- [ ] 脚本无硬编码凭证，可直接用环境变量运行
