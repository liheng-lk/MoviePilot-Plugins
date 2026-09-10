import BasePage from './__federation_expose_AssistantPage-v352.js?v=3.7.6';
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
.gya376{width:100%;margin-bottom:10px;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;color:rgb(var(--v-theme-on-surface))}
.gya376-card{background:rgb(var(--v-theme-surface));border:1px solid rgba(var(--v-theme-on-surface),.09);border-radius:14px;padding:14px 16px}
.gya376-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:11px}.gya376-title{font-size:14px;font-weight:760}.gya376-sub{font-size:10.5px;opacity:.58;line-height:1.55;margin-top:3px}
.gya376-actions{display:flex;gap:8px;flex-wrap:wrap}.gya376-btn{height:35px;padding:0 13px;border-radius:8px;border:1px solid rgba(var(--v-theme-on-surface),.13);background:transparent;color:inherit;cursor:pointer;font-size:11px}.gya376-btn.primary{background:rgb(var(--v-theme-primary));border-color:transparent;color:rgb(var(--v-theme-on-primary))}.gya376-btn.warn{border-color:rgba(245,158,11,.48);color:#f59e0b}.gya376-btn:disabled{opacity:.42;cursor:not-allowed}
.gya376-state{margin-top:11px;display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:7px}.gya376-stat{border:1px solid rgba(var(--v-theme-on-surface),.075);border-radius:8px;padding:8px 9px;min-width:0}.gya376-stat span{display:block;font-size:9px;opacity:.48}.gya376-stat b{display:block;font-size:12px;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.gya376-progress{margin-top:9px;padding:9px 10px;border-radius:8px;background:rgba(var(--v-theme-primary),.05);font-size:10px;line-height:1.65;word-break:break-all}.gya376-progress strong{color:rgb(var(--v-theme-primary))}.gya376-msg{margin-top:9px;padding:8px 10px;border-radius:8px;font-size:10.5px;background:rgba(16,185,129,.08);color:#10b981}.gya376-msg.warn{background:rgba(245,158,11,.08);color:#f59e0b}.gya376-msg.error{background:rgba(239,68,68,.08);color:#ef4444}
@media(max-width:900px){.gya376-head{display:block}.gya376-actions{margin-top:10px}.gya376-state{grid-template-columns:repeat(2,minmax(0,1fr))}}
`;

function fmtTime(v) {
  const n = Number(v || 0);
  if (!n) return '-';
  try { return new Date(n * 1000).toLocaleString(); } catch { return '-'; }
}

export default defineComponent({
  name:'GuangYaAssistantV376',
  props:{initialConfig:{type:Object,default:()=>({})},api:{type:Object,default:null}},
  emits:['close','switch'],
  setup(props,{emit}) {
    const status=ref({});
    const busy=ref('');
    const message=ref('');
    const messageKind=ref('ok');
    let timer=null;

    const fullActive=computed(()=>Boolean(status.value?.full_scan_active));
    const fullPaused=computed(()=>Boolean(status.value?.full_scan_paused));
    const scanMode=computed(()=>status.value?.scan_mode_label||status.value?.scan_mode||'-');
    const stageText=computed(()=>{
      const no=Number(status.value?.scan_stage_no||0), total=Number(status.value?.scan_stage_total||6);
      return no?`${no}/${total} ${status.value?.scan_stage||''}`:(status.value?.scan_stage||'-');
    });

    function setMsg(text,kind='ok'){message.value=text||'';messageKind.value=kind;}

    async function loadStatus(silent=true){
      try{
        const r=await getApi(props,'/organize/monitor/status');
        if(!r?.success)throw new Error(r?.message||'读取扫描状态失败');
        status.value=r?.data?.status||{};
      }catch(e){if(!silent)setMsg(e?.message||'读取扫描状态失败','error');}
    }

    async function action(kind,path){
      busy.value=kind;setMsg('');
      try{
        const r=await postApi(props,path,{});
        if(!r?.success)throw new Error(r?.message||'操作失败');
        setMsg(r?.message||'操作已提交',r?.data?.full_scan_paused?'warn':'ok');
        await loadStatus(true);
      }catch(e){setMsg(e?.message||'操作失败','error');}
      finally{busy.value='';}
    }

    onMounted(async()=>{
      await loadStatus(true);
      timer=setInterval(()=>loadStatus(true),3000);
    });
    onUnmounted(()=>{if(timer)clearInterval(timer);});

    const control=()=>h('div',{class:'gya376'},[
      h('style',css),
      h('div',{class:'gya376-card'},[
        h('div',{class:'gya376-head'},[
          h('div',[
            h('div',{class:'gya376-title'},'整理扫描控制 · 双通道'),
            h('div',{class:'gya376-sub'},'增量：pending → 已知资源变化 → discovery 推进一页；全量：从监控根目录完整遍历，遇到正在整理会暂停并自动续页。')
          ]),
          h('div',{class:'gya376-actions'},[
            h('button',{class:'gya376-btn',disabled:Boolean(busy.value)||fullActive.value,onClick:()=>action('incremental','/organize/monitor/incremental-scan')},busy.value==='incremental'?'扫描中…':'增量扫描一次'),
            h('button',{class:'gya376-btn primary',disabled:Boolean(busy.value),onClick:()=>action('full','/organize/monitor/full-scan')},busy.value==='full'?'启动中…':fullActive.value?'继续全量扫描':'开始全量扫描'),
            h('button',{class:'gya376-btn warn',disabled:Boolean(busy.value)||!fullActive.value,onClick:()=>action('stop','/organize/monitor/full-scan/stop')},'停止全量扫描'),
            h('button',{class:'gya376-btn',disabled:Boolean(busy.value),onClick:()=>loadStatus(false)},'刷新进度')
          ])
        ]),
        h('div',{class:'gya376-state'},[
          ['当前模式',scanMode.value],
          ['扫描阶段',stageText.value],
          ['全量页数',status.value?.full_scan_pages||0],
          ['累计目录',status.value?.full_scan_dirs||0],
          ['剩余游标',status.value?.full_scan_remaining_dirs||0]
        ].map(([k,v])=>h('div',{class:'gya376-stat'},[h('span',k),h('b',String(v??'-'))]))),
        h('div',{class:'gya376-progress'},[
          h('div',[h('strong',fullActive.value?(fullPaused.value?'全量已暂停，等待 Worker 空闲后自动继续':'全量扫描进行中'):'当前无全量会话')]),
          h('div',`扫描 ID：${status.value?.scan_id||status.value?.full_scan_id||'-'} ｜ 最近全量完成：${fmtTime(status.value?.full_scan_last_completed_at)}`),
          h('div',`当前说明：${status.value?.scan_message||'等待扫描触发'} ｜ 自动全量兜底：${Math.round(Number(status.value?.full_scan_interval||1800)/60)} 分钟`)
        ]),
        message.value?h('div',{class:`gya376-msg ${messageKind.value==='warn'?'warn':messageKind.value==='error'?'error':''}`},message.value):null
      ])
    ]);

    return()=>h('div',[
      control(),
      h(BasePage,{initialConfig:props.initialConfig,api:props.api,onClose:()=>emit('close'),onSwitch:()=>emit('switch')})
    ]);
  }
});
