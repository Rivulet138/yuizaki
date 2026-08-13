# Technology stack

## Desktop and renderer

- Electron 42
- Vue 3, Vue Router, Pinia, TypeScript
- Vite, Vitest, ESLint, Prettier
- PixiJS and easy-live2d for Live2D
- Three.js and `@pixiv/three-vrm` for VRM
- Socket.IO client and WebRTC for realtime interaction
- AudioWorklet with a browser fallback

## Backend

- Python 3.11-3.13
- FastAPI and Uvicorn
- python-socketio
- SQLAlchemy and Alembic
- SQLite for local persistence
- NumPy and Pillow for media handling
- Optional Sherpa ONNX, RapidOCR, Genie-TTS, Qdrant, and sentence-transformers

## Runtime constraints

Provider adapters isolate wire protocols. Audio, Job, perception, and avatar state use explicit identities and terminal events. Frame-level animation remains local to the renderer; the LLM emits intent-level commands.

## 中文说明

技术栈包括 Electron、Vue、Vite、Pinia、PixiJS、Three.js/VRM、FastAPI、Socket.IO、SQLAlchemy、SQLite，以及可选的 Sherpa ONNX、Genie TTS、Qdrant、MCP 和 SoulX 服务。各模块保持可替换边界，使核心桌面聊天链路无需安装可选模型服务即可运行；语音、视觉、检索和桌宠质量仍取决于本机设备、提供商配置、模型资源与资产许可证。
