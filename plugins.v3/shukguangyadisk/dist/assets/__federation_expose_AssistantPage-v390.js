import BasePage from './__federation_expose_AssistantPage-v352.js?v=3.9.1';
import { importShared } from './__federation_fn_import-054b33c3.js';

const { defineComponent, h, ref, computed, onMounted, onUnmounted } = await importShared('vue');
const PLUGIN_ID = 'ShukGuangYaDisk';

async function getApi(props, path) {
  const endpoint = `plugin/${PLUGIN_ID}${path}`;
  if (props.api?.get) return props.api.get(endpoint);
  const r = await fetch(`/api/v1/plugin/${PLUGIN_ID}${path}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

async function postApi(props, path, body = {}) {
  const endpoint = `plugin/${PLUGIN_ID}${path}`;
  if (props.api?.post) return props.api.post(endpoint, body);
  const r = await fetch(`/api/v1/plugin/${PLUGIN_ID}${path}`, {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify(body)
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

const css = `
.gya390{width:100%;margin-bottom:10px;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;color:rgb(var(--v-theme-on-surface))}
.gya390-card{background:rgb(var(--v-theme-surface));border:1px solid rgba(var(--v-theme-on-surface),.09);border-radius:14px;padding:14px 16px}
.gya390-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:11px}.gya390-title{font-size:14px;font-weight:760}.gya390-sub{font-size:10.5px;opacity:.58;line-height:1.55;margin-top:3px}
.gya390-actions{display:flex;gap:8px;flex-wrap:wrap}.gya390-btn{height:35px;padding:0 13px;border-radius:8px;border:1px solid rgba(var(--v-theme-on-surface),.13);background:transparent;color:inherit;cursor:pointer;font-size:11px}.gya390-btn.primary{background:rgb(var(--v-theme-primary));border-color:transparent;color:rgb(var(--v-theme-on-primary))}.gya390-btn.warn{border-color:rgba(245,158,11,.48);color:#f59e0b}.gya390-btn:disabled{opacity:.42;cursor:not-allowed}
.gya390-state{margin-top:11px;display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:7px}.gya390-stat{border:1px solid rgba(var(--v-theme-on-surface),.075);border-radius:8px;padding:8px 9px;min-width:0}.gya390-stat span{display:block;font-size:9px;opacity:.48}.gya390-stat b{display:block;font-size:12px;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.gya390-progress{margin-top:9px;padding:9px 10px;border-radius:8px;background:rgba(var(--v-theme-primary),.05);font-size:10px;line-height:1.65;word-break:break-all}.gya390-progress strong{color:rgb(var(--v-theme-primary))}.gya390-msg{margin-top:9px;padding:8px 10px;border-radius:8px;font-size:10.5px;background:rgba(16,185,129,.08);color:#10b981}.gya390-msg.warn{background:rgba(245,158,11,.08);color:#f59e0b}.gya390-msg.error{background:rgba(239,68,68,.08);color:#ef4444}
@media(max-width:900px){.gya390-head{display:block}.gya390-actions{margin-top:10px}.gya390-state{grid-template-columns:repeat(2,minmax(0,1fr))}}
`;

function fmtTime(v){
  const n=Number(v||0);
  if(!n)return '-';
  try{return new Date(n*1000).toLocaleString();}catch{return '-';}
}

export default defineComponent({
  name:'GuangYaAssistantV390',
  props:{initialConfig:{type:Object,default:()=>({})},api:{type:Object,default:null}},
  emits:['close','switch'],
  setup(props,{emit}){
    const status=ref({});
    const busy=ref('');
    const message=ref('');
    const messageKind=ref('ok');
    let timer=null;
    const fullActive=computed(()=>Boolean(status.value?.full_scan_active));
    const workerPath=computed(()=>status.value?.current_task_path||'-');

    function setMsg(text,kind='ok'){
      message.value=text||'';
      messageKind.value=kind;
    }

    async function loadStatus(silent=true){
      try{
        const r=await getApi(props,'/organize/monitor/status');
        if(!r?.success)throw new Error(r?.message||'读取监控状态失败');
        status.value=r?.data?.status||{};
      }catch(e){
        if(!silent)setMsg(e?.message||'读取监控状态失败','error');
      }
    }

    async function action(kind,path){
      busy.value=kind;
      setMsg('');
      try{
        const r=await postApi(props,path,{});
        if(!r?.success)throw new Error(r?.message||'操作失败');
        setMsg(r?.message||'操作已提交','ok');
        await loadStatus(true);
      }catch(e){
        setMsg(e?.message||'操作失败','error');
      }finally{
        busy.value='';
      }
    }

    onMounted(async()=>{
      await loadStatus(true);
      timer=setInterval(()=>loadStatus(true),3000);
    });
    onUnmounted(()=>{if(timer)clearInterval(timer);});

    const control=()=>h('div',{class:'gya390'},[
      h('style',css),
      h('div',{class:'gya390-card'},[
        h('div',{class:'gya390-head'},[
          h('div',[
            h('div',{class:'gya390-title'},'整理监控控制 · v3.9.1'),
            h('div',{class:'gya390-sub'},'安装期零副作用；持续目录观察负责发现，持久待整理队列负责排队，单 Worker 串行执行；全量巡检独立补漏。')
          ]),
          h('div',{class:'gya390-actions'},[
            h('button',{class:'gya390-btn',disabled:Boolean(busy.value),onClick:()=>action('incremental','/organize/monitor/incremental-scan')},busy.value==='incremental'?'观察中…':'增量观察一次'),
            h('button',{class:'gya390-btn primary',disabled:Boolean(busy.value),onClick:()=>action('full','/organize/monitor/full-scan')},busy.value==='full'?'启动中…':fullActive.value?'继续全量巡检':'强制全量巡检'),
            h('button',{class:'gya390-btn warn',disabled:Boolean(busy.value)||!fullActive.value,onClick:()=>action('stop','/organize/monitor/full-scan/stop')},'停止全量巡检'),
            h('button',{class:'gya390-btn',disabled:Boolean(busy.value),onClick:()=>loadStatus(false)},'刷新状态')
          ])
        ]),
        h('div',{class:'gya390-state'},[
          ['监控目录',status.value?.watch_registry_total||0],
          ['热监控',status.value?.watch_hot_total||0],
          ['待整理',status.value?.resource_queue_depth||0],
          ['当前 Worker',workerPath.value],
          ['全量剩余',status.value?.full_scan_remaining_dirs||0]
        ].map(([k,v])=>h('div',{class:'gya390-stat'},[h('span',k),h('b',String(v??'-'))]))),
        h('div',{class:'gya390-progress'},[
          h('div',[h('strong',fullActive.value?'全量巡检进行中；Worker 忙时发现器仍继续运行':'持续增量观察模式')]),
          h('div',`监控引擎：${status.value?.monitor_pipeline||'-'} ｜ 安装注册安全：${status.value?.install_registration_safe?'是':'-'}`),
          h('div',`全量 ID：${status.value?.full_scan_id||'-'} ｜ 已扫描目录：${status.value?.full_scan_dirs||0} ｜ 待整理队列：${status.value?.resource_queue_depth||0}`),
          h('div',`最近全量完成：${fmtTime(status.value?.full_scan_last_completed_at)} ｜ 自动全量：${Math.round(Number(status.value?.full_scan_interval||3600)/60)} 分钟`)
        ]),
        message.value?h('div',{class:`gya390-msg ${messageKind.value==='warn'?'warn':messageKind.value==='error'?'error':''}`},message.value):null
      ])
    ]);

    return()=>h('div',[
      control(),
      h(BasePage,{initialConfig:props.initialConfig,api:props.api,onClose:()=>emit('close'),onSwitch:()=>emit('switch')})
    ]);
  }
});
