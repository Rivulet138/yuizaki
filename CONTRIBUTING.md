# Contributing to Yuizaki / 为 Yuizaki 贡献

Thank you for helping improve Yuizaki. The project is a local-first desktop application; contributions should preserve that boundary, keep changes reviewable, and include evidence for behavior changes.

感谢你帮助改进 Yuizaki。本项目是本地优先的桌面应用；贡献应保持这一边界，使变更易于审查，并为行为变化提供证据。

## Before you start / 开始之前

Read:

请阅读：

- [README.md](README.md) for supported scope and installation.
- [SECURITY.md](SECURITY.md) for local trust boundaries and reporting.
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) before adding assets, models, fonts, or services.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) before changing process or event contracts.
- 修改进程或事件契约前阅读 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

Do not commit API keys, personal data, chat history, screenshots, model weights, audio caches, databases, logs, or pytest temporary directories.

不要提交 API 密钥、个人数据、聊天历史、截图、模型权重、音频缓存、数据库、日志或 pytest 临时目录。

## Development setup / 开发环境

Build the root launcher from `electron` with `npm run prepare:launcher`; its
first run installs the selected `core` or `full` profile automatically.

Use the project Python environment in `python/.venv`. Keep provider credentials in the ignored `python/.env` file.

使用 `python/.venv` 中的项目 Python 环境。将 provider 凭据保存在已忽略的 `python/.env` 文件中。

## Verification / 验证

Run the smallest relevant checks first, then the full checks for cross-layer changes:

```powershell
python scripts/check_docs.py
cd electron
npm run type-check
npm run lint
npm test
npm run build
cd ..\python
.\.venv\Scripts\python.exe -m pytest -q --tb=short
.\.venv\Scripts\python.exe -m compileall -q modules app.py socket_server.py
```

Linux uses `python scripts/check_docs.py`, the equivalent npm commands, and `.venv/bin/python -m pytest -q --tb=short`.

Changes to Socket.IO events, Job envelopes, cancellation, authentication, storage deletion, restore, or resource permissions require contract tests. Hardware- or provider-dependent behavior must include a mocked deterministic test plus a clear real-device limitation.

对 Socket.IO 事件、Job 信封、取消、认证、存储删除、恢复或资源权限的修改必须包含契约测试。依赖硬件或 provider 的行为必须包含确定性的模拟测试，并明确真实设备限制。

## Pull requests / 拉取请求

Keep one concern per pull request. Describe:

- the user-visible or operator-visible outcome;
- the files and process boundaries affected;
- tests and verification commands run;
- configuration, migration, license, or security implications;
- known limitations and follow-up work.

Do not include generated build output or local runtime state. Review the diff for secrets and third-party assets before requesting review.

不要包含生成的构建输出或本地运行时状态。请求审查前检查 diff 中是否有机密和第三方资源。

## Commit style / 提交风格

Use concise imperative subjects with a conventional prefix when practical, for example:

- `docs: clarify local deployment boundary`
- `fix: reject stale voice events`
- `test: cover scheduler cancellation`

## Security issues / 安全问题

Do not open a public issue for credentials, token leakage, unauthorized tool execution, or data disclosure. Follow the private reporting guidance in [SECURITY.md](SECURITY.md).

## License / 许可证

By contributing, you agree that your contribution is provided under the repository license. Third-party assets remain subject to their own licenses.

贡献代码即表示同意你的贡献按仓库许可证提供。第三方资源仍受其各自许可证约束。
