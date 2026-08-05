# 安全策略

## 支持范围

安全修复面向当前 `main` 分支。仓库尚未发布稳定版；旧提交不保证回溯修复。

## 报告漏洞

请使用私密 GitHub 仓库的 Security Advisory，提供受影响版本、复现步骤、影响范围和最小必要日志。不要在公开 issue 中提交密钥、个人截图、语音、数据库或可直接利用的细节。

## 信任边界

- Electron renderer 视为低信任 UI 环境，高权限操作必须经过 preload/IPC 或本地控制服务。
- Python 受保护路由要求 backend token，未认证本地开发只能显式开启。
- 外部模型、MCP、插件、网页和视觉内容均是不可信输入。
- 记忆、世界书、视觉和工具结果是带来源的数据块，不得覆盖系统策略。

## 本地服务

- 默认绑定 `127.0.0.1`。
- `YUIZAKI_ALLOWED_ORIGINS` 只列出实际前端来源。
- 不要把控制端口、Python 端口、Qdrant 或 SoulX 暴露到公网。
- 密钥不得写入 URL、日志、崩溃报告或 Git。
- `YUIZAKI_ALLOW_UNAUTHENTICATED_LOCAL_DEV=1` 只允许隔离开发环境使用。

## 文件与永久删除

备份恢复、资源导入、桌宠模型删除和存储清理必须限制在受管根目录，校验 resolved/real path 并拒绝符号链接逃逸。永久清理需要明确确认词，不能伪装成缓存刷新。

默认备份已包含 `chat.db` 与 `memory.db`。仓库外的自定义数据库不自动备份，部署方必须另行保护。

## 插件和工具

- 插件声明 route、tool、model 与 agent bridge 权限。
- 高影响工具在执行前请求用户许可，拒绝结果要可见。
- 插件不得直接获得 renderer 的 Node 权限。
- 陌生插件仍建议迁移到受限子进程，并增加签名、来源、资源配额与卸载清理。

## 屏幕与音频隐私

视觉默认关闭；启用后仅在 Agent 回合按需采集一帧并保存在内存中，按会话替换并过期。OCR 请求不建立 PNG 历史。任何未来的截图历史都必须显式启用、标明保留期并支持永久清理。

麦克风只有在按住说话或明确开启的语音模式下采集。打断应停止 LLM、TTS 和播放队列，避免后台继续生成敏感内容。

## 供应链

- npm 使用锁文件和 `npm ci`。
- Python 已使用 Windows/Linux 分离的直接依赖精确 lock；完整传递依赖 hash lock 仍待补齐。
- Qdrant 使用固定 tag，不使用可变 `latest`。
- Hugging Face 模型必须固定 commit revision。
- 直接下载归档必须校验 SHA-256。
- 发布前生成代码依赖与模型资源 SBOM。

当前 Sherpa 归档已固定 SHA-256，SoulX 与 Hugging Face 资源已固定 revision。正式发布仍需在目标平台验证下载、许可证和生成制品，并生成代码依赖与模型资源 SBOM。

## Electron 发布

保持受支持 Electron 小版本，启用 context isolation，限制导航、新窗口、权限请求和外部协议。正式分发需要平台签名、自动更新签名验证和最小权限安装包。
