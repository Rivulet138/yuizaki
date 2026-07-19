# SoulX-Singer-SVC Docker Service

This service wraps [Soul-AILab/SoulX-Singer](https://github.com/Soul-AILab/SoulX-Singer) as Yuizaki's external SVC provider.

SoulX-Singer-SVC is prompt/reference based: it does not have a native `speaker_id` concept. In Yuizaki, `speaker_id` is treated as a reference-audio id and mapped by the service to a mounted file under `references/`.

## Layout

```text
services/soulx-svc/
  Dockerfile
  docker-compose.yml
  server.py
  download_models.py
  models/                         # ignored, downloaded HF weights
    SoulX-Singer/
    SoulX-Singer-Preprocess/
  references/                     # ignored except .gitkeep
    0.wav                         # speaker_id=0
    1/prompt.wav                  # speaker_id=1
```

## One-Click Run

From the repository root:

```bat
start_soulx_svc.bat --check
start_soulx_svc.bat path\to\reference.wav
```

On first run, `start_soulx_svc.bat` can also be double-clicked. If no `speaker_id=0` reference audio exists yet, it opens a file picker, copies the selected `.wav`, `.mp3`, `.flac`, or `.m4a` into `references/`, downloads the Hugging Face model assets, builds the Docker image, and starts `http://127.0.0.1:7861`.

Later runs can use:

```bat
start_soulx_svc.bat
```

## Download Models

The one-click launcher downloads models automatically. Use this manual path only when you want to prefetch model assets without starting Docker.

Run this from the repository root:

```powershell
.\python\.venv\Scripts\python.exe -m pip install huggingface_hub
.\python\.venv\Scripts\python.exe services\soulx-svc\download_models.py
```

The script downloads:

- `Soul-AILab/SoulX-Singer`
- `Soul-AILab/SoulX-Singer-Preprocess`

Depending on the upstream snapshot, the main checkpoint may be stored as either `model-svc.pt` or `model.pt`. Yuizaki's launcher and service wrapper accept both names.

The model weights are not committed to this repo.

## Add Reference Audio

Place a clean singing reference file for each id:

```text
services/soulx-svc/references/0.wav
services/soulx-svc/references/1/prompt.wav
```

Yuizaki sends `speaker_id`; the service resolves it in this order:

- `references/{speaker_id}/prompt.wav`
- `references/{speaker_id}/reference.wav`
- `references/{speaker_id}/voice.wav`
- `references/{speaker_id}.wav`
- `references/{speaker_id}.mp3`
- `references/default.wav`

## Run

The preferred run command is the root launcher:

```bat
start_soulx_svc.bat
```

Manual Docker Compose startup is also available:

```powershell
cd services\soulx-svc
docker compose up --build
```

Then set Yuizaki:

```env
SVC_PROVIDER=soulx-service
SVC_BASE_URL=http://127.0.0.1:7861
SVC_SPEAKER_ID=0
SVC_PITCH=0
```

You can also prepare the same assets from the desktop app through `Settings -> Resources`:

- `Download SoulX Models`
- `Import Reference Audio`

## API

`POST /convert`

Multipart fields:

- `file`: target singing/audio file
- `generation_id`: optional request id
- `speaker_id`: reference audio id
- `pitch` or `f0_shift`: semitone shift
- `auto_shift`: optional boolean, default from `SOULX_AUTO_SHIFT`
- `prompt_vocal_sep`: optional boolean
- `target_vocal_sep`: optional boolean
- `n_steps`: optional integer, default `32`
- `cfg`: optional float, default `3.0`
- `response_format`: `wav` or `json`

Default response is `audio/wav`. With `response_format=json`, the service returns:

```json
{
  "status": "done",
  "provider": "soulx-service",
  "audio_base64": "...",
  "speaker_id": "0",
  "pitch": 0
}
```

## Notes

- The official SoulX repository currently provides CLI and Gradio entry points, not a production HTTP API or official Docker image.
- CPU mode is possible but slow; GPU with NVIDIA Container Toolkit is recommended.
- Keep reference audio authorized and private. Do not use SVC to impersonate people without consent.
