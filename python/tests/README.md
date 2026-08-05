# Python 测试

测试覆盖配置、认证、设置、记忆、摘要、实时协议、视觉、音频、工具、插件、资源清理和跨层契约。

## 运行

Windows：

```powershell
cd python
.\.venv\Scripts\python.exe -m pytest -q --tb=short
```

Linux：

```bash
cd python
.venv/bin/python -m pytest -q --tb=short
```

单文件：

```bash
python -m pytest -q tests/test_repository_contracts.py
python -m pytest -q test_settings_api_router.py
```

## 静态检查

```bash
ruff check . --select E9,F63,F7,F82
pyright --pythonversion 3.11
```

## 测试约定

- 文件系统测试使用临时目录，不写真实 `python/data`。
- 外部模型、Docker、网络和音频设备必须 mock 或显式标记为集成测试。
- 新增环境变量时同步更新 `.env.example`、[`ENVIRONMENT_SETUP.md`](../../docs/ENVIRONMENT_SETUP.md) 和仓库契约测试。
- 修改 Socket.IO 事件时同时验证事件名、payload 与取消行为。
- 修改永久删除或恢复逻辑时覆盖路径逃逸、符号链接和 dry-run。

CI 使用 Python 3.11、3.12 和 3.13 矩阵，安装对应平台的 `requirements-dev-lock-*` 后执行 Ruff、Pyright、完整 pytest 和离线模型评测；评测 JSON 会作为 Actions artifact 保存。
