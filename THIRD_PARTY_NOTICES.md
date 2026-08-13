# Third-party notices

Yuizaki source code is MIT-licensed. That license does not automatically cover character models, voices, fonts, artwork, downloaded weights, or services selected by the user.

## Runtime libraries

The Electron and Python dependency manifests are authoritative for package licenses and versions. They include Vue, Electron, Vite, Pinia, PixiJS, easy-live2d, Three.js, `@pixiv/three-vrm`, FastAPI, SQLAlchemy, Socket.IO, Sherpa ONNX, RapidOCR, Genie-TTS, and optional Qdrant/embedding clients. Consult the installed package metadata before redistributing a bundled build.

## Avatar and media assets

Live2D Cubism models, VRM files, textures, motions, expressions, reference audio, fonts, and images may impose separate attribution, non-commercial, or redistribution terms. Keep downloaded assets outside source control unless their license explicitly permits inclusion.

## External services and models

Ollama, LM Studio, OpenAI-compatible endpoints, Qdrant, SoulX services, MCP servers, and Hugging Face model repositories have their own terms. Yuizaki does not grant rights to those services or weights.

## Resource lock review

The downloadable resources in `resources.lock.json` have the following release boundary:

| Resource | Declared license | Source release | Bundled installer |
| --- | --- | --- | --- |
| Sherpa SenseVoice archive | FunASR Model License | Keep only the URL and checksum; do not commit model files | Do not bundle by default; review the model-specific terms and attribution before redistribution |
| Sherpa streaming Zipformer2 | Apache-2.0 | Keep the dependency reference and notices | Permitted in principle if Apache notices and model-card terms are preserved |
| Qwen3 Embedding 0.6B | Apache-2.0 | Keep the dependency reference and notices | Permitted in principle if Apache notices and Hugging Face model terms are preserved |
| Genie TTS 2.0.2 | MIT | Keep the package reference and MIT notice | Permitted in principle; voices and reference audio remain separately licensed |
| SoulX Singer bundle | Apache-2.0 (upstream declaration) | Keep the service integration and lock metadata only | Do not bundle by default; its model/preprocess assets are optional and must retain upstream notices and asset-specific terms |

These are the declared upstream terms, not a legal opinion. Before publishing a binary, generate a license report from the exact lock files and ship the corresponding notices. Do not include downloaded model weights, user-provided voices, Live2D/VRM files, fonts, artwork, or reference audio unless their separate licenses explicitly permit redistribution.

## AIRI and research references

Project AIRI is an external reference implementation. Yuizaki does not copy AIRI source code. Research links and upstream references are provided for design provenance, not as bundled dependencies.
