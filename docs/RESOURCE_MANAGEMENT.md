# Resource management

## Persistent data

Chat and memory databases live under `python/data/`. Settings live under `python/config/`. Back up through the control-panel API or while services are stopped.

## Caches and models

TTS files live under `python/audio_cache/`. Embedding, ASR, TTS, and provider caches are managed by the resource panel or provider-specific paths. Model weights and avatar assets must remain outside Git unless their licenses explicitly allow inclusion.

## Vision and audio

Vision frames are held in memory for one Agent request and released after analysis. Realtime audio uses the active session; queued TTS is cleared on interruption. Do not write microphone buffers or screenshots to long-lived logs.

## Hardware profiles

Use the performance settings to cap DPR/FPS and pause hidden windows. On integrated GPUs or low-memory machines, prefer lazy startup, CPU inference, lower TTS quality, and SQLite memory mode. Qdrant is optional and should not be auto-started unless semantic retrieval is needed.

## Cleanup boundary

Never commit `.venv`, model weights, `audio_cache`, `python/data`, logs, or pytest temporary directories. Prefer the launcher and resource APIs over deleting active files manually. Review cleanup previews before permanent deletion.
