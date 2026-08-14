# Third-party notices / 第三方声明

Yuizaki source code is MIT-licensed. That license does not automatically cover character models, voices, fonts, artwork, downloaded weights, or services selected by the user.

Yuizaki 源代码采用 MIT 许可证，但角色模型、声音、字体、艺术素材、下载权重和用户选择的外部服务不自动继承该许可证。

## Runtime libraries / 运行时库

The Electron and Python dependency manifests are authoritative for package versions. They include Vue, Electron, Vite, Pinia, PixiJS, easy-live2d, Three.js, `@pixiv/three-vrm`, FastAPI, SQLAlchemy, Socket.IO, Sherpa ONNX, RapidOCR, Genie-TTS, and optional Qdrant/embedding clients. Review installed package metadata before redistributing a bundled build.

Electron 和 Python 依赖清单是版本的权威来源，包含 Vue、Electron、Vite、Pinia、PixiJS、easy-live2d、Three.js、`@pixiv/three-vrm`、FastAPI、SQLAlchemy、Socket.IO、Sherpa ONNX、RapidOCR、Genie-TTS 以及可选 Qdrant/嵌入客户端。重新分发构建包前，应核对精确安装包元数据。

## Avatar and media assets / 桌宠与媒体资源

Live2D Cubism models, VRM files, textures, motions, expressions, reference audio, fonts, and images may impose separate attribution, non-commercial, or redistribution terms. Keep downloaded assets outside source control unless their exact license explicitly permits inclusion.

Live2D Cubism 模型、VRM 文件、纹理、动作、表情、参考音频、字体和图片可能有独立的署名、非商业或再分发条款。除非精确许可证明确允许，否则将下载资源保留在源码控制之外。

## External services and models / 外部服务与模型

Ollama, LM Studio, OpenAI-compatible endpoints, Qdrant, SoulX services, MCP servers, and Hugging Face model repositories have their own terms. Yuizaki does not grant rights to those services or weights.

Ollama、LM Studio、OpenAI 兼容端点、Qdrant、SoulX 服务、MCP 服务和 Hugging Face 模型仓库各自拥有独立条款；Yuizaki 不授予这些服务或模型权利。

## Resource lock review / 资源锁核验

The downloadable resources in `resources.lock.json` have the following release boundary:

`resources.lock.json` 中的可下载资源具有以下发布边界：

| Resource / 资源 | Declared license / 声明许可证 | Source release / 源码发布 | Bundled installer / 安装包 |
| --- | --- | --- | --- |
| Sherpa SenseVoice archive | FunASR Model License | Keep URL and checksum only | Do not bundle by default; review model-card terms |
| Sherpa streaming Zipformer2 | Apache-2.0 | Keep dependency reference and notices | Permitted only with Apache notices and model terms |
| Qwen3 Embedding 0.6B | Apache-2.0 | Keep dependency reference and notices | Preserve Apache notice and Hugging Face model terms |
| Genie TTS 2.0.2 | MIT | Keep package reference and MIT notice | Package license is permissive; voices remain separate |
| SoulX Singer bundle | Apache-2.0 upstream declaration | Keep service integration and lock metadata | Do not bundle by default; verify every model/preprocess asset |

These are upstream declarations, not a legal opinion. Before publishing a binary, generate a license report from the exact lock files and ship the corresponding notices. Do not include downloaded model weights, user-provided voices, Live2D/VRM files, fonts, artwork, reference audio, local databases, logs, caches, or test screenshots unless their separate licenses and the release gate explicitly permit them.

以上是上游声明，不构成法律意见。发布二进制前，应根据精确锁文件生成许可证报告并附带相应声明。除非独立许可证与发布门槛明确允许，否则不得包含下载的模型权重、用户声音、Live2D/VRM 文件、字体、艺术素材、参考音频、本地数据库、日志、缓存或测试截图。
