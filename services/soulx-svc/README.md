# SoulX SVC

可选的 SoulX 音色转换服务。基础对话、ASR 和 TTS 不依赖该服务。

## 启动

Windows：

```powershell
.\start_soulx_svc.bat
```

Linux：

```bash
./start_soulx_svc.sh
```

Docker：

```bash
cd services/soulx-svc
docker compose up --build
```

服务地址由 `SVC_BASE_URL` 配置，默认 `http://127.0.0.1:7861`。

## 模型

```bash
python download_models.py --models-dir ./models
```

默认 revision 来自根目录 `resources.lock.json`。下载约需 9 GiB。

| 目录 | 内容 |
| --- | --- |
| `models/SoulX-Singer` | SVC checkpoint |
| `models/SoulX-Singer-Preprocess` | 预处理模型 |
| `references` | 用户参考音频 |

## 环境

- NVIDIA GPU 与兼容驱动
- Docker 与 NVIDIA Container Toolkit
- CUDA 12.1 运行环境

`references` 不进入镜像、日志或版本控制。服务保持本机访问，不直接暴露到公网。
