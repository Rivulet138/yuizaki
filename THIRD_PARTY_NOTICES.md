# 第三方声明 / Third-party notices

Yuizaki 源代码采用 MIT 许可证，但角色模型、声音、字体、艺术素材、下载权重和用户选择的外部服务不自动继承该许可证。

Yuizaki source code is MIT-licensed. That license does not automatically cover character models, voices, fonts, artwork, downloaded weights, or services selected by the user.

## 运行时库 / Runtime libraries

Electron 和 Python 依赖清单是版本的权威来源，包含 Vue、Electron、Vite、Pinia、PixiJS、easy-live2d、Three.js、`@pixiv/three-vrm`、FastAPI、SQLAlchemy、Socket.IO、Sherpa ONNX、RapidOCR、Genie-TTS 以及可选 Qdrant/嵌入客户端。重新分发构建包前，应核对精确安装包元数据。

The Electron and Python dependency manifests are authoritative for package versions. They include Vue, Electron, Vite, Pinia, PixiJS, easy-live2d, Three.js, `@pixiv/three-vrm`, FastAPI, SQLAlchemy, Socket.IO, Sherpa ONNX, RapidOCR, Genie-TTS, and optional Qdrant/embedding clients. Review installed package metadata before redistributing a bundled build.

## 桌宠与媒体资源 / Avatar and media assets

Live2D Cubism 模型、VRM 文件、纹理、动作、表情、参考音频、字体和图片可能有独立的署名、非商业或再分发条款。除非精确许可证明确允许，否则将下载资源保留在源码控制之外。

Live2D Cubism models, VRM files, textures, motions, expressions, reference audio, fonts, and images may impose separate attribution, non-commercial, or redistribution terms. Keep downloaded assets outside source control unless their exact license explicitly permits inclusion.

## 外部服务与模型 / External services and models

Ollama、LM Studio、OpenAI 兼容端点、Qdrant、SoulX 服务、MCP 服务和 Hugging Face 模型仓库各自拥有独立条款；Yuizaki 不授予这些服务或模型权利。

Ollama, LM Studio, OpenAI-compatible endpoints, Qdrant, SoulX services, MCP servers, and Hugging Face model repositories have their own terms. Yuizaki does not grant rights to those services or weights.

## 上游致谢 / Upstream acknowledgements

首次运行所需资源来自以下上游项目和模型仓库。重新分发构建前请核对当前许可证：

The required first-run resources are prepared from the following upstream projects and model repositories. Review their current licenses before redistributing a build:

| 集成 / Integration | 上游项目 / Upstream project | 模型或数据来源 / Model or data source |
| --- | --- | --- |
| Sherpa ASR | [k2-fsa/sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) | Sherpa ONNX release archives |
| Streaming ASR recipe | [k2-fsa/icefall](https://github.com/k2-fsa/icefall) | Streaming Zipformer2 model archive |
| Qwen3 Embedding | [QwenLM/Qwen3](https://github.com/QwenLM/Qwen3) | [Qwen/Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) |
| Genie TTS | [High-Logic/Genie-TTS](https://github.com/High-Logic/Genie-TTS) | Built-in local mode; `High-Logic/Genie` fixed Hugging Face revision |
| SoulX SVC | [Soul-AILab/SoulX-Singer](https://github.com/Soul-AILab/SoulX-Singer) | SoulX model and preprocess repositories |

感谢上述项目及其维护者。Yuizaki 只负责集成和下载编排，不重新授权上游代码、模型、声音或角色素材。

Thank you to these projects and their maintainers. Yuizaki only provides integration and download orchestration; it does not relicense upstream code, models, voices, or character assets.

## Genie 角色模型 / Genie character bundles

以下 Genie 角色包发布在 `python/CharacterModels/v2ProPlus/` 对应目录中，每个目录都有自己的 `LICENSE` 文件：

The following Genie character bundles are published in their corresponding directories under `python/CharacterModels/v2ProPlus/`. Each directory has its own `LICENSE` file:

| 角色 / Character | 许可证 / License | 范围 / Scope |
| --- | --- | --- |
| 辉夜 / Huiye | [CC BY-NC-SA 4.0](python/CharacterModels/v2ProPlus/辉夜/LICENSE) | 仅此角色包 / This bundle only |
| 莓华 / Meihua | [CC BY-NC-SA 4.0](python/CharacterModels/v2ProPlus/莓华/LICENSE) | 仅此角色包 / This bundle only |
| 美久栗 / Meikuli | [CC BY-NC-SA 4.0](python/CharacterModels/v2ProPlus/美久栗/LICENSE) | 仅此角色包 / This bundle only |
| 普拉琪娜 / Pulachina | [CC BY-NC-SA 4.0](python/CharacterModels/v2ProPlus/普拉琪娜_e15_e8_correct_sampling_v2/LICENSE) | 仅此角色包；目录名保持兼容 / This bundle only; compatibility directory name retained |
| feibi | [Genie upstream MIT](python/CharacterModels/v2ProPlus/feibi/LICENSE) | Genie 内置角色包 / Built-in Genie bundle |

上表四个 CC BY-NC-SA 4.0 声明仅适用于各自角色包；`feibi` 遵循 Genie 上游 MIT 许可证。根目录 MIT 许可证仅适用于 Yuizaki 源代码，不适用于这些角色资产或共享 GenieData 运行时资源。

The four CC BY-NC-SA 4.0 declarations above apply only to their respective bundles. `feibi` follows the Genie upstream MIT license. The root MIT license covers Yuizaki source code only; it does not license these character assets or shared GenieData runtime resources.

`genie-character-pulachina.zip` 于 2026-10-04 更新为当前 Pu 模型使用的 `sampling025` ONNX 处理，解压目录仍为 `普拉琪娜_e15_e8_correct_sampling_v2`，以保持现有默认路径兼容。资源使用参考音频 `もうこんなひどいことさせないからね.wav` 及匹配的日文文本。

The `genie-character-pulachina.zip` asset was refreshed on 2026-10-04 with the `sampling025` ONNX processing used by the current Pu model. Its extracted directory remains `普拉琪娜_e15_e8_correct_sampling_v2` for compatibility. It uses the reference audio `もうこんなひどいことさせないからね.wav` and matching Japanese text.

角色包下载： [Genie 角色模型 Release](https://github.com/Rivulet138/yuizaki/releases/tag/genie-models-2026-10-02)。

Download the bundles from the [Genie character models release](https://github.com/Rivulet138/yuizaki/releases/tag/genie-models-2026-10-02).

## 资源锁核验 / Resource lock review

`resources.lock.json` 中的可下载资源具有以下发布边界：

The downloadable resources in `resources.lock.json` have the following release boundary:

| 资源 / Resource | 声明许可证 / Declared license | 源码发布 / Source release | 安装包 / Bundled installer |
| --- | --- | --- | --- |
| Sherpa SenseVoice archive | FunASR Model License | 仅保留 URL 和校验和 / Keep URL and checksum only | 默认不打包；核对模型卡条款 / Do not bundle by default; review model-card terms |
| Sherpa streaming Zipformer2 | Apache-2.0 | 保留依赖引用和声明 / Keep dependency reference and notices | 仅在附带 Apache 声明和模型条款时允许 / Permitted only with Apache notices and model terms |
| Qwen3 Embedding 0.6B | Apache-2.0 | 保留依赖引用和声明 / Keep dependency reference and notices | 保留 Apache 声明和 Hugging Face 条款 / Preserve Apache notice and model terms |
| Genie TTS 2.0.2 | MIT | 保留包引用和 MIT 声明 / Keep package reference and MIT notice | 包许可证宽松；声音仍单独处理 / Package license is permissive; voices remain separate |
| SoulX Singer bundle | Apache-2.0 upstream declaration | 保留服务集成和锁元数据 / Keep service integration and lock metadata | 默认不打包；逐项核对模型和预处理资源 / Do not bundle by default; verify every asset |

以上是上游声明，不构成法律意见。发布二进制前，应根据精确锁文件生成许可证报告并附带相应声明。除非独立许可证与发布门槛明确允许，否则不得包含下载的模型权重、用户声音、Live2D/VRM 文件、字体、艺术素材、参考音频、本地数据库、日志、缓存或测试截图。

These are upstream declarations, not a legal opinion. Before publishing a binary, generate a license report from the exact lock files and ship the corresponding notices. Do not include downloaded model weights, user-provided voices, Live2D/VRM files, fonts, artwork, reference audio, local databases, logs, caches, or test screenshots unless their separate licenses and the release gate explicitly permit them.
