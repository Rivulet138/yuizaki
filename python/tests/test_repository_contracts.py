import json
import os
import subprocess
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = REPOSITORY_ROOT / "python" / ".env.example"
RUNTIME_REQUIREMENTS = REPOSITORY_ROOT / "python" / "requirements.txt"
RESOURCE_LOCK = REPOSITORY_ROOT / "resources.lock.json"
PYRIGHT_CONFIG = REPOSITORY_ROOT / "pyrightconfig.json"
PYTHON_RESOLVER = REPOSITORY_ROOT / "scripts" / "resolve_python.bat"


def _read_env_example() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def test_environment_template_matches_persistence_and_resource_defaults():
    values = _read_env_example()

    assert values["MEMORY_BACKEND"] == "sqlite"
    assert values["QDRANT_AUTO_START"] == "0"
    assert values["QDRANT_DOCKER_IMAGE"] == "qdrant/qdrant:v1.18.3"
    assert values["LLM_CONTEXT_MAX_TOKENS"] == "131072"
    assert values["LLM_DEFAULT_MAX_OUTPUT_TOKENS"] == "8192"


def test_mutable_qdrant_latest_tag_is_normalized_to_pinned_baseline():
    from modules.core.config import DEFAULT_QDRANT_DOCKER_IMAGE, normalize_qdrant_docker_image

    assert normalize_qdrant_docker_image("qdrant/qdrant:latest") == DEFAULT_QDRANT_DOCKER_IMAGE
    assert normalize_qdrant_docker_image("qdrant/qdrant:v1.18.3") == "qdrant/qdrant:v1.18.3"


def test_qdrant_auto_start_follows_the_selected_memory_backend(monkeypatch):
    from modules.core.config import _load_config_from_env

    monkeypatch.delenv("QDRANT_AUTO_START", raising=False)
    monkeypatch.setenv("MEMORY_BACKEND", "sqlite")
    assert _load_config_from_env().memory.qdrant_auto_start is False

    monkeypatch.setenv("MEMORY_BACKEND", "qdrant")
    assert _load_config_from_env().memory.qdrant_auto_start is True

    monkeypatch.setenv("QDRANT_AUTO_START", "0")
    assert _load_config_from_env().memory.qdrant_auto_start is False


def test_python_toolchain_targets_project_venv_and_minimum_supported_version():
    pyright = json.loads(PYRIGHT_CONFIG.read_text(encoding="utf-8"))

    assert pyright["venvPath"] == "python"
    assert pyright["venv"] == ".venv"
    assert pyright["pythonVersion"] == "3.11"


@pytest.mark.skipif(os.name != "nt", reason="Windows batch resolver contract")
def test_windows_python_resolver_prefers_newer_launcher_runtime(tmp_path):
    (tmp_path / "py.cmd").write_text(
        '@echo off\nif "%~1"=="-3.13" exit /b 0\nexit /b 1\n',
        encoding="utf-8",
    )
    (tmp_path / "python.cmd").write_text("@exit /b 0\n", encoding="utf-8")
    environment = os.environ.copy()
    windows_root = Path(environment.get("SystemRoot", environment.get("WINDIR", r"C:\Windows")))
    environment["PATH"] = f"{tmp_path};{windows_root / 'System32'}"
    command_shell = environment.get("COMSPEC", str(windows_root / "System32" / "cmd.exe"))
    runner = tmp_path / "run-resolver.cmd"
    runner.write_text(
        f'@echo off\ncall "{PYTHON_RESOLVER}"\nif errorlevel 1 exit /b 1\necho [%PY_CMD%]\n',
        encoding="utf-8",
    )

    result = subprocess.run(
        [command_shell, "/d", "/c", runner.name],
        capture_output=True,
        check=False,
        cwd=tmp_path,
        encoding="utf-8",
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    assert "[py -3.13]" in result.stdout


def test_platform_dependency_lock_matrix_is_present_and_exactly_pinned():
    from scripts.check_requirements_lock import LOCKS, _parse_requirements

    assert len(LOCKS) == 6
    for lock in LOCKS:
        values = _parse_requirements(lock)
        assert values
        assert all(specifier.startswith("==") and specifier[2:3].isdigit() for specifier, _ in values.values())


def test_environment_template_does_not_restore_removed_legacy_fields():
    values = _read_env_example()

    assert {"ASR_MODEL", "ASR_DEVICE", "ASR_LANG", "OCR_ENABLED"}.isdisjoint(values)


def test_direct_runtime_validation_dependency_is_declared():
    requirements = RUNTIME_REQUIREMENTS.read_text(encoding="utf-8").splitlines()

    assert any(line.startswith("pydantic>=2.12,<3") for line in requirements)


def test_resource_sensitive_tts_runtime_is_pinned():
    requirements = RUNTIME_REQUIREMENTS.read_text(encoding="utf-8").splitlines()

    assert "genie-tts==2.0.2" in requirements


def test_default_model_resources_are_locked_to_immutable_sources():
    resources = json.loads(RESOURCE_LOCK.read_text(encoding="utf-8"))["resources"]

    assert set(resources) == {"soulx", "sherpa", "sherpa_online", "embedding", "tts"}
    assert all(resources[resource_id]["sources"][0]["sha256"] for resource_id in ("sherpa", "sherpa_online"))
    assert all(
        len(source["revision"]) == 40
        for resource_id in ("soulx", "embedding")
        for source in resources[resource_id]["sources"]
    )
