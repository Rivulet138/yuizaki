from pathlib import Path
import ast,json,collections
ROOT=Path(r'E:\yuizaki');OUT=ROOT/'docs/audit-evidence-2026-11-09'
files=[]
for base in ['python','services']:
 for p in (ROOT/base).rglob('*.py'):
  parts=set(p.relative_to(ROOT).parts)
  if parts.intersection({'.venv','__pycache__','.cache','tests','alembic','tmp','data','CharacterModels'}) or any(x.startswith('tmp') for x in parts):continue
  files.append(p)
result=[];errors=[];routes=[]
for p in sorted(set(files)):
 try:tree=ast.parse(p.read_text(encoding='utf-8-sig'))
 except Exception as e:errors.append({'file':str(p),'error':type(e).__name__});continue
 scopes=[];funcs=[]
 class V(ast.NodeVisitor):
  def visit_ClassDef(self,n):
   scopes.append(n.name);self.generic_visit(n);scopes.pop()
  def visit_FunctionDef(self,n):self.fn(n)
  def visit_AsyncFunctionDef(self,n):self.fn(n)
  def fn(self,n):
   name='.'.join([*scopes,n.name]);calls=[]
   class C(ast.NodeVisitor):
    def visit_FunctionDef(self,x):pass
    def visit_AsyncFunctionDef(self,x):pass
    def visit_ClassDef(self,x):pass
    def visit_Call(self,x):
     try:target=ast.unparse(x.func)
     except Exception:target='<dynamic>'
     calls.append({'line':x.lineno,'target':target});self.generic_visit(x)
   cv=C()
   for stmt in n.body:cv.visit(stmt)
   funcs.append({'name':name,'line':n.lineno,'end_line':n.end_lineno,'async':isinstance(n,ast.AsyncFunctionDef),'calls':calls})
   for d in n.decorator_list:
    if isinstance(d,ast.Call) and isinstance(d.func,ast.Attribute) and d.func.attr in {'get','post','put','patch','delete','websocket','route','on','event'}:
     path=d.args[0].value if d.args and isinstance(d.args[0],ast.Constant) else '<dynamic>'
     routes.append({'file':str(p),'line':n.lineno,'method_or_event':d.func.attr,'path_or_event':path,'handler':name})
   scopes.append(n.name);self.generic_visit(n);scopes.pop()
 V().visit(tree)
 imports=[]
 for n in ast.walk(tree):
  if isinstance(n,ast.Import):imports.extend(a.name for a in n.names)
  elif isinstance(n,ast.ImportFrom):imports.append('.'*n.level+(n.module or ''))
 result.append({'file':str(p),'imports':sorted(set(imports)),'functions':funcs})
summary={'files':len(result),'functions':sum(len(f['functions']) for f in result),'call_sites':sum(len(fn['calls']) for f in result for fn in f['functions']),'route_event_decorators':len(routes),'parse_errors':errors}
payload={'scope':'Static AST inventory only. Calls are textual call sites, not resolved runtime edges. Dynamic registration, decorators, monkeypatch and native/IPC boundaries need manual tracing. No function arguments or data literals are exported.','summary':summary,'routes_and_events':routes,'files':result}
(OUT/'python-call-inventory.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=True))
