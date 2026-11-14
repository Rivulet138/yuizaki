"""Isolated R5 renderer host. Only a validated synthetic summary PATCH is writable."""
import argparse
import copy
import json
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[4] / "electron" / "dist" / "renderer"
ARGS = argparse.ArgumentParser()
ARGS.add_argument("--port", type=int, default=48949)
PORT = ARGS.parse_args().port
ORIGIN = f"http://localhost:{PORT}"
SETTINGS = {
 'llm': {'provider':'custom','base_url':'','api_key':'','model':'','temperature':0.7,'top_p':0.9,'top_k':0,'min_p':0,'frequency_penalty':0,'presence_penalty':0,'repetition_penalty':1,'timeout':60,'context_max_tokens':32768,'default_max_output_tokens':2048,'profiles':{}},
 'tts': {'genie_character':'','genie_model_dir':'','lang':'ja','ref_audio':'','ref_text':'','device':'cpu','quality':'quality','split':'auto','mode':'serial','save_mode':'disabled','provider':'genie-tts','base_url':'','api_key':'','model':'tts-1','voice':'alloy','timeout':60},
 'asr': {'provider':'disabled','base_url':'','api_key':'','timeout':60,'sensevoice_model':'iic/SenseVoiceSmall','sensevoice_device':'cpu','sherpa_model_path':'','sherpa_tokens_path':'','sherpa_num_threads':2,'sherpa_provider':'cpu','language':'zh','vad_threshold':0.5,'vad_min_silence_ms':400,'asr_partial_every':15},
 'svc': {'provider':'disabled','base_url':'','speaker_id':0,'pitch':0,'timeout':120},
 'summary': {'trigger_messages':24,'keep_recent_messages':8,'item_max_chars':140,'rewrite_interval_messages':6,'quality_scorer_mode':'rule','quality_score_cooldown_seconds':300,'quality_score_budget_per_hour':20},
 'system': {'language':'zh','theme':'light'},
 'memory': {'backend':'sqlite','sqlite_path':'','qdrant_url':'','qdrant_api_key':'','qdrant_collection':'memories','qdrant_timeout':10,'qdrant_auto_start':False,'embedding_model':'fixture','reranker_enabled':False,'reranker_model':'fixture','reranker_candidate_count':32},
}
FIXTURES = {
 '/api/settings/': SETTINGS,
 '/api/settings/runtime/status': {'sections':{}},
 '/api/workspaces': {'workspaces':[{'id':'default','name':'Acceptance fixture','description':'Synthetic workspace','memory_scope':'workspace','context':{'activeTab':'chat','wallpaperMode':False},'created_at':None,'updated_at':None}]},
 '/api/sessions': {'sessions':[{'id':'default','workspace_id':'default','title':'Synthetic chat','created_at':None,'updated_at':None}]},
 '/api/companions': {'companions':[]},
 '/api/pet/catalog': {'models':[]},
 '/api/pet/state': {'visible':True,'modelType':'live2d','modelId':None},
 '/api/settings/llm/status': {'available':False,'model':'','provider':'custom'},
 '/api/settings/tts/status': {'available':False},
 '/api/settings/tts/characters': {'characters':[]},
 '/api/system/ui-capabilities': {'protocol':{'http':True,'socketIo':False},'clients':{'browser':{'coreRoutes':['chat','memory','settings'],'hostCapabilities':{},'limitations':[]}}},
 '/api/system/backend-token': {'hasToken':False,'source':'memory','tokenPreview':''},
 '/api/system/runtime': {'apiOrigin':f'http://localhost:{PORT}','pythonApiOrigin':f'http://localhost:{PORT}'},
 '/health': {'status':'ok','service':'yuizaki-control','pythonRunning':False},
 '/api/health': {'status':'ok','service':'yuizaki-control'},
 '/memory/docs': {'docs':[]},
 '/memory/overview': {'total':0,'recallable':0,'by_state':{},'by_layer':{},'by_source':{},'by_review_status':{},'latest_activity':[]},
 '/memory/candidates': {'candidates':[]},
 '/memory/operations': {'operations':[]},
 '/memory/index/status': {'status':'ok','count':0,'backend':'sqlite','healthy':True},
}

LOCK = threading.Lock()
RELEASE = threading.Event()
STATE = {}
SERVER = None

def reset(name, normalized):
    with LOCK:
        if STATE.get("token_pending"):
            raise ValueError("Previous token request is still pending")
        STATE.clear()
        STATE.update(name=name, normalized=normalized, settings=copy.deepcopy(SETTINGS),
                     requests=[], rejected=[], token_pending=False, token_started=0,
                     token_completed=0, token_timeouts=0)
        RELEASE.clear()

reset("startup", True)

class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def json_response(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def record(self):
        entry = {"method": self.command, "path": urlsplit(self.path).path,
                 "started": time.perf_counter()}
        with LOCK:
            STATE["requests"].append(entry)
        return entry

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/__fixture/state":
            with LOCK:
                snapshot = copy.deepcopy(STATE)
            self.json_response(snapshot)
            return
        entry = self.record()
        try:
            if path in ("/", "/index.html"):
                text = (ROOT / "index.html").read_text(encoding="utf-8")
                bootstrap = (f'<script>window.__YUIZAKI_CONTROL_TOKEN__="r5-fixture";'
                             f'window.__YUIZAKI_CONTROL_ORIGIN__="{ORIGIN}";'
                             f'window.__YUIZAKI_API_ORIGIN__="{ORIGIN}";</script>')
                body = text.replace("<head>", "<head>" + bootstrap).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path == "/api/settings/":
                time.sleep(.15)
                self.json_response(copy.deepcopy(STATE["settings"]))
            elif path == "/api/system/backend-token":
                with LOCK:
                    STATE["token_started"] += 1
                    STATE["token_pending"] = True
                if not RELEASE.wait(20):
                    with LOCK:
                        STATE["token_timeouts"] += 1
                    self.json_response({"error": "fixture_gate_not_released"}, 504)
                else:
                    self.json_response({"hasToken": True, "source": "memory",
                                        "tokenPreview": "R5_fixture_preview", "requiresRestart": False})
                    with LOCK:
                        STATE["token_completed"] += 1
                with LOCK:
                    STATE["token_pending"] = False
            elif path in FIXTURES:
                data = FIXTURES[path]
                if path == "/api/system/runtime":
                    data = {"apiOrigin": ORIGIN, "pythonApiOrigin": ORIGIN}
                self.json_response(data)
            elif path.startswith(("/api/", "/memory/", "/socket.io")):
                if path.endswith("/messages"):
                    self.json_response({"messages": []})
                elif path.endswith("/tools"):
                    self.json_response({"tools": []})
                elif "input-bindings" in path:
                    self.json_response({})
                else:
                    self.json_response({"error": "fixture_route_unavailable", "path": path}, 404)
            else:
                super().do_GET()
        finally:
            entry["finished"] = time.perf_counter()

    def do_POST(self):
        path = urlsplit(self.path).path
        if path == "/__fixture/configure":
            payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            reset(payload["name"], payload.get("normalized", True))
            self.json_response({"ok": True})
        elif path == "/__fixture/release-token":
            RELEASE.set()
            self.json_response({"ok": True})
        else:
            self.reject_write()

    def do_PATCH(self):
        entry = self.record()
        path = urlsplit(self.path).path
        patch = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if (path != "/api/settings/" or not isinstance(patch, dict)
                or set(patch) != {"summary"} or not isinstance(patch["summary"], dict)
                or set(patch["summary"]) != {"trigger_messages"}
                or type(patch["summary"]["trigger_messages"]) is not int
                or not 1 <= patch["summary"]["trigger_messages"] <= 100):
            self.reject_write(entry)
            return
        entry["patch"] = patch
        STATE["settings"]["summary"].update(patch["summary"])
        time.sleep(.15)
        result = {"status": "success", "updated": ["summary"], "runtime_applied": [],
                  "runtime_changed": False, "runtime_reload": {"sections": {}}}
        if STATE["normalized"]:
            result["normalized_settings"] = copy.deepcopy(STATE["settings"])
        self.json_response(result)
        entry["finished"] = time.perf_counter()

    def reject_write(self, entry=None):
        entry = entry or self.record()
        STATE["rejected"].append({"method": self.command, "path": urlsplit(self.path).path})
        self.json_response({"error": "fixture_host_rejects_nonfixture_mutation"}, 409)
        entry["finished"] = time.perf_counter()

    do_PUT = do_DELETE = reject_write

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

if __name__ == "__main__":
    if not (ROOT / "index.html").is_file():
        raise SystemExit(f"Renderer build missing: {ROOT}")
    SERVER = ThreadingHTTPServer(("127.0.0.1", PORT), partial(Handler, directory=str(ROOT)))
    SERVER.daemon_threads = True
    print(f"R5 fixture at {ORIGIN}; renderer={ROOT}", flush=True)
    SERVER.serve_forever()
