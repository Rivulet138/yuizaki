"""Read-only loopback fixture host for the built renderer; no production processes or data."""
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
ROOT = Path(__file__).resolve().parents[3] / 'electron' / 'dist' / 'renderer'
PORT = 48945
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
class Handler(SimpleHTTPRequestHandler):
 def log_message(self, *args): pass
 def end_headers(self):
  self.send_header('Access-Control-Allow-Origin','*')
  super().end_headers()
 def json_response(self, data, status=200):
  body=json.dumps(data).encode('utf-8')
  self.send_response(status); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
 def do_GET(self):
  path=urlsplit(self.path).path
  if path in ('/','/index.html'):
   body=(ROOT/'index.html').read_text(encoding='utf-8')
   bootstrap=f'<script>window.__YUIZAKI_CONTROL_TOKEN__="acceptance-fixture";window.__YUIZAKI_CONTROL_ORIGIN__="http://localhost:{PORT}";window.__YUIZAKI_API_ORIGIN__="http://localhost:{PORT}";</script>'
   body=body.replace('<head>','<head>'+bootstrap).encode('utf-8')
   self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
  elif path in FIXTURES: self.json_response(FIXTURES[path])
  elif path.startswith('/api/') or path.startswith('/memory/') or path.startswith('/socket.io'):
   if path.endswith('/messages'): self.json_response({'messages':[]})
   elif path.endswith('/tools'): self.json_response({'tools':[]})
   elif 'input-bindings' in path: self.json_response({})
   else: self.json_response({'error':'fixture_route_unavailable','path':path},404)
  else: super().do_GET()
 def do_OPTIONS(self):
  self.send_response(204); self.send_header('Access-Control-Allow-Headers','*'); self.send_header('Access-Control-Allow-Methods','GET,HEAD,OPTIONS'); self.end_headers()
 def reject_write(self): self.json_response({'error':'fixture_host_rejects_mutations'},409)
 do_POST=do_PATCH=do_PUT=do_DELETE=reject_write
if __name__ == '__main__':
 print(f'Fixture renderer at http://127.0.0.1:{PORT}; root={ROOT}',flush=True)
 ThreadingHTTPServer(('127.0.0.1',PORT),partial(Handler,directory=str(ROOT))).serve_forever()
