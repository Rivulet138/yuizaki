from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = REPOSITORY_ROOT / "python" / ".env.example"


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
    assert values["QDRANT_DOCKER_IMAGE"] == "qdrant/qdrant:v1.18.3"
    assert values["LLM_CONTEXT_MAX_TOKENS"] == "131072"
    assert values["LLM_DEFAULT_MAX_OUTPUT_TOKENS"] == "8192"


def test_environment_template_does_not_restore_removed_legacy_fields():
    values = _read_env_example()

    assert {"ASR_MODEL", "ASR_DEVICE", "ASR_LANG", "OCR_ENABLED"}.isdisjoint(values)
