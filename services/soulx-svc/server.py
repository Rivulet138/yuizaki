from __future__ import annotations

import asyncio
import base64
import os
import random
import shutil
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response


SOULX_ROOT = Path(os.getenv("SOULX_ROOT", "/opt/SoulX-Singer")).resolve()
MODEL_DIR = Path(os.getenv("SOULX_MODEL_DIR", "/models/SoulX-Singer")).resolve()
PREPROCESS_DIR = Path(os.getenv("SOULX_PREPROCESS_DIR", "/models/SoulX-Singer-Preprocess")).resolve()
REFERENCE_DIR = Path(os.getenv("SOULX_REFERENCE_DIR", "/models/references")).resolve()
CONFIG_PATH = Path(os.getenv("SOULX_CONFIG_PATH", str(SOULX_ROOT / "soulxsinger/config/soulxsinger.yaml"))).resolve()
WORK_DIR = Path(os.getenv("SOULX_WORK_DIR", "/tmp/soulx-svc")).resolve()
TARGET_VOCAL_SEP = os.getenv("SOULX_TARGET_VOCAL_SEP", "true").strip().lower() in {"1", "true", "yes", "on"}
PROMPT_VOCAL_SEP = os.getenv("SOULX_PROMPT_VOCAL_SEP", "false").strip().lower() in {"1", "true", "yes", "on"}
AUTO_SHIFT = os.getenv("SOULX_AUTO_SHIFT", "true").strip().lower() in {"1", "true", "yes", "on"}
AUTO_MIX_ACC = os.getenv("SOULX_AUTO_MIX_ACC", "false").strip().lower() in {"1", "true", "yes", "on"}
DEFAULT_STEPS = int(os.getenv("SOULX_STEPS", "32"))
DEFAULT_CFG = float(os.getenv("SOULX_CFG", "3.0"))
DEFAULT_SEED = int(os.getenv("SOULX_SEED", "0"))


def _resolve_model_path() -> Path:
    explicit_path = os.getenv("SOULX_SVC_MODEL_PATH", "").strip()
    if explicit_path:
        return Path(explicit_path).resolve()
    for candidate in (MODEL_DIR / "model-svc.pt", MODEL_DIR / "model.pt"):
        if candidate.exists():
            return candidate.resolve()
    return (MODEL_DIR / "model-svc.pt").resolve()


MODEL_PATH = _resolve_model_path()


def _install_model_links() -> None:
    pretrained = SOULX_ROOT / "pretrained_models"
    pretrained.mkdir(parents=True, exist_ok=True)
    links = {
        pretrained / "SoulX-Singer": MODEL_DIR,
        pretrained / "SoulX-Singer-Preprocess": PREPROCESS_DIR,
    }
    for link, target in links.items():
        if link.exists() or link.is_symlink():
            continue
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError:
            link.mkdir(parents=True, exist_ok=True)


def _bootstrap_imports() -> None:
    _install_model_links()
    sys.path.insert(0, str(SOULX_ROOT))
    os.chdir(SOULX_ROOT)


def _device() -> str:
    configured = os.getenv("SOULX_DEVICE", "auto").strip().lower()
    if configured and configured != "auto":
        return configured
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def _bool_form(value: str | bool | None, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ReferenceAudio:
    audio_path: Path
    cache_dir: Path


class SoulXSvcRuntime:
    def __init__(self) -> None:
        _bootstrap_imports()
        self.device = _device()
        self.use_fp16 = os.getenv("SOULX_FP16", "false").strip().lower() in {"1", "true", "yes", "on"} and "cuda" in self.device

        import numpy as np
        import torch
        from cli.inference_svc import build_model
        from preprocess.pipeline import PreprocessPipeline
        from soulxsinger.utils.file_utils import load_config

        if not MODEL_PATH.exists():
            raise FileNotFoundError(f"SoulX SVC checkpoint not found: {MODEL_PATH}")
        if not PREPROCESS_DIR.exists():
            raise FileNotFoundError(f"SoulX preprocess model directory not found: {PREPROCESS_DIR}")
        if not REFERENCE_DIR.exists():
            raise FileNotFoundError(f"SoulX reference directory not found: {REFERENCE_DIR}")

        self._np = np
        self._torch = torch
        self.config = load_config(CONFIG_PATH)
        self.model = build_model(
            model_path=str(MODEL_PATH),
            config=self.config,
            device=self.device,
            use_fp16=self.use_fp16,
        )
        self.preprocess_pipeline = PreprocessPipeline(
            device=self.device,
            language=os.getenv("SOULX_LANGUAGE", "Mandarin"),
            save_dir=str(WORK_DIR / "_placeholder"),
            vocal_sep=True,
            max_merge_duration=60000,
            midi_transcribe=False,
        )

    def reference_for(self, speaker_id: str) -> ReferenceAudio:
        normalized = speaker_id.strip() or "0"
        candidates = [
            REFERENCE_DIR / normalized,
            REFERENCE_DIR / f"{normalized}.wav",
            REFERENCE_DIR / f"{normalized}.mp3",
            REFERENCE_DIR / f"{normalized}.flac",
            REFERENCE_DIR / f"{normalized}.m4a",
            REFERENCE_DIR / "default.wav",
            REFERENCE_DIR / "default.mp3",
            REFERENCE_DIR / "default.flac",
        ]
        for candidate in candidates:
            if candidate.is_dir():
                for name in ("prompt.wav", "reference.wav", "voice.wav", "prompt.mp3", "reference.mp3"):
                    nested = candidate / name
                    if nested.exists():
                        return ReferenceAudio(nested, WORK_DIR / "reference-cache" / normalized)
            if candidate.exists():
                return ReferenceAudio(candidate, WORK_DIR / "reference-cache" / normalized)
        raise HTTPException(status_code=404, detail=f"reference audio not found for speaker_id={speaker_id}")

    def preprocess(self, audio_path: Path, save_dir: Path, vocal_sep: bool) -> tuple[Path, Path]:
        self.preprocess_pipeline.save_dir = str(save_dir)
        self.preprocess_pipeline.run(
            audio_path=str(audio_path),
            vocal_sep=vocal_sep,
            max_merge_duration=60000,
            language=os.getenv("SOULX_LANGUAGE", "Mandarin"),
        )
        vocal_wav = save_dir / "vocal.wav"
        vocal_f0 = save_dir / "vocal_f0.npy"
        if not vocal_wav.exists() or not vocal_f0.exists():
            raise RuntimeError(f"preprocess output missing: {vocal_wav} or {vocal_f0}")
        return vocal_wav, vocal_f0

    def preprocess_reference(self, reference: ReferenceAudio, vocal_sep: bool) -> tuple[Path, Path]:
        reference.cache_dir.mkdir(parents=True, exist_ok=True)
        vocal_wav = reference.cache_dir / "vocal.wav"
        vocal_f0 = reference.cache_dir / "vocal_f0.npy"
        if vocal_wav.exists() and vocal_f0.exists():
            return vocal_wav, vocal_f0
        return self.preprocess(reference.audio_path, reference.cache_dir, vocal_sep)

    def convert(
        self,
        *,
        target_audio_path: Path,
        speaker_id: str,
        pitch_shift: int,
        auto_shift: bool,
        prompt_vocal_sep: bool,
        target_vocal_sep: bool,
        n_steps: int,
        cfg: float,
        seed: int,
        session_dir: Path,
    ) -> Path:
        from cli.inference_svc import process as svc_process

        seed = seed if seed > 0 else random.randint(1, 2**31 - 1)
        self._torch.manual_seed(seed)
        self._np.random.seed(seed)
        random.seed(seed)

        reference = self.reference_for(speaker_id)
        prompt_wav, prompt_f0 = self.preprocess_reference(reference, prompt_vocal_sep)
        target_wav, target_f0 = self.preprocess(target_audio_path, session_dir / "target", target_vocal_sep)

        save_dir = session_dir / "generated"
        save_dir.mkdir(parents=True, exist_ok=True)
        args = SimpleNamespace(
            device=self.device,
            prompt_wav_path=str(prompt_wav),
            target_wav_path=str(target_wav),
            prompt_f0_path=str(prompt_f0),
            target_f0_path=str(target_f0),
            save_dir=str(save_dir),
            auto_shift=auto_shift,
            pitch_shift=int(pitch_shift),
            n_steps=max(1, int(n_steps)),
            cfg=float(cfg),
            use_fp16=self.use_fp16,
        )
        svc_process(args, self.config, self.model)

        generated = save_dir / "generated.wav"
        if not generated.exists():
            raise RuntimeError(f"SoulX inference finished but output not found: {generated}")
        if AUTO_MIX_ACC:
            return generated
        return generated


app = FastAPI(title="Yuizaki SoulX-Singer-SVC Service", version="1.0.0")
runtime: SoulXSvcRuntime | None = None
runtime_lock = asyncio.Lock()


@app.on_event("startup")
def startup() -> None:
    global runtime
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    runtime = SoulXSvcRuntime()


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "ok": runtime is not None,
        "provider": "soulx-service",
        "device": runtime.device if runtime is not None else None,
        "fp16": runtime.use_fp16 if runtime is not None else None,
    }


@app.post("/convert")
async def convert(
    file: Annotated[UploadFile, File()],
    generation_id: Annotated[str, Form()] = "",
    speaker_id: Annotated[str, Form()] = "0",
    pitch: Annotated[int, Form()] = 0,
    f0_shift: Annotated[int | None, Form()] = None,
    auto_shift: Annotated[str | None, Form()] = None,
    prompt_vocal_sep: Annotated[str | None, Form()] = None,
    target_vocal_sep: Annotated[str | None, Form()] = None,
    n_steps: Annotated[int, Form()] = DEFAULT_STEPS,
    cfg: Annotated[float, Form()] = DEFAULT_CFG,
    seed: Annotated[int, Form()] = DEFAULT_SEED,
    response_format: Annotated[str, Form()] = "wav",
) -> Response:
    if runtime is None:
        raise HTTPException(status_code=503, detail="SoulX runtime is not initialized")

    request_id = generation_id.strip() or uuid.uuid4().hex
    session_dir = WORK_DIR / "requests" / request_id
    session_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "input.wav").suffix or ".wav"
    target_audio = session_dir / f"target{suffix}"
    target_audio.write_bytes(await file.read())

    try:
        async with runtime_lock:
            generated = await asyncio.to_thread(
                runtime.convert,
                target_audio_path=target_audio,
                speaker_id=speaker_id,
                pitch_shift=int(f0_shift if f0_shift is not None else pitch),
                auto_shift=_bool_form(auto_shift, AUTO_SHIFT),
                prompt_vocal_sep=_bool_form(prompt_vocal_sep, PROMPT_VOCAL_SEP),
                target_vocal_sep=_bool_form(target_vocal_sep, TARGET_VOCAL_SEP),
                n_steps=n_steps,
                cfg=cfg,
                seed=seed,
                session_dir=session_dir,
            )
        audio_bytes = generated.read_bytes()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        shutil.rmtree(session_dir, ignore_errors=True)

    if response_format.strip().lower() == "json":
        return JSONResponse({
            "status": "done",
            "provider": "soulx-service",
            "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
            "speaker_id": speaker_id,
            "pitch": int(f0_shift if f0_shift is not None else pitch),
        })
    return Response(content=audio_bytes, media_type="audio/wav")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.getenv("SOULX_HOST", "0.0.0.0"), port=int(os.getenv("SOULX_PORT", "7861")))
