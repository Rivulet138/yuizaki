const fs=require('node:fs'),path=require('node:path');
const ts=require('E:/yuizaki/electron/node_modules/typescript');
const root='E:/yuizaki',out=path.join(root,'docs/audit-evidence-2026-11-09');
function scan(dir){return fs.readdirSync(dir,{withFileTypes:true}).flatMap(e=>e.isDirectory()?(['node_modules','dist','__pycache__','.cache'].includes(e.name)?[]:scan(path.join(dir,e.name))):/\.(ts|vue|mjs|js)$/.test(e.name)&&!/(\.test\.|\.spec\.|test-fixtures|\.d\.ts$)/.test(e.name)?[path.join(dir,e.name)]:[])}
const files=[...scan(path.join(root,'electron/src')),...scan(path.join(root,'node-mcp')),...scan(path.join(root,'tools/yuizaki-mcp'))];const inventory=[];
for(const file of files){const raw=fs.readFileSync(file,'utf8');let code=raw;if(file.endsWith('.vue')){const m=/<script\b[^>]*>([\s\S]*?)<\/script>/i.exec(raw);if(!m)continue;code=raw.slice(0,m.index+m[0].indexOf('>')+1).replace(/[^\n]/g,' ')+m[1];}
const source=ts.createSourceFile(file,code,ts.ScriptTarget.Latest,true,ts.ScriptKind.TS),functions=[],imports=[],rootCalls=[];
function target(e){if(ts.isIdentifier(e)||ts.isPropertyAccessExpression(e)||ts.isElementAccessExpression(e))return e.getText(source).slice(0,180);return '<dynamic-expression>';}
function walk(n,owner){if(ts.isImportDeclaration(n)&&ts.isStringLiteral(n.moduleSpecifier))imports.push(n.moduleSpecifier.text);
if(ts.isFunctionLike(n)&&n.body){let name=n.name?.getText(source)||'';if(!name&&ts.isVariableDeclaration(n.parent))name=n.parent.name.getText(source);if(!name&&ts.isPropertyAssignment(n.parent))name=n.parent.name.getText(source);const row={name:name||'<callback>',line:source.getLineAndCharacterOfPosition(n.getStart(source)).line+1,calls:[]};functions.push(row);owner=row;}
if(ts.isCallExpression(n)){const row={line:source.getLineAndCharacterOfPosition(n.getStart(source)).line+1,target:target(n.expression)};(owner?owner.calls:rootCalls).push(row);}
ts.forEachChild(n,c=>walk(c,owner));}walk(source,null);inventory.push({file:file.replaceAll('\\','/'),imports:[...new Set(imports)].sort(),functions,top_level_calls:rootCalls});}
const summary={files:inventory.length,functions:inventory.reduce((n,f)=>n+f.functions.length,0),call_sites:inventory.reduce((n,f)=>n+f.top_level_calls.length+f.functions.reduce((m,x)=>m+x.calls.length,0),0)};
fs.writeFileSync(path.join(out,'typescript-call-inventory.json'),JSON.stringify({scope:'Static syntax inventory. Textual call sites are not resolved runtime edges; Vue templates, dynamic IPC and callbacks require manual tracing. Tests, declarations, generated bundles and data files excluded.',summary,files:inventory},null,2));console.log(JSON.stringify(summary));
