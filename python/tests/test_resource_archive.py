from __future__ import annotations

import hashlib
import io
import socket
import tarfile
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator

import pytest

from scripts.resource_archive import PROGRESS_PREFIX, download_archive, remove_download_artifacts, safe_extract, verify_sha256


@pytest.fixture(autouse=True)
def bypass_proxy_for_loopback_archive_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")


class ArchiveHandler(BaseHTTPRequestHandler):
    payload = b""
    ranges: list[str | None] = []
    ignore_ranges = False
    truncate_first = False

    def do_GET(self) -> None:  # noqa: N802
        range_header = self.headers.get("Range")
        self.__class__.ranges.append(range_header)
        if range_header and not self.__class__.ignore_ranges:
            start = int(range_header.removeprefix("bytes=").removesuffix("-"))
            if start >= len(self.__class__.payload):
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{len(self.__class__.payload)}")
                self.end_headers()
                return
            body = self.__class__.payload[start:]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(self.__class__.payload) - 1}/{len(self.__class__.payload)}")
        else:
            body = self.__class__.payload
            self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.__class__.truncate_first and len(self.__class__.ranges) == 1 and not range_header:
            self.wfile.write(body[: len(body) // 2])
            self.wfile.flush()
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


@contextmanager
def archive_server(
    payload: bytes,
    *,
    ignore_ranges: bool = False,
    truncate_first: bool = False,
) -> Iterator[tuple[str, type[ArchiveHandler]]]:
    handler = type("TestArchiveHandler", (ArchiveHandler,), {
        "payload": payload,
        "ranges": [],
        "ignore_ranges": ignore_ranges,
        "truncate_first": truncate_first,
    })
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/archive.bin", handler
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_verify_sha256_accepts_matching_file(tmp_path: Path):
    archive = tmp_path / "resource.bin"
    archive.write_bytes(b"yuizaki-resource")

    verify_sha256(archive, hashlib.sha256(archive.read_bytes()).hexdigest())


def test_verify_sha256_rejects_modified_file(tmp_path: Path):
    archive = tmp_path / "resource.bin"
    archive.write_bytes(b"modified")

    with pytest.raises(ValueError, match="SHA256 mismatch"):
        verify_sha256(archive, "0" * 64)


def test_safe_extract_rejects_path_escape(tmp_path: Path):
    archive_path = tmp_path / "resource.tar"
    with tarfile.open(archive_path, "w") as archive:
        payload = b"escape"
        member = tarfile.TarInfo("../outside.txt")
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))

    with tarfile.open(archive_path) as archive:
        with pytest.raises(ValueError, match="escapes target directory"):
            safe_extract(archive, tmp_path / "extract")

    assert not (tmp_path / "outside.txt").exists()


def test_download_archive_emits_structured_byte_progress(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    source = tmp_path / "source.bin"
    target = tmp_path / "target.bin"
    source.write_bytes(b"yuizaki" * 4096)

    download_archive(source.as_uri(), target)

    progress_lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith(PROGRESS_PREFIX)]
    assert target.read_bytes() == source.read_bytes()
    assert progress_lines
    assert '"phase": "downloading"' in progress_lines[-1]
    assert f'"bytesTotal": {source.stat().st_size}' in progress_lines[-1]


def test_download_archive_resumes_partial_file(tmp_path: Path):
    payload = b"resume-archive" * 4096
    target = tmp_path / "archive.part"
    partial_size = len(payload) // 3
    target.write_bytes(payload[:partial_size])

    with archive_server(payload) as (url, handler):
        download_archive(url, target, retry_delay=0)

    assert target.read_bytes() == payload
    assert handler.ranges == [f"bytes={partial_size}-"]
    assert target.with_name("archive.part.json").is_file()


def test_download_archive_restarts_when_server_ignores_range(tmp_path: Path):
    payload = b"full-response" * 4096
    target = tmp_path / "archive.part"
    partial_size = len(payload) // 4
    target.write_bytes(payload[:partial_size])

    with archive_server(payload, ignore_ranges=True) as (url, handler):
        download_archive(url, target, retry_delay=0)

    assert handler.ranges == [f"bytes={partial_size}-"]
    assert target.read_bytes() == payload


def test_download_archive_restarts_when_partial_exceeds_remote_size(tmp_path: Path):
    payload = b"smaller-remote" * 1024
    target = tmp_path / "archive.part"
    target.write_bytes(payload + b"stale")

    with archive_server(payload) as (url, handler):
        download_archive(url, target, retry_delay=0)

    assert handler.ranges == [f"bytes={len(payload) + 5}-", None]
    assert target.read_bytes() == payload


def test_download_archive_retries_from_received_bytes_after_disconnect(tmp_path: Path):
    payload = b"retry-archive" * 4096
    target = tmp_path / "archive.part"

    with archive_server(payload, truncate_first=True) as (url, handler):
        download_archive(url, target, max_retries=2, retry_delay=0)

    assert target.read_bytes() == payload
    assert handler.ranges == [None, f"bytes={len(payload) // 2}-"]


def test_remove_download_artifacts_deletes_partial_and_journal(tmp_path: Path):
    target = tmp_path / "archive.part"
    target.write_bytes(b"partial")
    target.with_name("archive.part.json").write_text("{}", encoding="utf-8")

    remove_download_artifacts(target)

    assert not target.exists()
    assert not target.with_name("archive.part.json").exists()
