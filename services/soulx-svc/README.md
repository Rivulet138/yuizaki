# SoulX SVC service

This directory contains the optional HTTP voice-conversion service. Core chat, ASR, and TTS do not require it.

## Start

Windows:

```powershell
.\\start_soulx_svc.bat
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

Model downloads are large and provider-specific. Keep checkpoints and reference audio outside Git, review their licenses, and use the repository resource lock when one is provided. NVIDIA GPU, a compatible driver, and CUDA may be required by the selected image. This service is local by default and should not be exposed publicly without an independent deployment review.
