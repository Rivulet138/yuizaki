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
