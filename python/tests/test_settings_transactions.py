from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from modules.system.dynamic_config import DynamicConfigManager
from modules.system.settings_api import SettingsAPI
from modules.system.settings_history_store import SettingsHistoryStore
from modules.system.settings_schema import PersistedSettingsSchema
from modules.system.settings_store import SETTINGS_SECRET_MASK, SettingsStore


def make_api(tmp_path, reload=None):
    store = SettingsStore(tmp_path / "settings.json")
    defaults = PersistedSettingsSchema().model_dump()
    store.replace(defaults)
    config = SimpleNamespace(**{key: SimpleNamespace(**value) for key, value in defaults.items() if isinstance(value, dict)})
    return SettingsAPI(
        store, DynamicConfigManager(), config=config,
        reload_runtime_services=reload,
        settings_history_store=SettingsHistoryStore(tmp_path / "history.json"),
    ), store


@pytest.mark.asyncio
async def test_concurrent_patch_set_reset_merge_latest_and_rollback(tmp_path):
    api, store = make_api(tmp_path)
    await api.set_setting("llm.timeout", 45)
    original_commit = api._commit_settings
    arrived = 0
    ready = asyncio.Event()

    async def rendezvous(*args, **kwargs):
        nonlocal arrived
        arrived += 1
        if arrived == 3:
            ready.set()
        await ready.wait()
        return await original_commit(*args, **kwargs)

    api._commit_settings = rendezvous
    await asyncio.gather(
        api.set_setting("llm.model", "new-model"),
        api.update_settings({"llm": {"temperature": 0.3}}),
        api.delete_setting("llm.timeout"),
    )
    assert store.get("llm.model") == "new-model"
    assert store.get("llm.temperature") == 0.3
    assert store.get("llm.timeout") == PersistedSettingsSchema().llm.timeout
    await api.rollback_changes(3)
    assert store.get("llm.timeout") == 45
    assert store.get("llm.model") == PersistedSettingsSchema().llm.model


@pytest.mark.asyncio
async def test_reload_failure_query_and_same_value_save_recovers(tmp_path):
    calls = []

    async def reload(sections):
        calls.append(sections)
        if len(calls) == 1:
            raise RuntimeError("provider secret must not reach status")

    api, store = make_api(tmp_path, reload)
    result = await api.update_settings({"llm": {"model": "target"}})
    assert result.runtime_applied == []
    assert result.runtime_reload.sections["llm"].state == "pending"
    assert result.normalized_settings.llm.model == "target"
    await api.wait_for_runtime_reload_idle()
    assert result.normalized_settings == await api.get_all_settings()
    failed = await api.get_runtime_reload_status()
    assert failed.sections["llm"].state == "failed"
    assert "secret" not in failed.model_dump_json()
    assert store.get("llm.model") == "target"
    await api.update_settings({"llm": {"model": "target"}})
    await api.wait_for_runtime_reload_idle()
    applied = (await api.get_runtime_reload_status()).sections["llm"]
    assert applied.state == "applied"
    assert applied.applied_revision == applied.target_revision
    assert calls == [{"llm"}, {"llm"}]


@pytest.mark.asyncio
async def test_retry_rejects_stale_target_and_retries_current_without_saving(tmp_path):
    calls = []

    async def reload(sections):
        calls.append(api.config.llm.model)
        if len(calls) < 3:
            raise RuntimeError("unavailable")

    api, _ = make_api(tmp_path, reload)
    await api.update_settings({"llm": {"model": "old"}})
    await api.wait_for_runtime_reload_idle()
    old = (await api.get_runtime_reload_status()).sections["llm"].target_revision
    await api.update_settings({"llm": {"model": "latest"}})
    await api.wait_for_runtime_reload_idle()
    current = (await api.get_runtime_reload_status()).sections["llm"].target_revision
    with pytest.raises(HTTPException) as error:
        await api.retry_runtime_reload({"llm": old})
    assert error.value.status_code == 409
    history_count = len(api._settings_history)
    await api.retry_runtime_reload({"llm": current})
    await api.wait_for_runtime_reload_idle()
    assert calls == ["old", "latest", "latest"]
    assert len(api._settings_history) == history_count


@pytest.mark.asyncio
@pytest.mark.parametrize("old_fails", [False, True])
async def test_reload_keeps_target_config_stable_until_completion(tmp_path, old_fails):
    started, finish = asyncio.Event(), asyncio.Event()
    latest_started, latest_finish = asyncio.Event(), asyncio.Event()
    seen = []

    async def reload(sections):
        assert sections == {"llm"}
        model = api.config.llm.model
        seen.append(model)
        if model == "first":
            started.set()
            await finish.wait()
        else:
            latest_started.set()
            await latest_finish.wait()
        seen.append(api.config.llm.model)
        if model == "first" and old_fails:
            raise RuntimeError("provider-secret")

    api, store = make_api(tmp_path, reload)
    first = await api.update_settings({"llm": {"model": "first"}})
    old_revision = first.runtime_reload.sections["llm"].target_revision
    await asyncio.wait_for(started.wait(), timeout=2)
    try:
        second = await asyncio.wait_for(api.update_settings({"llm": {"model": "second"}}), timeout=2)
        assert second.normalized_settings.llm.model == "second"
        assert second.runtime_applied == []
        assert second.runtime_changed == ["llm"]
        assert second.runtime_reload.sections["llm"].state == "pending"
        assert store.get("llm.model") == "second"
        assert api.config.llm.model == "first"
        latest = await asyncio.wait_for(api.update_settings({"llm": {"model": "latest", "temperature": 0.4}}), timeout=2)
        target = latest.runtime_reload.sections["llm"].target_revision
        assert target > second.runtime_reload.sections["llm"].target_revision > old_revision
        assert api.config.llm.model == "first"
        assert seen == ["first"]
        finish.set()
        await asyncio.wait_for(latest_started.wait(), timeout=2)
        status = (await api.get_runtime_reload_status()).sections["llm"]
        assert status.state == "applying"
        assert status.target_revision == target
        assert status.applied_revision == (None if old_fails else old_revision)
        assert status.error is None
        assert api.config.llm.model == "latest"
        assert api.config.llm.temperature == 0.4
        latest_finish.set()
        await asyncio.wait_for(api.wait_for_runtime_reload_idle(), timeout=2)
        applied = (await api.get_runtime_reload_status()).sections["llm"]
        assert applied.state == "applied"
        assert applied.applied_revision == applied.target_revision == target
        assert seen == ["first", "first", "latest", "latest"]
        assert "provider-secret" not in (await api.get_runtime_reload_status()).model_dump_json()
    finally:
        finish.set()
        latest_finish.set()
        await api.wait_for_runtime_reload_idle()


@pytest.mark.asyncio
async def test_concurrent_secret_placeholder_preserves_latest_secret_and_rollback(tmp_path):
    api, store = make_api(tmp_path)
    store.set("llm.api_key", "initial-test-secret")
    await asyncio.gather(
        api.update_settings({"llm": {"api_key": "new-test-secret"}}),
        api.update_settings({"llm": {"api_key": SETTINGS_SECRET_MASK, "model": "latest"}}),
    )
    assert store.get("llm.api_key") == "new-test-secret"
    await api.rollback_changes(1)
    assert store.get("llm.api_key") == "new-test-secret"
    assert "test-secret" not in (tmp_path / "settings.json").read_text(encoding="utf-8")
    assert "test-secret" not in (tmp_path / "history.json").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_invalid_patch_and_failed_dynamic_update_leave_commit_unchanged(tmp_path, monkeypatch):
    api, store = make_api(tmp_path)
    await api.update_settings({"llm": {"model": "original"}})
    before = store.get_all()
    history_count = len(api._settings_history)
    with pytest.raises(HTTPException) as error:
        await api.update_settings({"llm": {"temperature": "invalid"}})
    assert error.value.status_code == 422
    assert len(api._settings_history) == history_count

    async def fail(_updates):
        raise RuntimeError("dynamic update failed")

    monkeypatch.setattr(api.dynamic_config, "update_batch", fail)
    with pytest.raises(RuntimeError):
        await api.update_settings({"llm": {"model": "failed"}})
    assert store.get_all() == before
    assert len(api._settings_history) == history_count
    assert api.config.llm.model == "original"


@pytest.mark.asyncio
async def test_profile_field_patch_preserves_other_profiles_and_fields(tmp_path):
    api, store = make_api(tmp_path)
    await api.update_settings({"llm": {"profiles": {
        "custom": {"model": "custom-new", "timeout": 55},
        "ollama": {"model": "other-new"},
    }}})
    await api.update_settings({"llm": {"temperature": 0.4, "profiles": {"custom": {"temperature": 0.4}}}})
    assert store.get("llm.profiles.custom.model") == "custom-new"
    assert store.get("llm.profiles.custom.timeout") == 55
    assert store.get("llm.profiles.ollama.model") == "other-new"


@pytest.mark.asyncio
async def test_runtime_http_contract_and_validation(tmp_path):
    import httpx
    from fastapi import FastAPI
    from modules.system.settings_api import get_settings_api, router

    async def reload(sections):
        raise RuntimeError("temporary failure")

    api, _ = make_api(tmp_path, reload)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings_api] = lambda: api
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch("/api/settings/", json={"llm": {"model": "saved"}})
        assert response.status_code == 200
        assert response.json()["runtime_applied"] == []
        await api.wait_for_runtime_reload_idle()
        status = await client.get("/api/settings/runtime/status")
        assert status.status_code == 200
        target = status.json()["sections"]["llm"]
        assert target["state"] == "failed"
        assert target["error"] == "runtime_reload_failed"
        assert (await client.post("/api/settings/runtime/retry", json={"targets": {}})).status_code == 422
        assert (await client.post("/api/settings/runtime/retry", json={"targets": {"llm": -1}})).status_code == 409
        retry = await client.post("/api/settings/runtime/retry", json={"targets": {"llm": target["target_revision"]}})
        assert retry.status_code == 200
        assert retry.json()["sections"]["llm"]["state"] == "pending"
        await api.wait_for_runtime_reload_idle()


@pytest.mark.asyncio
async def test_missing_reload_callback_is_unavailable_not_applied(tmp_path):
    api, _ = make_api(tmp_path)
    response = await api.update_settings({"llm": {"model": "needs-service"}})
    assert response.runtime_applied == []
    status = response.runtime_reload.sections["llm"]
    assert status.state == "unavailable"
    with pytest.raises(HTTPException) as error:
        await api.retry_runtime_reload({"llm": status.target_revision})
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_new_field_change_invalidates_failed_target_revision(tmp_path):
    async def reload(sections):
        raise RuntimeError("unavailable")

    api, _ = make_api(tmp_path, reload)
    await api.update_settings({"llm": {"model": "target"}})
    await api.wait_for_runtime_reload_idle()
    previous = (await api.get_runtime_reload_status()).sections["llm"].target_revision
    await api.update_settings({"llm": {"temperature": 0.4}})
    await api.wait_for_runtime_reload_idle()
    current = (await api.get_runtime_reload_status()).sections["llm"].target_revision
    assert current > previous
    with pytest.raises(HTTPException) as error:
        await api.retry_runtime_reload({"llm": previous})
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_vault_sync_cannot_mutate_config_during_reload(tmp_path):
    started, finish = asyncio.Event(), asyncio.Event()
    seen = []

    async def reload(sections):
        if not seen:
            seen.append(api.config.llm.api_key)
            started.set()
            await finish.wait()
            seen.append(api.config.llm.api_key)

    api, store = make_api(tmp_path, reload)
    await api.update_settings({"llm": {"model": "target", "api_key": "before-sync"}})
    await started.wait()
    syncing = asyncio.create_task(api.reload_provider_credentials({"llm.api_key": "after-sync"}))
    completed, _ = await asyncio.wait({syncing}, timeout=0.05)
    assert not completed
    finish.set()
    await syncing
    await api.wait_for_runtime_reload_idle()
    assert seen == ["before-sync", "before-sync"]
    assert store.get("llm.api_key") == "after-sync"
    assert api.config.llm.api_key == "after-sync"


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["PATCH", "POST"])
async def test_save_http_returns_get_equivalent_normalized_and_redacted_settings(tmp_path, monkeypatch, method):
    import httpx
    from fastapi import FastAPI
    from modules.system.settings_api import get_settings_api, router
    from modules.system.settings_schema import env_config

    monkeypatch.setattr(env_config.llm, "model", "environment-model")
    monkeypatch.setattr(env_config.llm, "vision_api_key", "environment-vision-secret")
    api, store = make_api(tmp_path)
    store.replace({
        "llm": {"provider": "custom", "base_url": "https://example.invalid/v1", "api_key": "existing-llm-secret"},
        "tts": {"api_key": "existing-tts-secret"},
        "asr": {"api_key": "existing-asr-secret"},
        "memory": {"qdrant_api_key": "existing-qdrant-secret"},
    })
    updates = {"timeout": "45", "profiles": {"custom": {
        "base_url": "https://example.invalid/v1/", "api_key": "profile-secret", "timeout": "55",
    }}}
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings_api] = lambda: api
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(
            method, "/api/settings/" if method == "PATCH" else "/api/settings/llm",
            json={"llm": updates} if method == "PATCH" else updates,
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == ("success" if method == "PATCH" else "updated")
        assert payload["runtime_applied"] == []
        assert payload["runtime_changed"] == ["llm"]
        assert payload["runtime_reload"]["sections"]["llm"]["state"] == "unavailable"
        normalized = payload["normalized_settings"]
        assert normalized == (await client.get("/api/settings/")).json()
        assert normalized["llm"]["model"] == "environment-model"
        assert normalized["llm"]["timeout"] == 45.0
        assert normalized["llm"]["profiles"]["custom"]["timeout"] == 55.0
        assert normalized["llm"]["profiles"]["custom"]["base_url"] == "https://example.invalid/v1"
        for section, field in (
            ("llm", "api_key"), ("llm", "vision_api_key"), ("tts", "api_key"),
            ("asr", "api_key"), ("memory", "qdrant_api_key"),
        ):
            assert normalized[section][field] == SETTINGS_SECRET_MASK
        assert normalized["llm"]["profiles"]["custom"]["api_key"] == SETTINGS_SECRET_MASK
        assert "secret" not in response.text
    assert store.get("llm.api_key") == "existing-llm-secret"
    assert "secret" not in (tmp_path / "settings.json").read_text(encoding="utf-8")
    assert "secret" not in (tmp_path / "history.json").read_text(encoding="utf-8")


@pytest.mark.asyncio
@pytest.mark.parametrize("placeholder", ["", SETTINGS_SECRET_MASK])
async def test_unchanged_secret_post_returns_snapshot_without_saving(tmp_path, monkeypatch, placeholder):
    import httpx
    from fastapi import FastAPI
    from modules.system.settings_api import get_settings_api, router

    api, store = make_api(tmp_path)
    store.set("llm.api_key", "preserved-secret")
    expected = (await api.get_all_settings()).model_dump(mode="json")
    original_get_all = store.get_all
    reads = 0

    def get_all():
        nonlocal reads
        reads += 1
        return original_get_all()

    monkeypatch.setattr(store, "get_all", get_all)

    def unexpected_save():
        pytest.fail("An unchanged secret must not save settings")

    monkeypatch.setattr(store, "save", unexpected_save)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings_api] = lambda: api
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/settings/llm.api_key", json=placeholder)
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unchanged"
    assert payload["value"] == SETTINGS_SECRET_MASK
    assert payload["normalized_settings"] == expected
    assert reads == 1  # No commit exists to reuse for this unchanged response.
    assert payload["runtime_changed"] == []
    assert "preserved-secret" not in response.text
    assert store.get("llm.api_key") == "preserved-secret"
    assert len(api._settings_history) == 0
    assert api.dynamic_config.config == {}


@pytest.mark.asyncio
async def test_save_responses_keep_their_own_committed_snapshot(tmp_path, monkeypatch):
    api, store = make_api(tmp_path)
    original_temperature = store.get("llm.temperature")
    first_committed, second_committed = asyncio.Event(), asyncio.Event()
    original_commit = api._commit_settings

    async def delay_first_response(patch):
        result = await original_commit(patch)
        if patch["llm"]["model"] == "first":
            first_committed.set()
            await second_committed.wait()
        else:
            second_committed.set()
        return result

    async def save_second():
        await first_committed.wait()
        return await api.update_settings({"llm": {"model": "second", "temperature": 0.7}})

    monkeypatch.setattr(api, "_commit_settings", delay_first_response)
    first, second = await asyncio.wait_for(asyncio.gather(
        api.set_setting("llm.model", "first"), save_second(),
    ), timeout=5)
    assert first.normalized_settings.llm.model == "first"
    assert first.normalized_settings.llm.temperature == original_temperature
    assert second.normalized_settings.llm.model == "second"
    assert second.normalized_settings.llm.temperature == 0.7
    assert second.normalized_settings == await api.get_all_settings()
    await api.rollback_changes(1)
    assert (await api.get_all_settings()).llm.model == "first"
    assert second.normalized_settings.llm.model == "second"


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["PATCH", "POST"])
@pytest.mark.parametrize("failure_stage", ["validation", "save", "dynamic"])
async def test_failed_save_has_no_normalized_success_snapshot(tmp_path, monkeypatch, method, failure_stage):
    import httpx
    from fastapi import FastAPI
    from modules.system.settings_api import get_settings_api, router

    api, store = make_api(tmp_path)
    await api.update_settings({"llm": {"model": "original"}})
    before = store.get_all()
    disk_before = (tmp_path / "settings.json").read_bytes()
    dynamic_before = api.dynamic_config.get_all()
    history_count = len(api._settings_history)
    reload_before = await api.get_runtime_reload_status()

    def fail_save():
        raise OSError("synthetic save failure")

    async def fail_dynamic(_updates):
        raise RuntimeError("synthetic dynamic failure")

    if failure_stage == "save":
        monkeypatch.setattr(store, "save", fail_save)
    elif failure_stage == "dynamic":
        monkeypatch.setattr(api.dynamic_config, "update_batch", fail_dynamic)
    updates = {"temperature": "invalid"} if failure_stage == "validation" else {"model": "failed"}
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings_api] = lambda: api
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test",
    ) as client:
        response = await client.request(
            method, "/api/settings/" if method == "PATCH" else "/api/settings/llm",
            json={"llm": updates} if method == "PATCH" else updates,
        )
    assert response.status_code == (422 if failure_stage == "validation" else 500)
    assert "normalized_settings" not in response.text
    assert store.get_all() == before
    assert (tmp_path / "settings.json").read_bytes() == disk_before
    assert api.dynamic_config.get_all() == dynamic_before
    assert len(api._settings_history) == history_count
    assert api.config.llm.model == "original"
    assert await api.get_runtime_reload_status() == reload_before


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["PATCH", "POST"])
async def test_save_snapshot_does_not_reread_store_after_persisting(tmp_path, monkeypatch, method):
    api, store = make_api(tmp_path)
    saved = False
    reads = 0
    original_get_all, original_save = store.get_all, store.save

    def save():
        nonlocal saved
        original_save()
        saved = True

    def get_all():
        nonlocal reads
        reads += 1
        assert not saved, "The response must use the committed snapshot without a store readback"
        return original_get_all()

    monkeypatch.setattr(store, "save", save)
    monkeypatch.setattr(store, "get_all", get_all)
    if method == "PATCH":
        response = await api.update_settings({"llm": {"model": "saved"}})
    else:
        response = await api.set_setting("llm.model", "saved")
    assert saved
    assert reads == 2  # Existing transaction base and rollback snapshot reads only.
    assert response.normalized_settings.llm.model == "saved"


@pytest.mark.asyncio
async def test_slow_reload_coalesces_disjoint_sections_and_latest_fields(tmp_path):
    started, finish = asyncio.Event(), asyncio.Event()
    seen = []

    async def reload(sections):
        seen.append((set(sections), api.config.llm.model, api.config.llm.temperature, api.config.memory.qdrant_url))
        if len(seen) == 1:
            started.set()
            await finish.wait()

    api, store = make_api(tmp_path, reload)
    await api.update_settings({"llm": {"model": "first"}})
    await asyncio.wait_for(started.wait(), timeout=2)
    try:
        await asyncio.wait_for(api.update_settings({"llm": {"model": "latest"}}), timeout=2)
        await asyncio.wait_for(api.update_settings({"memory": {"qdrant_url": "https://example.invalid/"}}), timeout=2)
        latest = await asyncio.wait_for(api.update_settings({"llm": {"temperature": 0.6}}), timeout=2)
        assert latest.normalized_settings.llm.model == "latest"
        assert latest.normalized_settings.memory.qdrant_url == "https://example.invalid"
        assert api.config.llm.model == "first"
        assert len(seen) == 1
    finally:
        finish.set()
        await asyncio.wait_for(api.wait_for_runtime_reload_idle(), timeout=2)
    assert seen[1] == ({"llm", "memory"}, "latest", 0.6, "https://example.invalid")
    assert len(seen) == 2
    assert store.get("llm.model") == api.config.llm.model == "latest"
    for section in ("llm", "memory"):
        status = (await api.get_runtime_reload_status()).sections[section]
        assert status.state == "applied"
        assert status.applied_revision == status.target_revision


@pytest.mark.asyncio
async def test_hot_field_waits_for_config_stability_without_extra_service_reload(tmp_path):
    started, finish = asyncio.Event(), asyncio.Event()
    seen = []

    async def reload(sections):
        seen.append(set(sections))
        before = api.config.llm.temperature
        started.set()
        await finish.wait()
        assert api.config.llm.temperature == before

    api, _ = make_api(tmp_path, reload)
    await api.update_settings({"memory": {"qdrant_url": "https://example.invalid"}})
    await asyncio.wait_for(started.wait(), timeout=2)
    try:
        result = await asyncio.wait_for(api.update_settings({"llm": {"temperature": 0.4}}), timeout=2)
        assert result.runtime_applied == []
        assert result.runtime_changed == ["llm"]
        assert result.runtime_reload.sections["llm"].state == "pending"
    finally:
        finish.set()
        await asyncio.wait_for(api.wait_for_runtime_reload_idle(), timeout=2)
    assert seen == [{"memory"}]
    assert api.config.llm.temperature == 0.4
    status = (await api.get_runtime_reload_status()).sections["llm"]
    assert status.state == "applied"
    assert status.applied_revision == status.target_revision


@pytest.mark.asyncio
async def test_latest_queued_reload_failure_stays_failed_and_retries_without_saving(tmp_path, monkeypatch):
    started, finish = asyncio.Event(), asyncio.Event()
    calls = []

    async def reload(sections):
        calls.append(api.config.llm.model)
        if len(calls) == 1:
            started.set()
            await finish.wait()
        elif len(calls) == 2:
            raise RuntimeError("provider-secret")

    api, store = make_api(tmp_path, reload)
    first = await api.update_settings({"llm": {"model": "first"}})
    await asyncio.wait_for(started.wait(), timeout=2)
    try:
        latest = await asyncio.wait_for(api.update_settings({"llm": {"model": "latest"}}), timeout=2)
    finally:
        finish.set()
        await asyncio.wait_for(api.wait_for_runtime_reload_idle(), timeout=2)
    failed = (await api.get_runtime_reload_status()).sections["llm"]
    assert failed.state == "failed"
    assert failed.error == "runtime_reload_failed"
    assert failed.target_revision == latest.runtime_reload.sections["llm"].target_revision
    assert failed.applied_revision == first.runtime_reload.sections["llm"].target_revision
    assert store.get("llm.model") == api.config.llm.model == "latest"
    assert "provider-secret" not in failed.model_dump_json()
    history_count = len(api._settings_history)

    def unexpected_save():
        pytest.fail("Retry must not persist settings")

    monkeypatch.setattr(store, "save", unexpected_save)
    await api.retry_runtime_reload({"llm": failed.target_revision})
    await asyncio.wait_for(api.wait_for_runtime_reload_idle(), timeout=2)
    applied = (await api.get_runtime_reload_status()).sections["llm"]
    assert applied.state == "applied"
    assert applied.target_revision == applied.applied_revision == failed.target_revision
    assert len(api._settings_history) == history_count
    assert calls == ["first", "latest", "latest"]


@pytest.mark.asyncio
@pytest.mark.parametrize("credential,base_url", [("api_key", "base_url"), ("vision_api_key", "vision_base_url")])
async def test_queued_connection_switch_drops_previous_queued_credential(tmp_path, credential, base_url):
    started, finish = asyncio.Event(), asyncio.Event()
    seen = []

    async def reload(sections):
        seen.append((getattr(api.config.llm, base_url), getattr(api.config.llm, credential)))
        if len(seen) == 1:
            started.set()
            await finish.wait()
            assert getattr(api.config.llm, credential) == "initial-secret"

    api, store = make_api(tmp_path, reload)
    provider = "provider" if credential == "api_key" else "vision_provider"
    await api.update_settings({"llm": {"model": "first", provider: "custom", base_url: "https://old.example/v1", credential: "initial-secret"}})
    await asyncio.wait_for(started.wait(), timeout=2)
    try:
        await asyncio.wait_for(api.update_settings({"llm": {credential: "queued-secret"}}), timeout=2)
        result = await asyncio.wait_for(api.update_settings({"llm": {base_url: "https://new.example/v1", credential: SETTINGS_SECRET_MASK}}), timeout=2)
        assert store.get(f"llm.{credential}") == ""
        assert getattr(result.normalized_settings.llm, credential) == ""
        assert "secret" not in result.model_dump_json()
    finally:
        finish.set()
        await asyncio.wait_for(api.wait_for_runtime_reload_idle(), timeout=2)
    assert seen == [("https://old.example/v1", "initial-secret"), ("https://new.example/v1", "")]
    assert getattr(api.config.llm, credential) == ""


@pytest.mark.asyncio
async def test_vault_sync_supersedes_queued_credentials_and_waits_for_reload(tmp_path):
    started, finish = asyncio.Event(), asyncio.Event()
    synced_started, synced_finish = asyncio.Event(), asyncio.Event()
    seen = []

    async def reload(sections):
        seen.append((api.config.llm.model, api.config.llm.api_key))
        if len(seen) == 1:
            started.set()
            await finish.wait()
            assert api.config.llm.api_key == "initial-secret"
        else:
            synced_started.set()
            await synced_finish.wait()
            assert api.config.llm.api_key == "vault-secret"

    api, store = make_api(tmp_path, reload)
    await api.update_settings({"llm": {"model": "first", "api_key": "initial-secret"}})
    await asyncio.wait_for(started.wait(), timeout=2)
    syncing = None
    try:
        await asyncio.wait_for(api.update_settings({"llm": {"model": "latest", "api_key": "queued-secret"}}), timeout=2)
        syncing = asyncio.create_task(api.reload_provider_credentials({"llm.api_key": "vault-secret"}))
        completed, _ = await asyncio.wait({syncing}, timeout=0.05)
        assert not completed
        assert api.config.llm.api_key == "initial-secret"
        finish.set()
        await asyncio.wait_for(synced_started.wait(), timeout=2)
        assert not syncing.done()
        assert api.config.llm.model == "latest"
        assert api.config.llm.api_key == "vault-secret"
        synced_finish.set()
        await asyncio.wait_for(syncing, timeout=2)
    finally:
        finish.set()
        synced_finish.set()
        if syncing is not None:
            await syncing
        await asyncio.wait_for(api.wait_for_runtime_reload_idle(), timeout=2)
    assert seen == [("first", "initial-secret"), ("latest", "vault-secret")]
    assert store.get("llm.api_key") == api.config.llm.api_key == "vault-secret"
    assert "secret" not in (tmp_path / "settings.json").read_text(encoding="utf-8")


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["PATCH", "POST"])
async def test_saving_during_slow_reload_returns_http_snapshot_without_store_readback(tmp_path, monkeypatch, method):
    import httpx
    from fastapi import FastAPI
    from modules.system.settings_api import get_settings_api, router

    started, finish = asyncio.Event(), asyncio.Event()

    async def reload(sections):
        if api.config.llm.model == "first":
            started.set()
            await finish.wait()

    api, store = make_api(tmp_path, reload)
    await api.update_settings({"llm": {"model": "first"}})
    await asyncio.wait_for(started.wait(), timeout=2)
    reads, saved = 0, False
    original_get_all, original_save = store.get_all, store.save

    def get_all():
        nonlocal reads
        reads += 1
        assert not saved, "No store readback after this commit"
        return original_get_all()

    def save():
        nonlocal saved
        original_save()
        saved = True

    monkeypatch.setattr(store, "get_all", get_all)
    monkeypatch.setattr(store, "save", save)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings_api] = lambda: api
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await asyncio.wait_for(client.request(
                method, "/api/settings/" if method == "PATCH" else "/api/settings/llm.model",
                json={"llm": {"model": "latest"}} if method == "PATCH" else "latest",
            ), timeout=2)
        assert response.status_code == 200
        assert response.json()["normalized_settings"]["llm"]["model"] == "latest"
        assert response.json()["runtime_reload"]["sections"]["llm"]["state"] == "pending"
        assert response.json()["runtime_applied"] == []
        assert api.config.llm.model == "first"
        assert saved and reads == 2
    finally:
        finish.set()
        await asyncio.wait_for(api.wait_for_runtime_reload_idle(), timeout=2)
    assert reads == 2
    assert api.config.llm.model == "latest"


@pytest.mark.asyncio
async def test_queued_model_reversion_replaces_intermediate_intent(tmp_path):
    started, finish = asyncio.Event(), asyncio.Event()
    seen = []

    async def reload(sections):
        seen.append(api.config.llm.model)
        if len(seen) == 1:
            started.set()
            await finish.wait()
            assert api.config.llm.model == "A"

    api, store = make_api(tmp_path, reload)
    await api.update_settings({"llm": {"model": "A"}})
    await asyncio.wait_for(started.wait(), timeout=2)
    try:
        second = await asyncio.wait_for(api.update_settings({"llm": {"model": "B"}}), timeout=2)
        reverted = await asyncio.wait_for(api.update_settings({"llm": {"model": "A"}}), timeout=2)
        assert reverted.normalized_settings.llm.model == "A"
        assert reverted.runtime_reload.sections["llm"].target_revision > second.runtime_reload.sections["llm"].target_revision
        assert reverted.runtime_reload.sections["llm"].state == "pending"
        assert api._pending_runtime_updates["llm"]["model"] == "A"
    finally:
        finish.set()
        await asyncio.wait_for(api.wait_for_runtime_reload_idle(), timeout=2)
    assert seen == ["A", "A"]
    assert store.get("llm.model") == api.config.llm.model == "A"
    status = (await api.get_runtime_reload_status()).sections["llm"]
    assert status.state == "applied"
    assert status.target_revision == status.applied_revision == reverted.runtime_reload.sections["llm"].target_revision


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_latest", [False, True])
async def test_cancelled_reload_and_pending_intent_are_explicitly_retryable(tmp_path, monkeypatch, cancel_latest):
    started, finish = asyncio.Event(), asyncio.Event()
    latest_started, latest_finish = asyncio.Event(), asyncio.Event()
    calls = []

    async def reload(sections):
        calls.append(api.config.llm.model)
        if len(calls) == 1:
            started.set()
            await finish.wait()
        elif len(calls) == 2 and cancel_latest:
            latest_started.set()
            await latest_finish.wait()

    api, store = make_api(tmp_path, reload)
    first = await api.update_settings({"llm": {"model": "first"}})
    await asyncio.wait_for(started.wait(), timeout=2)
    try:
        latest = await asyncio.wait_for(api.update_settings({"llm": {"model": "latest"}}), timeout=2)
        target = latest.runtime_reload.sections["llm"].target_revision
        if cancel_latest:
            finish.set()
            await asyncio.wait_for(latest_started.wait(), timeout=2)
        task = api._runtime_reload_task
        assert task is not None
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        failed = (await api.get_runtime_reload_status()).sections["llm"]
        assert failed.target_revision == target
        assert failed.state == "failed"
        assert failed.error == "runtime_reload_cancelled"
        assert failed.applied_revision == (first.runtime_reload.sections["llm"].target_revision if cancel_latest else None)
        assert store.get("llm.model") == "latest"
        history_count = len(api._settings_history)

        def unexpected_save():
            pytest.fail("Retry must reuse the committed target")

        monkeypatch.setattr(store, "save", unexpected_save)
        await api.retry_runtime_reload({"llm": target})
        await asyncio.wait_for(api.wait_for_runtime_reload_idle(), timeout=2)
        applied = (await api.get_runtime_reload_status()).sections["llm"]
        assert applied.target_revision == applied.applied_revision == target
        assert applied.state == "applied"
        assert api.config.llm.model == "latest"
        assert len(api._settings_history) == history_count
        assert calls == (["first", "latest", "latest"] if cancel_latest else ["first", "latest"])
    finally:
        finish.set()
        latest_finish.set()
        await api.wait_for_runtime_reload_idle()


@pytest.mark.asyncio
async def test_queued_config_apply_failure_retains_committed_snapshot_for_retry(tmp_path, monkeypatch):
    from modules.system import runtime_config

    started, finish = asyncio.Event(), asyncio.Event()
    calls = []

    async def reload(sections):
        calls.append(api.config.llm.model)
        if len(calls) == 1:
            started.set()
            await finish.wait()

    api, store = make_api(tmp_path, reload)
    original_apply = runtime_config.apply_runtime_config
    fail_once = True

    def apply(config, updates, **kwargs):
        nonlocal fail_once
        if config is api.config and updates.get("llm", {}).get("model") == "latest" and fail_once:
            fail_once = False
            raise RuntimeError("provider-secret")
        return original_apply(config, updates, **kwargs)

    monkeypatch.setattr(runtime_config, "apply_runtime_config", apply)
    await api.update_settings({"llm": {"model": "first"}})
    await asyncio.wait_for(started.wait(), timeout=2)
    try:
        latest = await asyncio.wait_for(api.update_settings({"llm": {"model": "latest"}}), timeout=2)
    finally:
        finish.set()
        await asyncio.wait_for(api.wait_for_runtime_reload_idle(), timeout=2)
    failed = (await api.get_runtime_reload_status()).sections["llm"]
    target = latest.runtime_reload.sections["llm"].target_revision
    assert failed.target_revision == target
    assert failed.state == "failed"
    assert failed.error == "runtime_reload_failed"
    assert "secret" not in failed.model_dump_json()
    assert store.get("llm.model") == "latest"
    assert api.config.llm.model == "first"
    assert api._pending_runtime_updates["llm"]["model"] == "latest"
    await api.retry_runtime_reload({"llm": target})
    await asyncio.wait_for(api.wait_for_runtime_reload_idle(), timeout=2)
    applied = (await api.get_runtime_reload_status()).sections["llm"]
    assert applied.target_revision == applied.applied_revision == target
    assert applied.state == "applied"
    assert api.config.llm.model == "latest"
    assert calls == ["first", "latest"]
