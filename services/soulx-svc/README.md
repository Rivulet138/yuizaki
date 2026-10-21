# SoulX SVC 服务 / SoulX SVC service

SoulX SVC 是可选的本地 HTTP 变声服务。文字聊天、ASR 和默认 TTS 路径不依赖它。

SoulX SVC is an optional local HTTP voice-conversion service. Text chat, ASR, and the default TTS path do not depend on it.

## 启动 / Start

使用 Docker： / With Docker:

```bash
cd services/soulx-svc
docker compose up --build
```

在 `python/.env` 中设置 `SVC_BASE_URL`，默认值为 `http://127.0.0.1:7861`。

Set `SVC_BASE_URL` in `python/.env`; the default is `http://127.0.0.1:7861`.

## 模型与硬件 / Models and hardware

模型下载体积较大且依赖服务商。请将检查点和参考音频保留在 Git 之外；下载或再分发前审阅上游许可证及 `resources.lock.json` 对应条目。所选镜像可能需要 NVIDIA GPU、兼容驱动和 CUDA。

Model downloads are large and provider-specific. Keep checkpoints and reference audio outside Git. Review the upstream license and the matching `resources.lock.json` entry before downloading or redistributing anything. The selected image may require an NVIDIA GPU, a compatible driver, and CUDA.

服务默认仅绑定本机。未经对认证、来源策略、资源限制和模型许可进行单独审查，不要将其公开暴露。

The service binds locally by default. Do not expose it publicly without a separate review of authentication, origin policy, resource limits, and model licensing.

## 认证与限制 / Authentication and limits

`SOULX_HOST` 默认为 `127.0.0.1`。当它不是回环地址时，`POST /convert` 要求 `Authorization: Bearer <SOULX_AUTH_TOKEN>`，且进程在缺少令牌时拒绝启动；`GET /health` 始终免认证，只返回设备与 FP16 状态。请通过 `SOULX_MAX_UPLOAD_BYTES`、`SOULX_MAX_STEPS`、`SOULX_MAX_CFG`、`SOULX_MAX_PITCH` 和 `SOULX_MAX_OUTPUT_BYTES` 限制资源使用。预处理的模型状态由进程内锁串行化，转换失败只返回通用错误，细节写入服务日志。

`SOULX_HOST` defaults to `127.0.0.1`. When it is not loopback, `POST /convert` requires `Authorization: Bearer <SOULX_AUTH_TOKEN>` and the process refuses to start without one; `GET /health` stays unauthenticated and returns only device/FP16 state. Bound resource use with `SOULX_MAX_UPLOAD_BYTES`, `SOULX_MAX_STEPS`, `SOULX_MAX_CFG`, `SOULX_MAX_PITCH`, and `SOULX_MAX_OUTPUT_BYTES`. Preprocess model state is serialized by an in-process lock, and conversion failures return a generic error while details go to the service log.
