# pyright: reportUnusedFunction=false

from __future__ import annotations

import csv
import io
import json
import time
from datetime import datetime
from typing import Any, Callable

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from database.repository import DatabaseError, NotFoundError
from modules.system.api_response import error_response
from modules.system.api_security import require_bearer_token, resolve_admin_authorization


def create_summary_router(
    get_generation_mgr: Callable[[], Any],
    get_llm_client: Callable[[], Any],
    get_summary_list_limiter: Callable[[], Any],
    get_summary_detail_limiter: Callable[[], Any],
    get_summary_rewrite_limiter: Callable[[], Any],
    get_governance_alert_state: Callable[[], dict[str, dict[str, Any]]],
    save_governance_alert_state: Callable[[], None],
    get_summary_admin_token: Callable[[], str],
    get_db_repo: Callable[[], Any] | None = None,
    get_active_workspace_id: Callable[[], str] | None = None,
) -> APIRouter:
    router = APIRouter(tags=["summary"])

    def _require_summary_admin(authorization: str | None):
        expected_token = get_summary_admin_token().strip()
        return require_bearer_token(authorization, expected_token)

    def _active_workspace_id() -> str | None:
        if get_active_workspace_id is None:
            return None
        workspace_id = str(get_active_workspace_id() or "").strip()
        return workspace_id or None

    def _db_repo_for_workspace_guard() -> Any | None:
        if get_db_repo is None:
            return None
        return get_db_repo()

    def _database_unavailable_response() -> JSONResponse:
        return JSONResponse({"error": "Database not initialized"}, status_code=503)

    def _workspace_mismatch_response(active_workspace_id: str, session_workspace_id: str) -> JSONResponse:
        return JSONResponse(
            {
                "error": "workspace_mismatch",
                "message": "Session does not belong to the active workspace",
                "active_workspace_id": active_workspace_id,
                "session_workspace_id": session_workspace_id,
            },
            status_code=403,
        )

    def _enforce_active_session_workspace(session_id: str) -> JSONResponse | None:
        active_workspace_id = _active_workspace_id()
        if active_workspace_id is None:
            return None
        db_repo = _db_repo_for_workspace_guard()
        if not db_repo:
            return _database_unavailable_response()
        try:
            session_workspace_id = db_repo.get_session_workspace_id(session_id)
        except NotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except DatabaseError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if session_workspace_id != active_workspace_id:
            return _workspace_mismatch_response(active_workspace_id, session_workspace_id)
        return None

    def _visible_summary_session_ids(generation_mgr: Any) -> list[str] | JSONResponse:
        session_ids = [str(sid) for sid in generation_mgr.list_summary_session_ids()]
        active_workspace_id = _active_workspace_id()
        if active_workspace_id is None:
            return session_ids
        db_repo = _db_repo_for_workspace_guard()
        if not db_repo:
            return _database_unavailable_response()

        visible_session_ids: list[str] = []
        for sid in session_ids:
            try:
                session_workspace_id = db_repo.get_session_workspace_id(sid)
            except NotFoundError:
                continue
            except DatabaseError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
            if session_workspace_id == active_workspace_id:
                visible_session_ids.append(sid)
        return visible_session_ids

    def _filter_audit_items(items: list[dict[str, Any]]) -> list[dict[str, Any]] | JSONResponse:
        active_workspace_id = _active_workspace_id()
        if active_workspace_id is None:
            return items
        db_repo = _db_repo_for_workspace_guard()
        if not db_repo:
            return _database_unavailable_response()

        visible_items: list[dict[str, Any]] = []
        workspace_cache: dict[str, str | None] = {}
        for item in items:
            session_id = str(item.get("session_id", "") or "").strip()
            if not session_id:
                continue
            if session_id not in workspace_cache:
                try:
                    workspace_cache[session_id] = db_repo.get_session_workspace_id(session_id)
                except NotFoundError:
                    workspace_cache[session_id] = None
                except DatabaseError as exc:
                    return JSONResponse({"error": str(exc)}, status_code=400)
            if workspace_cache[session_id] == active_workspace_id:
                visible_items.append(item)
        return visible_items

    @router.get("/api/summary")
    async def list_session_summaries():
        limit = get_summary_list_limiter().check("summary_list")
        if not limit.allowed:
            return JSONResponse(
                {
                    "error": "rate_limited",
                    "message": "Too many summary list requests",
                    "retry_after": round(limit.retry_after, 2),
                },
                status_code=429,
                headers={"Retry-After": str(max(1, int(limit.retry_after)))},
            )

        generation_mgr = get_generation_mgr()
        if not generation_mgr:
            return JSONResponse({"error": "Generation manager not initialized"}, status_code=503)

        def _build_summary_list() -> dict[str, Any] | JSONResponse:
            visible_session_ids = _visible_summary_session_ids(generation_mgr)
            if isinstance(visible_session_ids, JSONResponse):
                return visible_session_ids

            return {
                "sessions": [
                    {
                        "session_id": sid,
                        "summary": generation_mgr.get_summary(sid),
                        "stats": generation_mgr.get_summary_stats(sid),
                    }
                    for sid in visible_session_ids
                ]
            }

        return await run_in_threadpool(_build_summary_list)

    @router.get("/api/summary/audit")
    async def get_summary_audit(session_id: str | None = None, limit: int = 100):
        if session_id:
            guard = await run_in_threadpool(_enforce_active_session_workspace, session_id)
            if guard is not None:
                return guard
        generation_mgr = get_generation_mgr()
        if not generation_mgr:
            return JSONResponse({"error": "Generation manager not initialized"}, status_code=503)

        def _build_audit() -> dict[str, Any] | JSONResponse:
            logs = generation_mgr.get_summary_audit(session_id=session_id, limit=limit)
            filtered_logs = _filter_audit_items(logs)
            if isinstance(filtered_logs, JSONResponse):
                return filtered_logs
            return {"logs": filtered_logs}

        return await run_in_threadpool(_build_audit)

    def _build_governance_report(days: int = 7) -> dict[str, Any] | JSONResponse:
        generation_mgr = get_generation_mgr()
        if not generation_mgr:
            return {"sessions": [], "audit": [], "summary": {}}

        visible_session_ids = _visible_summary_session_ids(generation_mgr)
        if isinstance(visible_session_ids, JSONResponse):
            return visible_session_ids

        now = time.time()
        since = now - max(1, int(days)) * 86400
        sessions = []
        for sid in visible_session_ids:
            sessions.append({"session_id": sid, "stats": generation_mgr.get_summary_stats(sid)})

        audit = generation_mgr.get_summary_audit(limit=500)
        visible_audit = _filter_audit_items(audit)
        if isinstance(visible_audit, JSONResponse):
            return visible_audit

        filtered_audit = []
        for item in visible_audit:
            ts = str(item.get("timestamp", ""))
            try:
                dt = datetime.fromisoformat(ts)
                if dt.timestamp() >= since:
                    filtered_audit.append(item)
            except Exception:
                continue

        total = len(filtered_audit)
        ok = sum(1 for x in filtered_audit if x.get("outcome") == "ok")
        guard_skip = sum(1 for x in filtered_audit if "quality=rule_skip(" in str(x.get("detail", "")))
        fallback = sum(1 for x in filtered_audit if "quality=rule_fallback(" in str(x.get("detail", "")))

        def pct(n: int, d: int) -> float:
            return round((n / d) * 100, 2) if d > 0 else 0.0

        trend_buckets: dict[str, dict[str, Any]] = {}
        for item in filtered_audit:
            day = str(item.get("timestamp", ""))[:10]
            if len(day) != 10:
                continue
            bucket = trend_buckets.setdefault(
                day,
                {"day": day, "audit_total": 0, "ok": 0, "guard_skip": 0, "fallback": 0},
            )
            bucket["audit_total"] += 1
            if item.get("outcome") == "ok":
                bucket["ok"] += 1
            detail = str(item.get("detail", ""))
            if "quality=rule_skip(" in detail:
                bucket["guard_skip"] += 1
            if "quality=rule_fallback(" in detail:
                bucket["fallback"] += 1

        trends = []
        for day in sorted(trend_buckets.keys()):
            b = trend_buckets[day]
            d = int(b["audit_total"])
            trends.append(
                {
                    "day": day,
                    "audit_total": d,
                    "ok_rate": pct(int(b["ok"]), d),
                    "guard_skip_rate": pct(int(b["guard_skip"]), d),
                    "fallback_rate": pct(int(b["fallback"]), d),
                }
            )

        alerts: list[dict[str, Any]] = []
        fallback_streak = 0
        guard_streak = 0
        for row in trends:
            if float(row.get("fallback_rate", 0.0)) >= 20.0:
                fallback_streak += 1
            else:
                fallback_streak = 0

            if float(row.get("guard_skip_rate", 0.0)) >= 40.0:
                guard_streak += 1
            else:
                guard_streak = 0

            if fallback_streak >= 2:
                alerts.append(
                    {
                        "type": "fallback_high",
                        "severity": "high",
                        "day": row.get("day"),
                        "message": "Fallback rate stayed high for 2+ days",
                        "suggestion": "Check upstream LLM stability or switch scorer_mode to rule temporarily.",
                    }
                )
                fallback_streak = 0

            if guard_streak >= 2:
                alerts.append(
                    {
                        "type": "guard_skip_high",
                        "severity": "medium",
                        "day": row.get("day"),
                        "message": "Cost guard hit rate stayed high for 2+ days",
                        "suggestion": "Increase scoring budget/cooldown settings or reduce rewrite frequency.",
                    }
                )
                guard_streak = 0

        session_quality_trend = []
        for item in sessions:
            stats = item.get("stats", {})
            session_quality_trend.append(
                {
                    "session_id": item.get("session_id"),
                    "overall": stats.get("quality", {}).get("overall", 0),
                    "facts": stats.get("quality", {}).get("facts", 0),
                    "preferences": stats.get("quality", {}).get("preferences", 0),
                    "goals_open_tasks": stats.get("quality", {}).get("goals_open_tasks", 0),
                }
            )

        visible_alerts = []
        now_ts = time.time()
        governance_alert_state = get_governance_alert_state()
        for alert in alerts:
            key = f"{alert.get('type')}:{alert.get('day')}"
            state = governance_alert_state.get(key, {})
            if state.get("acked") is True:
                continue
            snooze_until = float(state.get("snooze_until", 0) or 0)
            if snooze_until > now_ts:
                continue
            alert = dict(alert)
            alert["key"] = key
            visible_alerts.append(alert)

        return {
            "window_days": int(days),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
            "sessions": sessions,
            "audit": filtered_audit,
            "trends": trends,
            "session_quality_trend": session_quality_trend,
            "summary": {
                "audit_total": total,
                "ok_rate": pct(ok, total),
                "guard_skip_rate": pct(guard_skip, total),
                "fallback_rate": pct(fallback, total),
            },
            "alerts": visible_alerts,
            "alert_state_count": len(governance_alert_state),
        }

    @router.post("/api/summary/alerts/ack")
    async def ack_governance_alert(key: str, authorization: str | None = Depends(resolve_admin_authorization)):
        auth_error = _require_summary_admin(authorization)
        if auth_error is not None:
            return auth_error
        governance_alert_state = get_governance_alert_state()
        governance_alert_state[key] = {
            "acked": True,
            "snooze_until": 0,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        }
        await run_in_threadpool(save_governance_alert_state)
        return {"status": "ok", "key": key, "acked": True}

    @router.post("/api/summary/alerts/snooze")
    async def snooze_governance_alert(key: str, minutes: int = 60, authorization: str | None = Depends(resolve_admin_authorization)):
        auth_error = _require_summary_admin(authorization)
        if auth_error is not None:
            return auth_error
        mins = max(1, min(int(minutes), 1440))
        governance_alert_state = get_governance_alert_state()
        governance_alert_state[key] = {
            "acked": False,
            "snooze_until": time.time() + mins * 60,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        }
        await run_in_threadpool(save_governance_alert_state)
        return {"status": "ok", "key": key, "snooze_minutes": mins}

    @router.post("/api/summary/alerts/clear")
    async def clear_governance_alert_state(authorization: str | None = Depends(resolve_admin_authorization)):
        auth_error = _require_summary_admin(authorization)
        if auth_error is not None:
            return auth_error
        governance_alert_state = get_governance_alert_state()
        governance_alert_state.clear()
        await run_in_threadpool(save_governance_alert_state)
        return {"status": "ok", "cleared": True}

    @router.get("/api/summary/report/json")
    async def export_governance_report_json(days: int = 7):
        generation_mgr = get_generation_mgr()
        if not generation_mgr:
            return JSONResponse({"error": "Generation manager not initialized"}, status_code=503)
        report = await run_in_threadpool(_build_governance_report, days=days)
        if isinstance(report, JSONResponse):
            return report
        payload = await run_in_threadpool(json.dumps, report, ensure_ascii=False, indent=2)
        return StreamingResponse(
            iter([payload]),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=governance_report_{days}d.json"},
        )

    @router.get("/api/summary/report/csv")
    async def export_governance_report_csv(days: int = 7):
        generation_mgr = get_generation_mgr()
        if not generation_mgr:
            return JSONResponse({"error": "Generation manager not initialized"}, status_code=503)
        report = await run_in_threadpool(_build_governance_report, days=days)
        if isinstance(report, JSONResponse):
            return report

        def _build_csv_payload() -> str:
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["timestamp", "session_id", "source", "outcome", "detail"])
            for item in report.get("audit", []):
                writer.writerow([
                    item.get("timestamp", ""),
                    item.get("session_id", ""),
                    item.get("source", ""),
                    item.get("outcome", ""),
                    item.get("detail", ""),
                ])
            return output.getvalue()

        payload = await run_in_threadpool(_build_csv_payload)

        return StreamingResponse(
            iter([payload]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=governance_report_{days}d.csv"},
        )

    @router.get("/api/summary/{session_id:path}")
    async def get_session_summary(session_id: str):
        limit = get_summary_detail_limiter().check(f"summary_detail:{session_id}")
        if not limit.allowed:
            return JSONResponse(
                {
                    "error": "rate_limited",
                    "message": "Too many summary detail requests",
                    "retry_after": round(limit.retry_after, 2),
                },
                status_code=429,
                headers={"Retry-After": str(max(1, int(limit.retry_after)))},
            )

        guard = await run_in_threadpool(_enforce_active_session_workspace, session_id)
        if guard is not None:
            return guard

        generation_mgr = get_generation_mgr()
        if not generation_mgr:
            return JSONResponse({"error": "Generation manager not initialized"}, status_code=503)
        return await run_in_threadpool(
            lambda: {
                "summary": generation_mgr.get_summary(session_id),
                "stats": generation_mgr.get_summary_stats(session_id),
            }
        )

    @router.post("/api/summary/{session_id:path}/rewrite")
    async def rewrite_session_summary(session_id: str, authorization: str | None = Depends(resolve_admin_authorization)):
        limit = get_summary_rewrite_limiter().check(f"summary_rewrite:{session_id}")
        if not limit.allowed:
            return JSONResponse(
                {
                    "error": "rate_limited",
                    "message": "Too many summary rewrite requests",
                    "retry_after": round(limit.retry_after, 2),
                },
                status_code=429,
                headers={"Retry-After": str(max(1, int(limit.retry_after)))},
            )

        auth_error = _require_summary_admin(authorization)
        if auth_error is not None:
            return auth_error

        guard = await run_in_threadpool(_enforce_active_session_workspace, session_id)
        if guard is not None:
            return guard

        generation_mgr = get_generation_mgr()
        llm_client = get_llm_client()
        if not generation_mgr:
            return error_response(code="generation_manager_unavailable", message="Generation manager not initialized", status_code=503)
        if not llm_client:
            return error_response(code="llm_unavailable", message="LLM client not initialized", status_code=503)

        result = await llm_client.rewrite_session_summary(generation_mgr, session_id, source="manual")
        if not result.get("ok"):
            return JSONResponse(result, status_code=400)
        return result

    return router
