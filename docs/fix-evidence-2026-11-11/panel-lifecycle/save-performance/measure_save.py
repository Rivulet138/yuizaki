"""R5 browser acceptance. Starts/stops its own fixture; never starts a real backend.

Run: python measure_save.py --label current-dist
     python measure_save.py --label mainline-final (after the mainline rebuild)
A distinct label preserves prior runs. No browser-script fetches trigger token GET.
"""
import argparse
import hashlib
import json
import platform
import socket
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, expect

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
DIST = ROOT / "electron" / "dist" / "renderer"
PARSER = argparse.ArgumentParser(description=__doc__)
PARSER.add_argument("--port", type=int, default=48949)
PARSER.add_argument("--label", default="current-dist")
ARGS = PARSER.parse_args()
if not ARGS.label or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in ARGS.label):
    PARSER.error("label must contain only ASCII letters, numbers, - or _")
ORIGIN = f"http://localhost:{ARGS.port}"
RUN = OUT / ARGS.label
TOKEN = "/api/system/backend-token"
SETTINGS = "/api/settings/"

def control(path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    request = Request(ORIGIN.replace("localhost", "127.0.0.1") + "/__fixture/" + path, data=data,
                      headers={"Content-Type": "application/json"} if data else {})
    with urlopen(request, timeout=5) as response:
        return json.load(response)

def fingerprint():
    files = []
    for path in sorted(DIST.rglob("*")):
        if path.is_file():
            content = path.read_bytes()
            files.append({"path": path.relative_to(DIST).as_posix(), "bytes": len(content),
                          "sha256": hashlib.sha256(content).hexdigest(),
                          "mtime_ns": path.stat().st_mtime_ns})
    digest = hashlib.sha256(json.dumps([{k: v for k, v in f.items() if k != "mtime_ns"} for f in files], sort_keys=True).encode()).hexdigest()
    return {"sha256": digest, "files": files}

def save_json(name, value):
    (RUN / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

def count(requests, method, path):
    return sum(r["method"] == method and r["path"] == path for r in requests)

class Case:
    def __init__(self, browser, name, normalized=True):
        control("configure", {"name": name, "normalized": normalized})
        self.name = name
        self.start = time.perf_counter()
        self.events = []
        self.requests = []
        self.errors = []
        self.console_errors = []
        self.blocked = []
        self.initiators = []
        self.context = browser.new_context(viewport={"width": 1440, "height": 1000}, service_workers="block")
        self.context.add_init_script("localStorage.setItem('yuizaki.onboarding.completed.v1','true')")
        self.context.route("**/*", self.guard)
        self.page = self.context.new_page()
        self.page.set_default_timeout(15000)
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.on("console", lambda m: self.console_errors.append(m.text) if m.type == "error" else None)
        self.page.on("request", self.requested)
        self.page.on("requestfinished", lambda r: self.mark("request_finished", method=r.method, path=urlsplit(r.url).path))
        self.page.on("requestfailed", lambda r: self.mark("request_failed", method=r.method, path=urlsplit(r.url).path, failure=r.failure))
        cdp = self.context.new_cdp_session(self.page)
        cdp.send("Network.enable")
        cdp.on("Network.requestWillBeSent", self.initiator)

    def mark(self, event, **details):
        at = time.perf_counter()
        self.events.append({"event": event, "at": at, "ms": round((at - self.start) * 1000, 2), **details})
        return at

    def requested(self, request):
        path = urlsplit(request.url).path
        if path.startswith(("/api/", "/memory/", "/socket.io")):
            entry = {"method": request.method, "path": path, "resource_type": request.resource_type,
                     "at": time.perf_counter()}
            if request.method == "PATCH":
                entry["patch"] = request.post_data_json
            self.requests.append(entry)
            self.mark("request_started", method=request.method, path=path)

    def initiator(self, event):
        if urlsplit(event["request"]["url"]).path == TOKEN:
            self.initiators.append({"url": event["request"]["url"], "initiator": event.get("initiator"),
                                    "request_id": event["requestId"], "timestamp": event["timestamp"]})

    def guard(self, route):
        req = route.request
        url = urlsplit(req.url)
        allowed_origin = url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1") and url.port == ARGS.port
        safe_method = req.method in ("GET", "HEAD", "OPTIONS")
        fixture_patch = allowed_origin and req.method == "PATCH" and url.path == SETTINGS
        if not allowed_origin or (not safe_method and not fixture_patch):
            self.blocked.append({"method": req.method, "url": req.url})
            route.fulfill(status=409, json={"error": "R5_blocks_nonfixture_network"})
        else:
            route.continue_()

    def open(self, section):
        self.page.goto(f"{ORIGIN}/#/w/default/settings?section={section}", wait_until="domcontentloaded")

    def summary_field(self):
        self.page.locator(".summary-advanced summary").click()
        field = self.page.locator(".summary-settings-group").first.get_by_role("spinbutton").first
        expect(field).to_be_visible()
        expect(field).to_be_enabled()
        expect(field).to_be_editable()
        return field

    def finish(self, **metrics):
        state = control("state")
        first_read = next((r["started"] for r in state["requests"] if r["method"] == "GET" and r["path"] == SETTINGS), None)
        result = {"name": self.name, "passed": True, **metrics,
                  "http_counts": {"settings_GET": count(state["requests"], "GET", SETTINGS),
                                  "settings_PATCH": count(state["requests"], "PATCH", SETTINGS),
                                  "backend_token_GET": count(state["requests"], "GET", TOKEN),
                                  "runtime_status_GET": count(state["requests"], "GET", "/api/settings/runtime/status")},
                  "pageerrors": self.errors, "console_errors": self.console_errors,
                  "blocked_browser_requests": self.blocked, "host_rejected_mutations": state["rejected"],
                  "token_started": state["token_started"], "token_completed": state["token_completed"],
                  "first_settings_get_at": first_read}
        save_json(self.name + ".json", {"result": result, "browser_requests": self.requests,
                                         "timeline": self.events, "token_initiators": self.initiators,
                                         "fixture_state": state})
        assert not self.errors, self.errors
        assert all(urlsplit(r["url"]).hostname in ("localhost", "127.0.0.1") and urlsplit(r["url"]).port == ARGS.port and r["method"] not in ("GET", "HEAD", "OPTIONS") for r in self.blocked), self.blocked
        assert not state["rejected"], state["rejected"]
        assert state["token_timeouts"] == 0, state
        self.context.close()
        return result

    def failure(self):
        try:
            self.page.screenshot(path=str(RUN / (self.name + "-failure.png")), full_page=True)
            save_json(self.name + "-failure.json", {"timeline": self.events, "browser_requests": self.requests,
                                                     "fixture_state": control("state"), "error": traceback.format_exc()})
        finally:
            control("release-token", {})
            self.context.close()

def discover(browser):
    case = Case(browser, "discovery")
    try:
        case.open("summary")
        case.page.wait_for_load_state("networkidle")
        field = case.summary_field()
        assert field.input_value() == "24", "fixture settings did not hydrate the rendered form"
        assert control("state")["token_started"] == 0
        assert count(control("state")["requests"], "GET", SETTINGS) >= 1
        save_json("discovery-dom.json", case.page.evaluate("""() => ({url: location.href,
          tabs: [...document.querySelectorAll('.settings-section-nav [role=tab]')].map(e => ({text:e.textContent,controls:e.getAttribute('aria-controls')})),
          summaryInputs: [...document.querySelectorAll('.summary-settings-group input')].map(e => ({role:e.getAttribute('role'),value:e.value,disabled:e.disabled}))})"""))
        case.page.screenshot(path=str(RUN / "discovery-summary.png"), full_page=True)
        return case.finish(purpose="DOM reconnaissance and direct-summary negative control", expected_token_requests=0)
    except Exception:
        case.failure()
        raise

def token_case(browser):
    case = Case(browser, "token-access-summary")
    try:
        with case.page.expect_request(lambda r: urlsplit(r.url).path == TOKEN and r.method == "GET") as token_request:
            case.open("access")
        assert token_request.value.resource_type == "fetch"
        deadline = time.monotonic() + 5
        while control("state")["token_started"] == 0:
            assert time.monotonic() < deadline, "browser token request never reached fixture host"
            case.page.wait_for_timeout(10)
        case.mark("token_started_confirmed_by_host")
        access_input = case.page.locator(".backend-token-input input")
        expect(access_input).to_be_visible()
        expect(access_input).to_be_editable()
        # networkidle is deliberately unsuitable here: the real frontend token request is held open.
        case.page.locator('.settings-section-nav [aria-controls="pane-summary"]').click()
        field = case.summary_field()
        field.focus()
        assert field.input_value() == "24", "fixture settings did not hydrate the rendered form"
        ready = case.mark("summary_form_ready", value=field.input_value(), visible=field.is_visible(),
                          enabled=field.is_enabled(), editable=field.is_editable())
        state = control("state")
        assert state["token_started"] == 1, "frontend did not start exactly one token GET"
        assert state["token_pending"] and state["token_completed"] == 0, "token must still be pending at form readiness"
        assert count(case.requests, "GET", TOKEN) == 1
        assert not any(e["event"] == "request_finished" and e.get("path") == TOKEN for e in case.events)
        assert count(state["requests"], "PATCH", SETTINGS) == 0
        save_json("token-pending-at-summary-ready.json", {"observed_at": ready, "host_state": state,
                                                         "browser_token_finished": False})
        case.page.screenshot(path=str(RUN / "token-pending-summary-ready.png"), full_page=True)
        case.page.locator('.settings-section-nav [aria-controls="pane-access"]').click()
        expect(case.page.locator(".backend-token-input input")).to_be_editable()
        expect(case.page.locator(".access-token-details")).to_have_count(0)
        state = control("state")
        assert state["token_started"] == 1 and state["token_pending"]
        release = case.mark("release_token_gate")
        with case.page.expect_event("requestfinished", predicate=lambda r: urlsplit(r.url).path == TOKEN):
            control("release-token", {})
        expect(case.page.locator(".access-token-details")).to_contain_text("R5_fixture_preview")
        presented = case.mark("token_completion_presented")
        state = control("state")
        assert state["token_completed"] == 1 and not state["token_pending"]
        assert count(case.requests, "GET", TOKEN) == 1
        assert len(case.initiators) == 1 and case.initiators[0]["initiator"]["type"] == "script"
        token_start = next(r["started"] for r in state["requests"] if r["path"] == TOKEN)
        token_end = next(r["finished"] for r in state["requests"] if r["path"] == TOKEN)
        read_start = next(r["started"] for r in state["requests"] if r["path"] == SETTINGS)
        assert read_start < token_start < ready < release < token_end < presented
        case.page.wait_for_load_state("networkidle")
        case.page.screenshot(path=str(RUN / "token-completed-access.png"), full_page=True)
        return case.finish(token_request_started=True, summary_ready_while_token_pending=True,
                           completion_verified_in_browser_and_ui=True,
                           form_ready_from_settings_get_ms=round((ready-read_start)*1000,2),
                           token_start_to_summary_ready_ms=round((ready-token_start)*1000,2),
                           token_pending_total_ms=round((token_end-token_start)*1000,2),
                           release_to_token_presented_ms=round((presented-release)*1000,2),
                           flow="navigate access -> click summary -> click access while pending -> release fixture gate -> UI preview")
    except Exception:
        case.failure()
        raise

def save_case(browser, normalized):
    name = "save-normalized" if normalized else "save-legacy"
    case = Case(browser, name, normalized)
    try:
        case.open("summary")
        case.page.wait_for_load_state("networkidle")
        field = case.summary_field()
        before = control("state")
        assert before["token_started"] == 0, "save scenario must stay separate from token scenario"
        baseline_reads = count(before["requests"], "GET", SETTINGS)
        assert baseline_reads >= 1
        assert field.input_value() == "24", "fixture settings did not hydrate the rendered form"
        original = int(field.input_value())
        changed = original + 1 if original < 100 else original - 1
        start = case.mark("edit_started", original=original, changed=changed)
        field.fill(str(changed))
        field.press("Tab")
        saved_alert = case.page.locator(".settings-panel > .el-alert--success")
        expect(saved_alert).to_contain_text("\u5df2\u4fdd\u5b58")
        saved = case.mark("saved_ui_visible")
        expect(field).to_have_value(str(changed))
        # Covers two 500ms debounce windows and network drain after the saved acknowledgement.
        case.page.wait_for_timeout(1100)
        case.page.wait_for_load_state("networkidle")
        state = control("state")
        patches = [r for r in state["requests"] if r["method"] == "PATCH" and r["path"] == SETTINGS]
        readbacks = count(state["requests"], "GET", SETTINGS) - baseline_reads
        assert len(patches) == 1, patches
        assert patches[0]["patch"] == {"summary": {"trigger_messages": changed}}, patches
        assert readbacks == (0 if normalized else 1), readbacks
        assert count(case.requests, "PATCH", SETTINGS) == 1
        assert count(case.requests, "GET", SETTINGS) == baseline_reads + readbacks
        assert state["token_started"] == 0
        assert state["settings"]["summary"]["trigger_messages"] == changed
        case.page.screenshot(path=str(RUN / (name + ".png")), full_page=True)
        return case.finish(normalized_response=normalized, save_PATCH=1, save_readbacks=readbacks,
                           initial_settings_reads=baseline_reads,
                           edit_to_request_ms=round((patches[0]["started"]-start)*1000,2),
                           edit_to_saved_ms=round((saved-start)*1000,2),
                           duplicate_request_observation_ms=1100)
    except Exception:
        case.failure()
        raise

def main():
    if RUN.exists():
        raise SystemExit(f"Run directory already exists; use a new --label to preserve evidence: {RUN}")
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", ARGS.port))
        except OSError as error:
            raise SystemExit(f"Port {ARGS.port} is already in use; no service was stopped: {error}")
    RUN.mkdir()
    result = {"run_label": ARGS.label, "started_utc": datetime.now(timezone.utc).isoformat(),
              "python": platform.python_version(), "origin": ORIGIN, "cases": [], "passed": False,
              "fixture_settings_delay_ms": 150, "fixture_patch_delay_ms": 150,
              "token_delay": "explicit release gate; 20s timeout is a failure",
              "limitations": ["Synthetic HTTP fixture and Chromium; no real backend or Electron IPC",
                              "Timings include browser/UI automation and injected fixture latency; one sample per case",
                              "Evidence applies only to the captured renderer fingerprint; rerun after mainline rebuild"]}
    before = fingerprint()
    save_json("dist-before.json", before)
    proc = None
    try:
        with (RUN / "fixture-host.log").open("w", encoding="utf-8") as log:
            proc = subprocess.Popen([sys.executable, "-u", str(OUT / "fixture_host.py"), "--port", str(ARGS.port)],
                                    cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
            result["fixture_pid"] = proc.pid
            deadline = time.monotonic() + 10
            while True:
                if proc.poll() is not None:
                    raise RuntimeError("Fixture failed to start; see fixture-host.log")
                try:
                    control("state")
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise
                    time.sleep(.05)
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                result["chromium"] = browser.version
                try:
                    for run in (lambda: discover(browser), lambda: token_case(browser),
                                lambda: save_case(browser, True), lambda: save_case(browser, False)):
                        case = run()
                        result["cases"].append(case)
                        print(json.dumps(case, ensure_ascii=True), flush=True)
                finally:
                    browser.close()
            after = fingerprint()
            save_json("dist-after.json", after)
            result["renderer_sha256"] = before["sha256"]
            result["renderer_unchanged_during_run"] = before["sha256"] == after["sha256"]
            assert result["renderer_unchanged_during_run"], "Renderer changed during run; rerun with a new label"
            result["passed"] = True
    except Exception:
        result["error"] = traceback.format_exc()
        raise
    finally:
        if proc is not None:
            proc.terminate()
            proc.wait(timeout=10)
            result["fixture_exit_code"] = proc.returncode
        with socket.socket() as probe:
            result["fixture_port_closed"] = probe.connect_ex(("127.0.0.1", ARGS.port)) != 0
        result["finished_utc"] = datetime.now(timezone.utc).isoformat()
        save_json("results.json", result)
        print(json.dumps({k:v for k,v in result.items() if k != "cases"}, ensure_ascii=True), flush=True)
    assert result["fixture_port_closed"], "Fixture port remained open"

if __name__ == "__main__":
    main()
