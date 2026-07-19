from __future__ import annotations

import os
import importlib
from typing import Protocol, cast


class MigrationBootstrapModule(Protocol):
    def bootstrap_database(self) -> tuple[bool, str]: ...
    def check_database_at_head(self) -> tuple[bool, str]: ...


def _migration_bootstrap() -> MigrationBootstrapModule:
    module = cast(object, importlib.import_module("migration_bootstrap"))
    return cast(MigrationBootstrapModule, module)


def run_schema_upgrade() -> None:
    ok, message = _migration_bootstrap().bootstrap_database()
    if not ok:
        raise RuntimeError(f"Database bootstrap failed: {message}")


def verify_schema_current() -> tuple[bool, str]:
    return _migration_bootstrap().check_database_at_head()


def enforce_schema_policy() -> None:
    mode = os.getenv("SCHEMA_MIGRATION_MODE", "").strip().lower()
    app_env = os.getenv("APP_ENV", "development").strip().lower()

    if mode == "bootstrap":
        run_schema_upgrade()
        return
    if mode == "check":
        schema_ok, schema_message = verify_schema_current()
        if not schema_ok:
            raise RuntimeError(f"Database migration check failed: {schema_message}")
        return

    if app_env in {"development", "dev"}:
        run_schema_upgrade()
    else:
        schema_ok, schema_message = verify_schema_current()
        if not schema_ok:
            raise RuntimeError(f"Database migration check failed: {schema_message}")
