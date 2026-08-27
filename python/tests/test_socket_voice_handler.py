from __future__ import annotations

import asyncio

from socket_events import SVCEvents
from socket_handlers.voice import build_svc_convert_handler


class _Sio:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object], str]] = []

    async def emit(self, event: str, payload: dict[str, object], *, to: str) -> None:
        self.events.append((event, payload, to))


class _SvcClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, str, int | None, int | None]] = []

    async def convert(
        self,
        generation_id: str,
        audio: str,
        *,
        speaker_id: int | None,
        pitch: int | None,
    ) -> dict[str, object]:
        self.calls.append((generation_id, audio, speaker_id, pitch))
        if self.fail:
            raise RuntimeError("provider detail must not cross the protocol")
        return {"status": "completed", "audio": "converted"}


def test_svc_handler_preserves_conversion_arguments_and_terminal_event() -> None:
    sio = _Sio()
    client = _SvcClient()
    handler = build_svc_convert_handler(sio=sio, svc_client_provider=lambda: client)

    asyncio.run(handler("sid-1", {
        "audio": "source-audio",
        "speaker_id": "4",
        "transpose": -2,
    }))

    assert len(client.calls) == 1
    generation_id, audio, speaker_id, pitch = client.calls[0]
    assert generation_id.startswith("svc_")
    assert audio == "source-audio"
    assert speaker_id == 4
    assert pitch == -2
    assert sio.events == [(SVCEvents.DONE, {"status": "completed", "audio": "converted"}, "sid-1")]


def test_svc_handler_reports_unavailable_and_bounded_provider_failure() -> None:
    sio = _Sio()
    unavailable = build_svc_convert_handler(sio=sio, svc_client_provider=lambda: None)
    asyncio.run(unavailable("sid-1", {"audio": "source-audio"}))

    failed_client = _SvcClient(fail=True)
    failed = build_svc_convert_handler(sio=sio, svc_client_provider=lambda: failed_client)
    asyncio.run(failed("sid-2", {"audio": "source-audio"}))

    assert sio.events[0] == (
        SVCEvents.DONE,
        {"status": "failed", "error": "SVC client not initialized"},
        "sid-1",
    )
    assert sio.events[1] == (
        SVCEvents.DONE,
        {"status": "failed", "error": "svc_convert_failed", "message": "SVC conversion failed"},
        "sid-2",
    )

