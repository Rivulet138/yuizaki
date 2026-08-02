# 依赖维护

安装脚本使用平台 lock 文件：Windows 为 `requirements-lock-windows.txt`，Linux 为 `requirements-lock-linux.txt`；核心和开发环境使用对应的 `requirements-core-lock-*` 与 `requirements-dev-lock-*`。模型评测见 [MODEL_EVALUATION.md](MODEL_EVALUATION.md)。

## 基线

| 范围 | 当前基线 | 策略 |
| --- | --- | --- |
| Electron | 42.x | 保持当前主版本最新补丁 |
| Node.js | 22.13+ | 新环境建议 24 LTS |
| Python | 3.11–3.13 | 兼容旧环境；新环境优先 3.12/3.13，并使用 `python/.venv` |
| Vue/Vite | Vue 3、Vite 8 | 主版本升级单独验证 |
| Qdrant | 1.18.3 | 使用固定镜像标签 |

Node 22.13 是当前工具链的实际安全下限：Electron 42 的安装工具要求 Node 22.12 以上，ESLint 10 在 Node 22 分支要求 22.13 以上。Node 20 已停止维护，因此不通过回退 Electron 或开发工具来换取 Node 20 兼容。

完整组件见 [TECH_STACK.md](TECH_STACK.md)。

## 安装

Node 项目使用锁文件：

```bash
cd electron && npm ci
cd node-mcp && npm ci
```

Python：

Windows 完整安装使用 `requirements-lock-windows.txt`，Linux 完整安装使用 `requirements-lock-linux.txt`；核心安装和开发环境分别使用对应的 `requirements-core-lock-*` 与 `requirements-dev-lock-*`。安装后必须运行 `pip check`。
Python 3.11 可使用当前直接依赖版本；完整 TTS 栈中的 `jieba_fast` 仅提供源码包，因此需要 Windows C++ Build Tools 或 Linux `build-essential`。只需要基础后端时可使用 core lock 避开该编译步骤。

`requirements-core.txt`、`requirements.txt` 和 `requirements-dev.txt` 是版本范围 manifest；六个平台 lock 文件对其直接依赖做精确版本 pin。`python/scripts/check_requirements_lock.py` 会在 CI 中双向检查 manifest 与 lock 的包集合、重复项和显式固定版本漂移；安装后 `python scripts/check_installed_lock.py --lock <lock-file>` 会核对当前 venv 的已安装版本。当前 lock 不是包含所有传递依赖及 hash 的完整供应链锁；若需要离线重建和更强的供应链证明，下一步应生成按平台/架构拆分的 hash lock 并提交 wheelhouse/SBOM。

模型和模型敏感运行时使用 `resources.lock.json`。Genie TTS 固定 Python 包与模型 commit；ASR 归档固定 SHA-256；Hugging Face 资源固定 commit。直接调用的 `huggingface-hub` 在 `python/requirements.txt` 显式声明，不依赖传递安装。

## 更新规则

- 补丁和同主版本更新：通过测试与构建后合并。
- Electron、Vue、Vite、TypeScript、Pinia 主版本：独立升级。
- ASR、TTS、OCR、嵌入依赖：验证模型加载、首段延迟和打断。
- Qdrant：验证现有记忆、索引和备份。
- 不使用 `latest` 容器标签。

## 发布要求

- npm 使用提交的 lockfile。
- Python 生成 Windows/Linux 分离的精确版本锁文件；发布环境逐步补充传递依赖 hash 和 wheelhouse。
- `python scripts/check_resources.py` 验证模型来源、revision 和 SHA-256。
- 生成代码依赖和模型资源 SBOM。
- 保留模型、字体、角色与声音的许可证。

当前已启用 Dependabot。
