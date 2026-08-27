from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from uuid import uuid4


QDRANT_IMAGE = "qdrant/qdrant:v1.18.3"
RESOURCE_PREFIX = "yuizaki-qdrant-it-"


def _run(command: list[str], *, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=check,
        capture_output=capture,
        text=True,
        timeout=240,
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_qdrant(url: str, timeout_seconds: float = 120.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/healthz", timeout=2) as response:
                if response.status == 200:
                    return
        except Exception as exc:
            last_error = exc
        time.sleep(0.5)
    raise RuntimeError("temporary Qdrant did not become healthy") from last_error


def _assert_owned_resource(name: str) -> None:
    if not name.startswith(RESOURCE_PREFIX) or len(name) <= len(RESOURCE_PREFIX):
        raise RuntimeError(f"refusing to remove non-integration Docker resource: {name}")


def main() -> int:
    if shutil.which("docker") is None:
        raise RuntimeError("Docker CLI is required for the real Qdrant integration test")
    daemon = _run(["docker", "info", "--format", "{{.ServerVersion}}"], check=False, capture=True)
    if daemon.returncode != 0:
        raise RuntimeError("Docker daemon is not running")

    suffix = uuid4().hex[:12]
    container_name = f"{RESOURCE_PREFIX}{suffix}"
    volume_name = f"{RESOURCE_PREFIX}storage-{suffix}"
    _assert_owned_resource(container_name)
    _assert_owned_resource(volume_name)
    port = _free_port()
    qdrant_url = f"http://127.0.0.1:{port}"
    repository_root = Path(__file__).resolve().parents[1]
    python_root = repository_root / "python"
    test_path = python_root / "tests" / "test_qdrant_integration.py"

    with tempfile.TemporaryDirectory(prefix="yuizaki-qdrant-metrics-") as temp_directory:
        metrics_path = Path(temp_directory) / "qdrant-integration.json"
        try:
            _run(["docker", "volume", "create", volume_name], capture=True)
            _run([
                "docker", "run", "--detach", "--pull", "missing",
                "--name", container_name,
                "--publish", f"127.0.0.1:{port}:6333",
                "--mount", f"type=volume,source={volume_name},target=/qdrant/storage",
                QDRANT_IMAGE,
            ], capture=True)
            _wait_for_qdrant(qdrant_url)

            environment = dict(os.environ)
            environment.update({
                "YUIZAKI_QDRANT_INTEGRATION_URL": qdrant_url,
                "YUIZAKI_QDRANT_INTEGRATION_CONTAINER": container_name,
                "YUIZAKI_QDRANT_METRICS_PATH": str(metrics_path),
            })
            result = subprocess.run(
                [sys.executable, "-m", "pytest", str(test_path), "-q", "-s"],
                cwd=python_root,
                env=environment,
                text=True,
                timeout=300,
            )
            if result.returncode != 0:
                logs = _run(["docker", "logs", "--tail", "120", container_name], check=False, capture=True)
                if logs.stdout:
                    print(logs.stdout, file=sys.stderr)
                if logs.stderr:
                    print(logs.stderr, file=sys.stderr)
                return result.returncode
            if not metrics_path.exists():
                raise RuntimeError("integration test passed without producing metrics evidence")
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            print(f"Qdrant integration evidence: {json.dumps(metrics, sort_keys=True)}")
            return 0
        finally:
            _run(["docker", "rm", "--force", container_name], check=False, capture=True)
            _run(["docker", "volume", "rm", "--force", volume_name], check=False, capture=True)


if __name__ == "__main__":
    raise SystemExit(main())
