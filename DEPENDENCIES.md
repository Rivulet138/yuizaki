# 依赖治理

维护基线：2026-07-19。

## 运行时基线

| 层 | 当前策略 | 维护意见 |
| --- | --- | --- |
| Electron | `^42.7.0` | 保持 42 系最新补丁；43 作为独立升级验证 |
| Node.js | `>=22.13.0` | 新环境优先 Node 24 LTS，Node 22 仅保留兼容 |
| Python | 3.12 | 原生模型兼容稳定；新增 3.13/3.14 CI 前不宣称支持 |
| Vue/Vite | 锁文件固定 | 同主版本补丁可批量验证，主版本单独迁移 |
| Qdrant | `v1.18.3` | 禁止 `latest`，升级时运行记忆读写回归 |

Electron 的 `@types/node` 对齐内置 Node 24，不跟随系统 Node 的最新主版本。

## 安装契约

Electron 与 Node MCP 使用提交的 `package-lock.json`：

```bash
cd electron && npm ci
cd node-mcp && npm ci
```

`npm ci` 是 CI 和干净复现的唯一安装方式；本地 `npm install` 只用于明确升级并提交锁文件。

Python 当前由 `requirements.txt` 和 `requirements-dev.txt` 的范围约束安装，尚未提供哈希锁。这是现阶段最大的依赖可复现性缺口。建议增加按平台生成的约束文件：

- `requirements-lock-windows.txt`
- `requirements-lock-linux.txt`
- 每项使用精确版本与 `--hash`
- CPU 与 CUDA 模型依赖拆分，避免一个锁文件覆盖所有硬件组合

在锁文件完成前，发布构建必须保存 `python -m pip freeze` 产物和 Python/驱动信息。

## 自动更新

`.github/dependabot.yml` 每周检查两个 npm 项目和 Python 依赖，每月检查 Docker 与 GitHub Actions。合并规则：

1. 同主版本补丁：通过 CI、启动检查和资源冒烟后合并。
2. Electron、Vite、Vue Router、Pinia、TypeScript 主版本：单独 PR，记录迁移影响。
3. ASR/TTS/嵌入依赖：必须执行模型加载、首段延迟和打断测试。
4. Qdrant：必须验证现有 collection、备份恢复与重新索引。

## 当前审计结果

- Electron 和 Node MCP 的 `npm audit`：0 个已知漏洞。
- Python `pip check`：无破损依赖。
- Electron 已用 `npm ci` 从锁文件干净重建。`npm ls` 仍把 5 个 WASM helper 标为 extraneous；它们来自 Rolldown/Tailwind 的可选 WASM 包布局，可由干净安装稳定复现，不是未知手工依赖。
- 安装会提示 `glob@10.5.0` 过时；来源是仅开发使用的 `@vue/test-utils -> js-beautify` 间接依赖，当前 `npm audit` 无漏洞。应等待上游替换，不要用 override 强压不兼容版本。
- Python 虚拟环境与模型缓存占用大，不能与源代码仓库一起备份或打包。

## 模型与下载依赖

Hugging Face 下载必须固定 `revision` 到提交哈希；直接下载压缩包必须记录 URL、版本、SHA-256、许可证和解压目标。当前 Sherpa 下载尚未具备完整校验清单，SoulX 默认 `main` 也不可复现，均列为 P0 改进项。

建议新增机器可读 `resources.lock.json`，由资源管理器校验后再标记 ready。字段至少包括：

```json
{
  "id": "resource-id",
  "source": "download URL or repository",
  "revision": "immutable revision",
  "sha256": "content digest",
  "license": "SPDX or upstream notice",
  "target": "managed relative path"
}
```

## 发布供应链

后续发布门禁应增加：

- npm 与 Python SBOM
- GitHub dependency review
- Python 哈希锁验证
- 下载模型清单与内容校验
- Electron 安装包签名和可复现版本元数据

第三方授权边界见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
