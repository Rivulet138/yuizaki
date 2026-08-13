# SoulX SVC service / SoulX SVC 服务

SoulX SVC 是可选的本地 HTTP 变声服务。文本聊天、ASR 或默认 TTS 路径不依赖该服务。

SoulX SVC is an optional local HTTP voice-conversion service. It is not required for text chat, ASR, or the default TTS path.

## Start / 启动

Windows:

```powershell
.\start_soulx_svc.bat
```

Linux:

```bash
./start_soulx_svc.sh
```

Docker:

```bash
cd services/soulx-svc
docker compose up --build
```

在 `python/.env` 中设置 `SVC_BASE_URL`；默认值为 `http://127.0.0.1:7861`。

Set `SVC_BASE_URL` in `python/.env`; the default is `http://127.0.0.1:7861`.

## Models and hardware / 模型与硬件

模型下载体积较大且依赖服务商。请将检查点和参考音频保留在 Git 之外。下载或再分发前，审阅上游许可证及仓库 `resources.lock.json` 中对应条目。所选镜像可能需要 NVIDIA GPU、兼容驱动和 CUDA。

Model downloads are large and provider-specific. Keep checkpoints and reference audio outside Git. Review the upstream license and the repository `resources.lock.json` entry before downloading or redistributing anything. NVIDIA GPU, a compatible driver, and CUDA may be required by the selected image.

服务默认仅绑定本机。未经对认证、来源策略、资源限制和模型许可进行单独审查，不要将其公开暴露。

The service binds locally by default. Do not expose it publicly without a separate review of authentication, origin policy, resource limits, and model licensing.
