import sys,json
from pathlib import Path
from fastapi import FastAPI,APIRouter,__version__
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'python'))
from route_manifest import build_route_manifest
app=FastAPI();router=APIRouter()
router.add_api_route('/api/audit-synthetic',lambda:{'ok':True},methods=['GET'])
app.include_router(router)
result={'python':sys.executable,'fastapi':__version__,'route_types':[type(x).__name__ for x in app.routes],'manifest':build_route_manifest(app),'actual_http':TestClient(app).get('/api/audit-synthetic').status_code}
print(json.dumps(result,ensure_ascii=True,indent=2))
