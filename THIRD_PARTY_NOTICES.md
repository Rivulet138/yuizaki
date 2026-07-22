# 第三方组件与素材

本文说明项目级授权边界，不替代各组件许可证。

## 源代码依赖

主要代码依赖包括 Electron、Vue、Vite、Pinia、Element Plus、PixiJS、Three.js、easy-live2d、uiohook-napi、FastAPI、Socket.IO、Genie TTS、Sherpa ONNX、RapidOCR、Qdrant client、sentence-transformers、Express 与 Playwright。

准确版本以以下锁或环境产物为准：

- `electron/package-lock.json`
- `node-mcp/package-lock.json`
- `python/requirements-*-lock-*.txt`
- `resources.lock.json`

项目尚需自动生成 SPDX/CycloneDX SBOM。依赖版本和升级策略见 [DEPENDENCIES.md](DEPENDENCIES.md)。

## Live2D

仓库包含 Live2D Cubism 运行时文件及角色资源。Live2D Cubism Core、SDK、模型和纹理可能适用不同许可。模型可在本机运行不等于允许公开再分发、商业使用或修改后发布。

发布者必须逐项确认：

- Cubism runtime 的再分发条件
- 每个模型与纹理的作者、来源和用途限制
- 角色形象的商用、二创和训练限制

## VRM

VRM 文件可能携带模型级许可和人格使用限制。导入功能不会自动授予分发权。应保留模型元数据与原始许可证，不得在清理资源时只留下模型文件而删除授权说明。

## 字体与图片

字体声明位于 `electron/src/renderer/public/assets/font/MIZUKI-FONTS-NOTICE.md`。角色图片、图标和背景图必须建立来源清单。项目 MIT 许可证不覆盖这些素材。

## 模型与数据

按需下载的 ASR、TTS、嵌入、SoulX 和其他模型受各自模型卡、数据集和服务条款约束。资源清单应记录：

- 资源 ID 与用途
- 上游 URL 与不可变 revision
- SHA-256
- 许可证/模型卡位置
- 是否允许再分发和商用
- 是否包含声音、角色或数据集限制

当前默认模型清单、revision、SHA-256 和许可证入口位于 `resources.lock.json`。

仓库内 `services/soulx-svc/models/` 的 README 属于上游模型卡，保留原文，不作为项目自有授权声明。

## 用户内容

参考音频、截图、对话、长期记忆和导入角色属于用户数据。默认不应进入源代码、测试夹具、遥测或公开构建。问题报告必须去除可识别个人信息和密钥。

## 分发检查

公开或商业分发前必须完成：

1. 生成代码依赖 SBOM。
2. 生成模型与素材资源清单。
3. 对每项资源记录授权结论。
4. 删除无权分发的内置资源，改为用户自行导入或从授权渠道下载。
5. 在安装包中附带所有必要 notice 与许可证。
