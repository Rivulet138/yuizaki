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
python scripts/check_resources.py
basedpyright --pythonversion 3.12
cd python
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/check_requirements_lock.py
.\.venv\Scripts\python.exe -m compileall -q modules routes socket_handlers tests app.py socket_server.py
cd ..\electron
npm audit --audit-level=low
npm run type-check
npm run lint
npm run test:unit
npm run build
npm run start:check
cd ..\node-mcp
npm ci
npm test
cd ..\tools\yuizaki-launcher
go test ./...
```

When the change touches memory, streaming, connectors, or voice, run the same replay gates CI uses (plus the fail-closed `platform_release_check.py` contract for release CLI changes):

```powershell
python scripts/memory_retrieval_check.py
python scripts/stream_staging_check.py
python scripts/connector_staging_check.py
python scripts/voice_comfort_check.py
```

以上命令假定 `python` 已指向项目环境；在 `python/` 目录内请使用 `.\.venv\Scripts\python.exe`。

These commands assume `python` already resolves to the project environment; inside `python/` use `.\.venv\Scripts\python.exe`.

文档变更也受契约检查约束：`scripts/check_docs.py` 校验维护文档集合、本地链接和禁止文本（明文凭据、未锁定镜像等）。修改默认值、端口、Launcher 参数、工作区行为或安全边界时，同步更新 `README.md`、`docs/` 与 `SECURITY.md`，不要只改其中一处。

Documentation changes are also contract-checked: `scripts/check_docs.py` validates the maintained document set, local links, and forbidden text such as plaintext credentials or unpinned images. When you change a default, port, launcher flag, workspace behavior, or security boundary, update `README.md`, `docs/`, and `SECURITY.md` together instead of only one of them.

CI also runs the documentation contract, the memory/streaming/connector/voice replay gates, basedpyright on Python 3.11-3.13, Electron validation on Windows and Linux, and the node-mcp contract tests. The release workflow additionally requires the `RELEASE_QUALIFIED` and `RELEASE_SIGNING_READY` repository variables and build attestations, so do not claim a release is qualified from local checks alone.

Linux 使用 `python scripts/check_docs.py` 以及对应的 npm 命令。

对 Socket.IO 事件、Job 信封、取消、认证、存储删除、恢复或资源权限的修改必须进行针对性人工验证。依赖硬件或 provider 的行为必须明确真实设备限制。

修改控制服务、插件生命周期或迁移 bootstrap 时，还应覆盖关闭期间的新请求、请求体解析取消、Windows 进程树等待、空库创建、可信旧 revision 升级和无 revision 数据库拒绝启动。测试应从迁移目录动态读取当前 head，不要硬编码日期型 revision。

Linux uses `python scripts/check_docs.py` and the equivalent npm commands.

Changes to Socket.IO events, Job envelopes, cancellation, authentication, storage deletion, restore, or resource permissions require targeted manual verification. Hardware- or provider-dependent behavior must include a clear real-device limitation.

Changes to the control service, plugin lifecycle, or migration bootstrap should also cover admission during shutdown, cancellation while parsing a request body, Windows process-tree wait behavior, empty-database creation, trusted old-revision upgrades, and rejection of databases without a revision. Tests should discover the current head from the migration directory instead of hard-coding date-based revision IDs.

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
