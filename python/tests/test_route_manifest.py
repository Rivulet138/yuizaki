from fastapi import FastAPI

from route_manifest import build_route_manifest


def test_route_manifest_contains_proxy_methods_and_excludes_socket_mount() -> None:
    app = FastAPI()

    @app.get("/memory/candidates")
    async def candidates() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/api/settings")
    async def settings() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/internal/secret")
    async def secret() -> dict[str, bool]:
        return {"ok": True}

    manifest = build_route_manifest(app)
    routes = {(item["path"], tuple(item["methods"])) for item in manifest["routes"]}

    assert ("/memory/candidates", ("GET",)) in routes
    assert ("/api/settings", ("POST",)) in routes
    assert all(path != "/internal/secret" for path, _ in routes)
    assert manifest["schema_version"] == 1


def test_route_manifest_is_deterministic_and_normalizes_methods() -> None:
    app = FastAPI()

    @app.api_route("/api/item", methods=["POST", "GET"])
    async def item() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/another")
    async def another() -> dict[str, bool]:
        return {"ok": True}

    manifest = build_route_manifest(app)

    assert [entry["path"] for entry in manifest["routes"]] == ["/api/another", "/api/item"]
    assert manifest["routes"][1]["methods"] == ["GET", "POST"]
    assert all(entry["proxy"] is True for entry in manifest["routes"])


def test_route_manifest_accepts_explicit_prefix_boundary() -> None:
    app = FastAPI()

    @app.get("/internal/health")
    async def internal_health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    manifest = build_route_manifest(app, proxy_prefixes=("/health",))

    assert [entry["path"] for entry in manifest["routes"]] == ["/health"]
    assert manifest["proxy_prefixes"] == ["/health"]
