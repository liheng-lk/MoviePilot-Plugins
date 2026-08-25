import BasePage from './__federation_expose_AssistantPage-v340.js?v=3.4.0-preview3';
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
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

const css = `
.gyqr{margin-bottom:10px;padding:12px 14px;border-radius:12px;border:1px solid rgba(var(--v-theme-on-surface),.10);background:rgb(var(--v-theme-surface));color:rgb(var(--v-theme-on-surface));font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}.gyqr *{box-sizing:border-box}
.gyqr.warn{border-color:rgba(245,158,11,.38);background:rgba(245,158,11,.055)}.gyqr.error{border-color:rgba(239,68,68,.40);background:rgba(239,68,68,.05)}
.gyqr-head{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap}.gyqr-title{font-size:13px;font-weight:760}.gyqr-sub{font-size:10px;opacity:.62;margin-top:3px;line-height:1.55}.gyqr-stats{display:flex;gap:6px;flex-wrap:wrap;margin-top:9px}.gyqr-chip{font-size:10px;padding:4px 7px;border-radius:999px;background:rgba(var(--v-theme-on-surface),.06)}.gyqr-chip.bad{color:#ef4444;background:rgba(239,68,68,.09)}.gyqr-chip.wait{color:#f59e0b;background:rgba(245,158,11,.10)}.gyqr-chip.run{color:#3b82f6;background:rgba(59,130,246,.10)}
.gyqr-actions{display:flex;gap:7px;flex-wrap:wrap;margin-top:10px}.gyqr-btn{height:34px;padding:0 11px;border-radius:8px;border:1px solid rgba(var(--v-theme-on-surface),.14);background:transparent;color:inherit;font-size:10.5px;cursor:pointer}.gyqr-btn.warn{border-color:rgba(245,158,11,.45);color:#f59e0b}.gyqr-btn.danger{border-color:rgba(239,68,68,.45);color:#ef4444}.gyqr-btn:disabled{opacity:.42;cursor:not-allowed}.gyqr-msg{font-size:10px;line-height:1.55;margin-top:8px;white-space:pre-wrap}.gyqr-msg.ok{color:#10b981}.gyqr-msg.warn{color:#f59e0b}.gyqr-msg.error{color:#ef4444}
`;

export default defineComponent({
  name: 'GuangyaCloudAssistantV341',
  props: {initialConfig:{type:Object,default:()=>({})}, api:{type:Object,default:null}},
  emits: ['close','switch'],
  setup(props,{emit}) {
    const nativeQueue=ref({});
    const loading=ref(false);
    const message=ref('');
    const messageKind=ref('');
    const armWaiting=ref(false);
    const armRunning=ref(false);
    let timer=null;

    const waiting=computed(()=>Number(nativeQueue.value?.guangya_waiting||0));
    const running=computed(()=>Number(nativeQueue.value?.guangya_running||0));
    const guangyaTotal=computed(()=>Number(nativeQueue.value?.guangya_total||0));
    const mpTotal=computed(()=>Number(nativeQueue.value?.total||0));
    const hasBacklog=computed(()=>waiting.value>0||running.value>0);

    function setMsg(text,kind=''){message.value=text||'';messageKind.value=kind;}

    async function refresh() {
      try {
        const r=await getApi(props,'/organize/monitor/status');
        if (r?.success) nativeQueue.value=r?.data?.native_queue||{};
      } catch (_) {}
    }

    async function recover(includeRunning=false) {
      const count=includeRunning?waiting.value+running.value:waiting.value;
      if (!count) return;
      if (includeRunning && !armRunning.value) {
        armRunning.value=true; armWaiting.value=false;
        setMsg(`再次点击确认：将取消当前监控目录内 ${count} 个光鸭等待/运行任务。运行中的文件操作会通过 MoviePilot 官方停止标记中断。`,'error');
        return;
      }
      if (!includeRunning && !armWaiting.value) {
        armWaiting.value=true; armRunning.value=false;
        setMsg(`再次点击确认：将只取消当前监控目录内 ${waiting.value} 个光鸭等待任务，不碰运行中任务和其它 MoviePilot 整理。`,'warn');
        return;
      }

      loading.value=true;
      try {
        const r=await postApi(props,'/organize/monitor/recover-queue',{
          confirm:true,
          monitor_only:true,
          include_running:includeRunning,
        });
        setMsg(r?.message||'队列恢复请求已完成',r?.success?'ok':'error');
        armWaiting.value=false; armRunning.value=false;
        await refresh();
      } catch(e) {
        setMsg(e?.message||'队列恢复失败','error');
      } finally { loading.value=false; }
    }

    onMounted(async()=>{await refresh();timer=setInterval(refresh,5000);});
    onUnmounted(()=>{if(timer)clearInterval(timer);});

    const recoveryPanel=()=>{
      if (!hasBacklog.value && !message.value) return null;
      return h('div',{class:`gyqr ${running.value>0?'error':'warn'}`},[
        h('style',css),
        h('div',{class:'gyqr-head'},[
          h('div',[
            h('div',{class:'gyqr-title'},hasBacklog.value?'检测到 MoviePilot 原生整理队列中的光鸭积压':'光鸭旧队列已释放'),
            h('div',{class:'gyqr-sub'},hasBacklog.value?'这是已经进入 MoviePilot 的旧任务；仅降低插件并发不会让它们自动消失。恢复操作只匹配光鸭存储，并默认只处理当前监控目录。':'等待约 2 分钟让 MoviePilot worker 跳过已取消项，然后插件会按新背压策略逐个提交。')
          ]),
          h('button',{class:'gyqr-btn',disabled:loading.value,onClick:refresh},'刷新')
        ]),
        hasBacklog.value?h('div',{class:'gyqr-stats'},[
          h('span',{class:'gyqr-chip'},`MP 总队列 ${mpTotal.value}`),
          h('span',{class:'gyqr-chip bad'},`光鸭 ${guangyaTotal.value}`),
          h('span',{class:'gyqr-chip wait'},`等待 ${waiting.value}`),
          h('span',{class:'gyqr-chip run'},`运行 ${running.value}`)
        ]):null,
        hasBacklog.value?h('div',{class:'gyqr-actions'},[
          waiting.value>0?h('button',{class:'gyqr-btn warn',disabled:loading.value,onClick:()=>recover(false)},armWaiting.value?`确认清理 ${waiting.value} 个等待任务`:`清理旧光鸭排队 (${waiting.value})`):null,
          running.value>0?h('button',{class:'gyqr-btn danger',disabled:loading.value,onClick:()=>recover(true)},armRunning.value?`确认终止等待/运行 (${waiting.value+running.value})`:`终止卡住的光鸭任务 (${running.value})`):null
        ]):null,
        message.value?h('div',{class:`gyqr-msg ${messageKind.value}`},message.value):null
      ]);
    };

    return()=>h('div',[
      recoveryPanel(),
      h(BasePage,{initialConfig:props.initialConfig,api:props.api,onClose:()=>emit('close'),onSwitch:()=>emit('switch')})
    ]);
  }
});
