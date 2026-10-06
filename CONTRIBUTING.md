# 为 Yuizaki 贡献 / Contributing to Yuizaki

感谢你帮助改进 Yuizaki。本项目是本地优先的桌面应用；贡献应保持这一边界，使变更易于审查，并为行为变化提供证据。

Thank you for helping improve Yuizaki. The project is a local-first desktop application; contributions should preserve that boundary, keep changes reviewable, and include evidence for behavior changes.

## 开始之前 / Before you start

请阅读：

- [README.md](README.md)：支持范围和安装方式。
- [SECURITY.md](SECURITY.md)：本地信任边界和安全报告。
- 添加资源、模型、字体或服务前阅读 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
- 修改进程或事件契约前阅读 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

Read:

- [README.md](README.md) for supported scope and installation.
- [SECURITY.md](SECURITY.md) for local trust boundaries and reporting.
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) before adding assets, models, fonts, or services.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) before changing process or event contracts.

不要提交 API 密钥、个人数据、聊天历史、截图、模型权重、音频缓存、数据库或日志。

Do not commit API keys, personal data, chat history, screenshots, model weights, audio caches, databases, or logs.

## 开发环境 / Development setup

从 `electron` 执行 `npm run prepare:launcher` 构建根目录启动器；首次运行会自动安装选定的 `core` 或 `full` 配置。

使用 `python/.venv` 中的项目 Python 环境。将 provider 凭据保存在已忽略的 `python/.env` 文件中。

Build the root launcher from `electron` with `npm run prepare:launcher`; its
first run installs the selected `core` or `full` profile automatically.

Use the project Python environment in `python/.venv`. Keep provider credentials in the ignored `python/.env` file.

## 验证 / Verification

先运行与变更最相关的检查；跨层变更再运行完整检查：

Run the smallest relevant checks first, then the full checks for cross-layer changes:

```powershell
python scripts/check_docs.py
cd electron
npm run type-check
npm run lint
npm run build
cd ..\python
.\.venv\Scripts\python.exe -m compileall -q modules app.py socket_server.py
```

Linux 使用 `python scripts/check_docs.py` 以及对应的 npm 命令。

对 Socket.IO 事件、Job 信封、取消、认证、存储删除、恢复或资源权限的修改必须进行针对性人工验证。依赖硬件或 provider 的行为必须明确真实设备限制。

Linux uses `python scripts/check_docs.py` and the equivalent npm commands.

Changes to Socket.IO events, Job envelopes, cancellation, authentication, storage deletion, restore, or resource permissions require targeted manual verification. Hardware- or provider-dependent behavior must include a clear real-device limitation.

## 拉取请求 / Pull requests

每个拉取请求只处理一个主题，并说明：

- 用户或运维人员可观察到的结果；
- 受影响的文件和进程边界；
- 已运行的测试和验证命令；
- 配置、迁移、许可证或安全影响；
- 已知限制和后续工作。

Keep one concern per pull request. Describe:

- the user-visible or operator-visible outcome;
- the files and process boundaries affected;
- tests and verification commands run;
- configuration, migration, license, or security implications;
- known limitations and follow-up work.

不要包含生成的构建输出或本地运行时状态。请求审查前检查 diff 中是否有机密和第三方资源。

Do not include generated build output or local runtime state. Review the diff for secrets and third-party assets before requesting review.

## 提交风格 / Commit style

提交标题应简洁、使用祈使语气，并尽量采用 conventional 前缀，例如：

Use concise imperative subjects with a conventional prefix when practical, for example:

- `docs: clarify local deployment boundary`
- `fix: reject stale voice events`
- `test: cover scheduler cancellation`

## 安全问题 / Security issues

涉及凭据、令牌泄露、未授权工具执行或数据泄露时，不要公开创建 Issue。请遵循 [SECURITY.md](SECURITY.md) 中的私下报告流程。

Do not open a public issue for credentials, token leakage, unauthorized tool execution, or data disclosure. Follow the private reporting guidance in [SECURITY.md](SECURITY.md).

## 许可证 / License

贡献代码即表示同意你的贡献按仓库许可证提供。第三方资源仍受其各自许可证约束。

By contributing, you agree that your contribution is provided under the repository license. Third-party assets remain subject to their own licenses.
