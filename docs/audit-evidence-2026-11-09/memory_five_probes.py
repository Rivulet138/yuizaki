import os,socket,sqlite3,sys,threading,json
from contextlib import contextmanager
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'python'))
os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
_original_connect=socket.socket.connect;_original_pair=socket.socketpair;_internal=threading.local()
def guarded_connect(self,address):
 if getattr(_internal,'pair',False) and address[0] in ('127.0.0.1','::1'):return _original_connect(self,address)
 raise RuntimeError('audit_network_disabled')
def guarded_pair(*args,**kwargs):
 _internal.pair=True
 try:return _original_pair(*args,**kwargs)
 finally:_internal.pair=False
socket.socket.connect=guarded_connect;socket.socketpair=guarded_pair
import fastapi
import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient
from modules.memory.sqlite_store import SQLiteMemoryStore
from modules.memory.vector_store import VectorStore,Document
from modules.memory.schema import MemorySearchFilters,RetrievalRequest
from modules.memory.pipeline import RetrievalPipeline
from modules.memory.routes import MemoryState,create_memory_router
print('sys.executable='+sys.executable);print('fastapi='+fastapi.__version__)
class Embedding:
 dimension=2
 def embed(self,text):return np.array([1.0,0.0],dtype=np.float32)
class RAMSQLite(SQLiteMemoryStore):
 def __init__(self):
  VectorStore.__init__(self,embedding_service=Embedding());self._db_lock=threading.RLock();self._index_ready=False;self.ram=sqlite3.connect(':memory:');self._initialize_database()
 @contextmanager
 def _connection(self):
  try:yield self.ram;self.ram.commit()
  except Exception:self.ram.rollback();raise
store=RAMSQLite();filters=MemorySearchFilters(scope='workspace',workspace_id='audit-synthetic',layers=['semantic']);meta={'scope':'workspace','workspace_id':'audit-synthetic','layer':'semantic'}
store.search_with_rerank('synthetic',filters=filters);store.add_metadata_document(Document('synthetic-new','synthetic',meta))
durable=store.ram.execute('SELECT COUNT(*) FROM memory_documents').fetchone()[0];before=len(store.search_with_rerank('synthetic',filters=filters));ready=store._index_ready;store.rebuild_index();after=len(store.search_with_rerank('synthetic',filters=filters))
print(json.dumps({'id':'M-02','durable':durable,'recalled':before,'index_ready':ready,'recalled_after_rebuild':after}));assert (durable,before,ready,after)==(1,0,True,1)
class BrokenEmbedding:
 dimension=2
 def embed(self,text):raise RuntimeError('synthetic_embedding_failure')
store._embedding_service=BrokenEmbedding()
try:store.add_document(Document('synthetic-failed','synthetic',meta))
except RuntimeError as e:print('M-03 caught='+str(e))
durable=store.ram.execute("SELECT COUNT(*) FROM memory_documents WHERE id='synthetic-failed'").fetchone()[0];visible=any(d.id=='synthetic-failed' for d in store.list_documents());print(json.dumps({'id':'M-03','durable':durable,'visible':visible}));assert durable==1 and not visible;store.ram.close()
meta={'scope':'workspace','workspace_id':'synthetic','layer':'semantic'}
docs=[Document('anchor','synthetic anchor',{**meta,'source_ids':[f'rel-{n}' for n in range(6)]})]+[Document(f'rel-{n}','synthetic related',dict(meta)) for n in range(6)]
class Backend:
 def list_documents(self):return docs
 def search_with_rerank(self,**kwargs):return [(docs[0],1.0)]
result=RetrievalPipeline(Backend()).recall(RetrievalRequest(query='synthetic',scope='workspace',workspace_id='synthetic',top_k=10,relation_limit=1));trace={k:v for k,v in result['trace'].items() if k in ('relation_accepted','expansion_truncated','relation_attempted')};print(json.dumps({'id':'M-05','selected':len(result['results']),'trace':trace}));assert len(result['results'])==7 and trace['relation_accepted']==6
store=VectorStore(embedding_service=Embedding());store.add_document(Document('synthetic-candidate','SYNTHETIC_ERASE_MARKER',{**meta,'candidate':True,'review_status':'approved','expires_at':'2020-01-01T00:00:00+00:00'}));app=FastAPI();app.include_router(create_memory_router(MemoryState(store=store),get_active_workspace_id=lambda:'synthetic'))
with TestClient(app) as client:
 preview=client.post('/memory/maintenance/preview',json={'scope':'workspace'});r=client.post('/memory/maintenance/apply',json={'scope':'workspace','confirmation':'PERMANENT_DELETE','preview_token':preview.json()['preview_token']});exported=client.get('/memory/export',params={'include_state':'all'});retained='SYNTHETIC_ERASE_MARKER' in exported.text;print(json.dumps({'id':'M-01','preview_status':preview.status_code,'purge_status':r.status_code,'reported_changed':r.json().get('changed_count'),'remaining_docs':len(store.list_documents()),'export_status':exported.status_code,'export_contains_synthetic_erased_text':retained}));assert r.status_code==200 and retained
store=VectorStore(embedding_service=Embedding());store.add_document(Document('synthetic-doc','synthetic',dict(meta)));app=FastAPI();app.include_router(create_memory_router(MemoryState(store=store),get_active_workspace_id=lambda:'synthetic'))
with TestClient(app) as client:
 changed=client.put('/memory/docs/synthetic-doc',json={'scope':'session'});deletion=client.delete('/memory/docs/synthetic-doc',params={'session_id':'synthetic-session'});doc=store.list_documents()[0];print(json.dumps({'id':'M-04','update_status':changed.status_code,'persisted_scope':doc.metadata.get('scope'),'persisted_session':doc.metadata.get('session_id'),'subsequent_delete_status':deletion.status_code}));assert changed.status_code==200 and doc.metadata.get('session_id') is None and deletion.status_code==403
print('ALL_FIVE_DEFECTS_REPRODUCED; no disk database, model download or outbound connection used.')
