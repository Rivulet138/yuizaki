# SoulX SVC service

SoulX SVC is an optional local HTTP voice-conversion service. It is not required for text chat, ASR, or the default TTS path.

## Start

Windows:

```powershell
.\start_soulx_svc.bat
```

Linux:

```bash
./start_soulx_svc.sh
```

Docker:

```bash
cd services/soulx-svc
docker compose up --build
```

Set `SVC_BASE_URL` in `python/.env`; the default is `http://127.0.0.1:7861`.

## Models and hardware

Model downloads are large and provider-specific. Keep checkpoints and reference audio outside Git. Review the upstream license and the repository `resources.lock.json` entry before downloading or redistributing anything. NVIDIA GPU, a compatible driver, and CUDA may be required by the selected image.

The service binds locally by default. Do not expose it publicly without a separate review of authentication, origin policy, resource limits, and model licensing.
