# SoulX SVC 服务

该目录提供 Yuizaki 可选的 SoulX 音色转换服务。它不是桌宠基础启动的必需组件，建议在用户首次启用 SVC 或手动准备资源时下载。

## 组成

- `server.py`：HTTP 服务适配层
- `download_models.py`：从 Hugging Face 下载模型
- `Dockerfile`：CUDA 12.1 运行镜像
- `docker-compose.yml`：本地 GPU 服务
- `references/`：用户参考音频受管目录
- `models/`：下载或挂载的上游模型

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

默认服务地址由根目录 `python/.env` 的 `SVC_BASE_URL` 配置，默认 `http://127.0.0.1:7861`。

## 模型下载

```bash
python download_models.py --output-dir ./models
```

下载器支持指定 Hugging Face revision。发布构建必须使用不可变 commit hash，不应依赖默认分支：

```bash
python download_models.py --revision <commit-sha> --output-dir ./models
```

当前 Docker 构建参数 `SOULX_REF` 默认仍可能跟随 `main`。这是不可复现风险，发布前应固定到审计过的提交，并在资源锁中记录仓库、revision、模型 hash 和许可证。

## GPU

容器基于 `nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04`。需要：

- 兼容的 NVIDIA 驱动
- Docker 与 NVIDIA Container Toolkit
- Compose GPU device 配置可用

没有 GPU 时不要自动启动该容器；桌宠基础对话和普通 TTS/ASR 应保持可用。

## 数据与隐私

`references/` 可能包含用户声音，默认被 Git 忽略。参考音频不得进入镜像、日志、测试夹具或公开问题报告。删除参考音频是永久操作。

转换生成的临时文件应使用 Yuizaki 受管命名并由 cache janitor 清理，不得扫描或删除用户其他音频目录。

## 安全

- 服务默认仅绑定本机或受控容器网络。
- 不要把 7861 端口直接暴露到公网。
- 限制上传大小、格式与处理超时。
- 模型代码和依赖都视为供应链输入，固定 revision 并校验内容。
- 上游模型卡位于 `models/` 子目录，保留其授权说明。

## 健康检查

启动后先检查服务健康与模型加载，再由 Yuizaki 设置页执行 SVC 测试。失败应区分 GPU、依赖、模型缺失、参考音频和请求格式，而不是重复下载全部资源。
