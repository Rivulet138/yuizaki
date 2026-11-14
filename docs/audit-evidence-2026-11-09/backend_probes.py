import ast,asyncio,pathlib,types,time,logging,datetime,sys,os
from importlib.metadata import version
ROOT=pathlib.Path(__file__).resolve().parents[2];os.chdir(ROOT);N=types.SimpleNamespace
print(sys.executable,sys.version.split()[0],version('fastapi'))
def load(file,names,ns):
 t=ast.parse(pathlib.Path(file).read_text(encoding='utf-8'));nodes=[n for n in ast.walk(t) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.col_offset==4 and n.name in names];assert len(nodes)==len(names)
 for node in nodes:
  node.decorator_list=[]
  for n in ast.walk(node):
   if isinstance(n,ast.arg):n.annotation=None
   if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):n.returns=None
 exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),file,'exec'),ns)
async def main():
 for status in (401,404,405):
  class Client:
   def __init__(self,**kw):pass
   async def __aenter__(self):return self
   async def __aexit__(self,*a):pass
   async def get(self,url):return N(status_code=status)
  ns=dict(cast=lambda t,v:v,httpx=N(AsyncClient=Client,RequestError=RuntimeError),_safe_probe_url=lambda u:u);load('python/modules/system/settings_api.py',{'test_svc_connection'},ns)
  async def settings():return {'svc':{'provider':'soulx-service','base_url':'http://stub.invalid'}}
  r=await ns['test_svc_connection'](N(_validated_settings_dump_async=settings));assert r['ok'] is True;print('REPRO B-01 svc_probe status='+str(status)+' ok=True')
 ns=dict(asyncio=asyncio,time=time,_generation_cancelled=lambda g:g.invalidated or g.cancel.is_set(),httpx=N(HTTPError=RuntimeError),logger=logging.getLogger('audit'));load('python/modules/tts/openai_compatible.py',{'synthesize_stream_segment','_cancel_active_request'},ns)
 started={};requests={}
 async def audio(text):requests[text]=asyncio.current_task();started[text].set();await asyncio.Event().wait()
 async def ready():return True
 o=N(_request_audio=audio,ensure_ready=ready,_active_request=None,diagnostics=N(record=lambda *a,**k:None),_cancel_count=0);o._cancel_active_request=types.MethodType(ns['_cancel_active_request'],o);gens=[N(invalidated=False,cancel=asyncio.Event()) for _ in range(2)];tasks=[]
 for i,text in enumerate(('A','B')):
  started[text]=asyncio.Event();tasks.append(asyncio.create_task(ns['synthesize_stream_segment'](o,None,gens[i],text,1)));await started[text].wait()
 gens[0].cancel.set();tasks[0].cancel();await asyncio.wait_for(asyncio.gather(*tasks,return_exceptions=True),1);assert requests['A'].cancelled() and requests['B'].cancelled();print('REPRO B-02 tts cancel_A_also_cancels_B')
 async def blocked(*a):await asyncio.Event().wait()
 ns={'asyncio':N(get_running_loop=asyncio.get_running_loop,to_thread=blocked,CancelledError=asyncio.CancelledError)};load('python/modules/asr/transcriber.py',{'_transcribe'},ns);o=N(language='stub',diagnostics=N(record_elapsed=lambda *a,**k:None));a=N(mark=lambda *a:None,transcribe_sync=lambda *a:None);r=await asyncio.wait_for(ns['_transcribe'](o,None,'synthetic',None,a,None,True),.01);assert r is None;print('REPRO B-03 asr returns_None_not_TimeoutError')
 ns={'datetime':datetime.datetime};load('python/modules/agent_plugins/manager.py',{'set_enabled','_append_trace'},ns);saves=[];o=N(_states={'sample':{'enabled':True}},plugins={},_registry=None,_trace=[],_save_store=lambda:saves.append(True));o._append_trace=types.MethodType(ns['_append_trace'],o);r=ns['set_enabled'](o,'sample',False);assert r['enabled'] is False and not saves;print('REPRO B-04 plugin persistence_calls=0')
 t=ast.parse(pathlib.Path('python/routes/ai_api.py').read_text(encoding='utf-8'));g=next(n for n in ast.walk(t) if isinstance(n,ast.AsyncFunctionDef) and n.name=='stream_generator');ys=[n.lineno for n in ast.walk(g) if isinstance(n,ast.Yield)];waits=[n.lineno for n in ast.walk(g) if isinstance(n,ast.Await) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Attribute) and n.value.func.attr in {'run_streaming','execute_streaming_context'}];assert len(waits)==2 and min(ys)>max(waits);print('STATIC B-05 HTTP stream waits='+str(sorted(waits))+' earliest_yield='+str(min(ys)))
 print('SIX_DYNAMIC_SCENARIOS_AND_ONE_STATIC_CHECK_REPRODUCED; extracted real functions, stubbed boundaries, no network/model/data access.')
asyncio.run(main())
