const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'../..');const ts=require(path.join(root,'electron/node_modules/typescript'));
const player=path.join(root,'electron/src/renderer/audio/player.ts'),bridgePath=path.join(root,'electron/src/renderer/audio/playbackEventBridge.ts');
const sf=ts.createSourceFile(player,fs.readFileSync(player,'utf8'),ts.ScriptTarget.Latest,true);let adapter;
function visit(n){if(ts.isNewExpression(n)&&n.expression.getText(sf)==='AudioPlayerEventBridge')adapter=n.arguments[0];ts.forEachChild(n,visit)}visit(sf);assert.ok(adapter);
function transpile(s){return ts.transpileModule(s,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText}
const adapterScope={exports:{},getAudioPlayer:()=>{throw Error('Unexpected audio-device access')}};vm.runInNewContext(transpile('export const target=('+adapter.getText(sf)+')'),adapterScope);
const target=adapterScope.exports.target;const bridgeScope={exports:{}};vm.runInNewContext(transpile(fs.readFileSync(bridgePath,'utf8')),bridgeScope);
const handlers=new Map(),host={addEventListener:(k,v)=>handlers.set(k,v),removeEventListener:k=>handlers.delete(k)};const bridge=new bridgeScope.exports.AudioPlayerEventBridge(target);bridge.attach(host);let error;
try{handlers.get('pet:tts-stream-complete')({detail:{generationId:'audit-synthetic'}})}catch(e){error=e}finally{bridge.detach()}
assert.equal(error?.name,'TypeError');assert.match(error.message,/markTtsStreamComplete.*not a function/);
console.log('Actual target keys: '+Object.keys(target).sort().join(', '));console.log('Observed: '+error.name+': '+error.message);console.log('REPRODUCED using actual adapter and bridge. No audio device, TTS or network used.');
