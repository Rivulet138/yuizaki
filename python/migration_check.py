from __future__ import annotations

from migration_bootstrap import check_database_at_head


def main() -> int:
    ok, message = check_database_at_head()
    if ok:
        print(f"[OK] {message}")
        return 0
    print(f"[ERROR] {message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
