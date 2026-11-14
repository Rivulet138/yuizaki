import { createServer } from './node_modules/vite/dist/node/index.js';
import vue from './node_modules/@vitejs/plugin-vue/dist/index.mjs';
import os from 'node:os';
import path from 'node:path';
const root=process.cwd();
const fixture=`import { reactive, ref } from 'vue';
export const currentLocale=ref('en'); export const t=(key)=>key;
const ws=reactive({activeWorkspace:{id:'fixture',memory_scope:'workspace',context:{}}});
export const useWorkspaceStore=()=>ws;
export const useSessionStore=()=>({activeSession:{id:'session-fixture'}});
export const memoryClient={
 getDocs:async(o)=>({docs:o?.includeState==='forgotten'?[]:[{id:'review-doc',text:'ISOLATED MEMORY',metadata:{scope:'workspace',workspace_id:'fixture',layer:'semantic',type:'fact',review_status:'approved',importance:0.8}}]}),
 getOverview:async()=>({total:1,by_layer:{semantic:1},by_state:{active:1},by_source:{manual:1},by_review_status:{approved:1},latest_activity:[]}),
 getCandidates:async()=>({candidates:[]}), getOperations:async()=>({operations:[]}), getIndexStatus:async()=>({status:'ok',count:1,healthy:true}),
};`;
const entry=`import {createApp,h,KeepAlive,defineComponent} from 'vue';
import {createRouter,createMemoryHistory,RouterView} from 'vue-router';
import MemoryPanel from '/src/renderer/domains/memory/views/MemoryPanel.vue';
const Other=defineComponent({name:'OtherPanel',setup:()=>()=>h('button',{id:'other-action',onClick:()=>window.otherClicks++},'OTHER PANEL ACTION')});
const router=createRouter({history:createMemoryHistory(),routes:[{path:'/w/:workspaceId/memory',name:'memory',component:MemoryPanel},{path:'/w/:workspaceId/other',name:'other',component:Other}]});
window.otherClicks=0; window.reviewRouter=router;
const App=defineComponent({setup:()=>()=>h(RouterView,{}, {default:({Component})=>h(KeepAlive,{},()=>Component)})});
router.push('/w/fixture/memory?edit=review-doc');await router.isReady();createApp(App).use(router).mount('#app');`;
const replacements=['/src/renderer/api/client.ts','/src/renderer/api/clients/memory-client.ts','/src/renderer/stores/workspaceStore.ts','/src/renderer/stores/sessionStore.ts','/src/renderer/i18n/index.ts'];
let server;
server=await createServer({configFile:false,root,cacheDir:path.join(os.tmpdir(),'yuizaki-memory-review-vite'),plugins:[{name:'readonly-memory-review',enforce:'pre',resolveId(id){if(id==='/__review_fixture__.js'||id==='/__review_entry__.js')return '\0'+id;},load(id){if(id==='\0/__review_fixture__.js')return fixture;if(id==='\0/__review_entry__.js')return entry;const normalized=id.replaceAll('\\','/').split('?')[0];if(replacements.some(x=>normalized.endsWith(x)))return `export * from '/__review_fixture__.js';`;},configureServer(s){s.middlewares.use((req,res,next)=>{if(req.url==='/'){res.setHeader('Content-Type','text/html');res.end('<!doctype html><html><head><meta charset="UTF-8"></head><body><div id="app"></div><script type="module" src="/__review_entry__.js"></script></body></html>');}else if(req.url==='/__shutdown'){res.end('closed');setTimeout(()=>s.close().then(()=>process.exit(0)),100);}else next();});}},vue()],resolve:{alias:{'@':path.join(root,'src/renderer')}},server:{host:'127.0.0.1',port:48947,strictPort:true},optimizeDeps:{noDiscovery:true,include:['vue','vue-router','element-plus','@element-plus/icons-vue']},logLevel:'warn'});
await server.listen();console.log('READONLY_REVIEW_HARNESS http://127.0.0.1:48947');
setTimeout(()=>server.close().then(()=>process.exit(0)),600000).unref();
