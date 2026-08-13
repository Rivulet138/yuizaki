# Resource management

## Persistent data

Chat and memory databases live under `python/data/`. Settings live under `python/config/`. Back up these files while services are stopped or through the control-panel backup API.

## Caches

TTS files live under `python/audio_cache/`; model and embedding caches are managed by the resource panel and provider-specific cache directories. Cache cleanup is reversible only until the files are recreated, so review the preview before permanent cleanup.

## Vision and audio

Requested vision frames are held in memory for one Agent request and released after analysis. Realtime audio is streamed through the active session; queued TTS is cleared on interruption. Do not write microphone buffers or screenshots to a long-lived log.

## Hardware profiles

Use the performance settings to cap DPR/FPS and pause hidden windows. On integrated GPUs or low-memory machines, prefer lazy model startup, CPU inference, lower TTS quality, and SQLite memory mode. Qdrant is optional and should not be auto-started unless semantic retrieval is needed.

## Cleanup boundary

Never commit `.venv`, model weights, `audio_cache`, `python/data`, logs, or pytest temporary directories. The launcher and resource APIs should be preferred over deleting active files manually.
