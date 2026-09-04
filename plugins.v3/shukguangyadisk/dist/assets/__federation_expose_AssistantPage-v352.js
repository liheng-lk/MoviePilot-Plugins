import AccountPage from './__federation_expose_AssistantPage-dev.js?v=3.0.0';
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
    method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body)
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

const css = `
.gya{width:100%;color:rgb(var(--v-theme-on-surface));font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}.gya *{box-sizing:border-box}
.gya-tabs{display:flex;gap:7px;padding:10px 14px;border:1px solid rgba(var(--v-theme-on-surface),.08);border-radius:12px;margin-bottom:10px;background:rgb(var(--v-theme-surface))}.gya-tab{height:34px;padding:0 14px;border-radius:9px;border:1px solid rgba(var(--v-theme-on-surface),.1);background:transparent;color:inherit;cursor:pointer;font-size:12px}.gya-tab.active{background:rgb(var(--v-theme-primary));border-color:transparent;color:rgb(var(--v-theme-on-primary));font-weight:700}
.gya-shell{background:rgb(var(--v-theme-surface));border:1px solid rgba(var(--v-theme-on-surface),.08);border-radius:14px;overflow:hidden}.gya-head{padding:16px 18px;border-bottom:1px solid rgba(var(--v-theme-on-surface),.07);display:flex;justify-content:space-between;align-items:center;gap:12px}.gya-title{font-size:17px;font-weight:760}.gya-sub{font-size:10.5px;opacity:.58;margin-top:3px;line-height:1.6}
.gya-body{padding:14px 18px 18px;display:grid;gap:12px}.gya-card{border:1px solid rgba(var(--v-theme-on-surface),.075);border-radius:11px;padding:13px;background:rgba(var(--v-theme-on-surface),.008)}.gya-card-title{font-size:13px;font-weight:740;margin-bottom:3px}.gya-card-sub{font-size:10px;opacity:.55;margin-bottom:10px;line-height:1.55}.gya-grid{display:grid;grid-template-columns:1.6fr .8fr .8fr;gap:10px}.gya-field label{display:block;font-size:10px;opacity:.55;margin-bottom:4px}.gya-input{width:100%;height:38px;border:1px solid rgba(var(--v-theme-on-surface),.13);border-radius:8px;padding:0 10px;background:rgb(var(--v-theme-surface));color:inherit;font-size:11.5px}.gya-path{display:grid;grid-template-columns:1fr auto;gap:7px}.gya-btn{height:36px;padding:0 13px;border-radius:8px;border:1px solid rgba(var(--v-theme-on-surface),.13);background:transparent;color:inherit;cursor:pointer;font-size:11px}.gya-btn.primary{background:rgb(var(--v-theme-primary));color:rgb(var(--v-theme-on-primary));border-color:transparent}.gya-btn.warn{border-color:rgba(245,158,11,.45);color:#f59e0b}.gya-btn:disabled{opacity:.4;cursor:not-allowed}.gya-actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.gya-check{display:flex;gap:7px;align-items:center;font-size:10.5px;opacity:.78}.gya-switch{display:flex;align-items:center;gap:8px;font-size:11.5px;font-weight:650}
.gya-note{padding:10px;border-radius:8px;background:rgba(var(--v-theme-primary),.055);font-size:10.5px;line-height:1.65}.gya-note b{color:rgb(var(--v-theme-primary))}.gya-msg{padding:9px 10px;border-radius:8px;font-size:10.5px;background:rgba(16,185,129,.08);color:#10b981;white-space:pre-wrap}.gya-msg.error{background:rgba(239,68,68,.08);color:#ef4444}.gya-msg.warn{background:rgba(245,158,11,.08);color:#f59e0b}
.gya-stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px}.gya-stat{padding:9px;border:1px solid rgba(var(--v-theme-on-surface),.07);border-radius:8px}.gya-stat span{display:block;font-size:9px;opacity:.48}.gya-stat b{font-size:15px}.gya-statusline{display:flex;gap:10px;align-items:center;flex-wrap:wrap;font-size:10px;opacity:.72;margin-top:8px}.gya-statuspath{margin-top:8px;padding:8px 9px;border-radius:8px;background:rgba(var(--v-theme-on-surface),.035);font-size:10px;word-break:break-all;line-height:1.55}.gya-dot{width:8px;height:8px;border-radius:50%;background:#9ca3af}.gya-dot.on{background:#10b981}.gya-dot.warn{background:#f59e0b}.gya-dot.err{background:#ef4444}
.gya-browser{border:1px solid rgba(var(--v-theme-on-surface),.1);border-radius:10px;padding:10px;margin-top:9px}.gya-browser-head{display:flex;gap:7px;align-items:center;margin-bottom:8px}.gya-browser-path{flex:1;font-size:10px;word-break:break-all;opacity:.65}.gya-folders{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;max-height:220px;overflow:auto}.gya-folder{padding:8px;border:1px solid rgba(var(--v-theme-on-surface),.08);border-radius:8px;cursor:pointer;font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;background:transparent;color:inherit;text-align:left}.gya-folder:hover{border-color:rgb(var(--v-theme-primary))}
.gya-history{display:grid;gap:6px;max-height:360px;overflow:auto}.gya-history-row{display:grid;grid-template-columns:145px minmax(180px,1fr) 125px;gap:8px;align-items:center;padding:8px;border:1px solid rgba(var(--v-theme-on-surface),.07);border-radius:8px;font-size:10px}.gya-history-row small{display:block;opacity:.5;word-break:break-all;margin-top:2px}.gya-result{padding:3px 7px;border-radius:999px;text-align:center;background:rgba(var(--v-theme-primary),.08)}.gya-result.completed,.gya-result.history_completed,.gya-result.folder_completed{color:#10b981;background:rgba(16,185,129,.1)}.gya-result.queued,.gya-result.resource_queued,.gya-result.folder_queued{color:#3b82f6;background:rgba(59,130,246,.1)}.gya-result.deferred,.gya-result.blocked,.gya-result.folder_partial,.gya-result.folder_safety_blocked{color:#f59e0b;background:rgba(245,158,11,.1)}.gya-result.failed{color:#ef4444;background:rgba(239,68,68,.1)}.gya-result.ignored{opacity:.6}
@media(max-width:900px){.gya-grid{grid-template-columns:1fr}.gya-stats{grid-template-columns:repeat(2,1fr)}.gya-history-row{grid-template-columns:1fr}.gya-folders{grid-template-columns:1fr 1fr}}
`;

const RESULT_TEXT = {
  queued:'等待执行', resource_queued:'等待执行', folder_queued:'文件夹任务', completed:'已整理',
  folder_completed:'文件夹完成', folder_partial:'待复核', folder_safety_blocked:'安全阻断',
  failed:'整理失败', history_completed:'MP历史已完成', deferred:'等待重试', blocked:'MP门控',
  ignored:'已忽略', submitted:'等待执行', gated:'MP门控'
};

export default defineComponent({
  name:'GuangyaCloudAssistant',
  props:{initialConfig:{type:Object,default:()=>({})},api:{type:Object,default:null}},
  emits:['close','switch'],
  setup(props,{emit}) {
    const tab=ref('account');
    const enabled=ref(false),monitorPath=ref('/'),interval=ref(60),stability=ref(30),batchSize=ref(100),recursive=ref(true);
    const mp=ref({}),status=ref({}),history=ref([]),busy=ref(false),message=ref(''),messageKind=ref('ok');
    const browserOpen=ref(false),browserPath=ref('/'),browserFolders=ref([]),browserBusy=ref(false);
    let timer=null;
    const running=computed(()=>Boolean(enabled.value));
    const blocked=computed(()=>Number(status.value?.state_blocked??status.value?.blocked??0));
    const retryTotal=computed(()=>Number(status.value?.state_retry_total??status.value?.state_retry_wait??status.value?.retry_wait??0));
    const retryWait=computed(()=>Number(status.value?.state_retry_wait??status.value?.retry_wait??0));
    const retryDue=computed(()=>Number(status.value?.state_retry_due??0));
    const retryMaxAttempts=computed(()=>Number(status.value?.state_retry_max_attempts??0));
    const runtimePhase=computed(()=>status.value?.runtime_phase||(!enabled.value?'disabled':'idle'));
    const gracefulStopping=computed(()=>['finishing_current','stopping'].includes(status.value?.graceful_stop_state));
    const gracefulStopped=computed(()=>status.value?.graceful_stop_state==='stopped');
    const statusDot=computed(()=>{
      if(Number(status.value?.failed_total||0)>0&&runtimePhase.value==='idle')return 'err';
      if(runtimePhase.value==='handoff'||runtimePhase.value==='draining'||blocked.value>0)return 'warn';
      if(runtimePhase.value==='stopped')return '';
      if(['transferring','queued','scanning','idle'].includes(runtimePhase.value)&&enabled.value)return 'on';
      return '';
    });
    function setMsg(text,kind='ok'){message.value=text||'';messageKind.value=kind;}
    function applyConfig(c={}){enabled.value=Boolean(c.enabled);monitorPath.value=c.path||'/';interval.value=Number(c.interval||60);stability.value=Number(c.stability??30);batchSize.value=Number(c.batch_size||100);recursive.value=c.recursive!==false;}
    function isLegacyQueueError(text=''){return text.includes('MoviePilot 全局整理队列仍有旧光鸭任务')||text.includes('请先重启 MoviePilot')||text.includes('旧版光鸭任务仍在 MoviePilot 全局后台队列');}
    async function loadConfig(){try{const r=await getApi(props,'/organize/monitor/config');if(!r?.success)throw new Error(r?.message||'读取失败');applyConfig(r?.data?.config||{});mp.value=r?.data?.mp||{};}catch(e){setMsg(e?.message||'读取自动整理设置失败','error');}}
    async function loadStatus(silent=true){try{const r=await getApi(props,'/organize/monitor/status');if(!r?.success)throw new Error(r?.message||'读取失败');status.value=r?.data?.status||{};history.value=r?.data?.history||[];mp.value=r?.data?.mp||mp.value;if(!status.value?.queue_guard_active&&messageKind.value==='error'&&isLegacyQueueError(message.value))setMsg('');if(!silent)setMsg(status.value?.graceful_stop_message||status.value?.queue_guard_message||r?.message||'状态已刷新',runtimePhase.value==='handoff'||runtimePhase.value==='draining'||status.value?.queue_guard_active?'warn':'ok');}catch(e){if(!silent)setMsg(e?.message||'读取运行状态失败','error');}}
    async function save(){busy.value=true;setMsg('');try{const r=await postApi(props,'/organize/monitor/config',{enabled:enabled.value,path:monitorPath.value,interval:Number(interval.value||60),stability:Number(stability.value||0),batch_size:Number(batchSize.value||100),recursive:recursive.value});if(!r?.success)throw new Error(r?.message||'保存失败');applyConfig(r?.data?.config||{});mp.value=r?.data?.mp||mp.value;setMsg(r?.message||'设置已保存');await loadStatus(true);}catch(e){setMsg(e?.message||'保存自动整理设置失败','error');}finally{busy.value=false;}}
    async function scan(){busy.value=true;setMsg('');try{const r=await postApi(props,'/organize/monitor/scan',{});setMsg(r?.message||'扫描完成',r?.success?'ok':'error');await loadStatus(true);}catch(e){setMsg(e?.message||'立即扫描失败','error');}finally{busy.value=false;}}
    async function gracefulStop(){busy.value=true;setMsg('');try{const r=await postApi(props,'/organize/monitor/graceful-stop',{});if(!r?.success)throw new Error(r?.message||'安全停止失败');enabled.value=false;setMsg(r?.message||'已请求安全停止',r?.data?.state==='finishing_current'?'warn':'ok');await loadStatus(true);}catch(e){setMsg(e?.message||'安全停止失败','error');}finally{busy.value=false;}}
    async function selfcheck(){busy.value=true;try{const r=await getApi(props,'/organize/monitor/selfcheck');if(!r?.success)throw new Error(r?.message||'自检失败');const d=r?.data||{};const c=d.checks||{};const rtotal=Number(c.state_retry_total??c.state_retry_wait??0),rwait=Number(c.state_retry_wait??0),rdue=Number(c.state_retry_due??0),rmax=Number(c.state_retry_max_attempts??0);const lines=[`自动整理自检：${d.healthy?'正常':'存在异常'}`,`运行时桥：${c.runtime_bridge?'正常':'异常'}｜存储：${c.storage_ready?'正常':'未就绪'}｜监控目录：${c.monitor_path_exists?'正常':'异常'}`,`状态缓存：完成 ${c.state_completed||0}｜处理中 ${c.state_inflight||0}｜重试总数 ${rtotal}｜退避中 ${rwait}｜已到期 ${rdue}｜最大尝试 ${rmax}｜门控 ${c.state_blocked||0}`];setMsg(lines.join('\n'),d.healthy?'ok':'warn');}catch(e){setMsg(e?.message||'自检失败','error');}finally{busy.value=false;}}
    async function unblock(){busy.value=true;try{const r=await postApi(props,'/organize/monitor/unblock',{});if(!r?.success)throw new Error(r?.message||'解除失败');setMsg(r?.message||'已解除门控等待');await loadStatus(true);}catch(e){setMsg(e?.message||'解除门控失败','error');}finally{busy.value=false;}}
    async function browse(path=browserPath.value){browserBusy.value=true;try{const r=await postApi(props,'/organize/folders',{path:path||'/'});if(!r?.success)throw new Error(r?.message||'目录读取失败');browserOpen.value=true;browserPath.value=r.data.path||'/';browserFolders.value=r.data.folders||[];}catch(e){setMsg(e?.message||'目录读取失败','error');}finally{browserBusy.value=false;}}
    async function openBrowser(){await browse(monitorPath.value||'/');}
    function chooseCurrent(){monitorPath.value=browserPath.value;browserOpen.value=false;}
    function parentPath(){return browserPath.value==='/'?'/':(browserPath.value.split('/').slice(0,-1).join('/')||'/');}
    onMounted(async()=>{await Promise.all([loadConfig(),loadStatus(true)]);timer=setInterval(()=>{if(tab.value==='organize')loadStatus(true);},5000);});
    onUnmounted(()=>{if(timer)clearInterval(timer);});

    const browser=()=>!browserOpen.value?null:h('div',{class:'gya-browser'},[
      h('div',{class:'gya-browser-head'},[
        h('button',{class:'gya-btn',disabled:browserPath.value==='/'||browserBusy.value,onClick:()=>browse(parentPath())},'上一级'),
        h('div',{class:'gya-browser-path'},browserPath.value),
        h('button',{class:'gya-btn primary',disabled:browserPath.value==='/',onClick:chooseCurrent},'设为监控目录'),
        h('button',{class:'gya-btn',onClick:()=>browserOpen.value=false},'关闭')
      ]),
      h('div',{class:'gya-folders'},browserFolders.value.length?browserFolders.value.map(f=>h('button',{class:'gya-folder',title:f.path,onClick:()=>browse(f.path)},`📁 ${f.name}`)):h('div',{class:'gya-card-sub'},browserBusy.value?'读取中…':'当前目录没有子文件夹'))
    ]);

    const organizer=()=>h('div',{class:'gya-shell'},[
      h('div',{class:'gya-head'},[
        h('div',[h('div',{class:'gya-title'},'自动整理监控'),h('div',{class:'gya-sub'},'资源发现 → MoviePilot 识别/预览 → 安全校验 → 真实整理 → MP历史落库。单 Worker 串行执行；等待资源优先复查，若当前没有活动执行，同一监控周期继续发现新资源。')])
      ]),
      h('div',{class:'gya-body'},[
        h('div',{class:'gya-card'},[
          h('div',{class:'gya-card-title'},'1. 监控目录'),
          h('div',{class:'gya-card-sub'},'只负责发现该目录新增/变化资源。作品目录名优先提供作品上下文，错误文件名不会直接否定正确文件夹。'),
          h('div',{class:'gya-path'},[
            h('input',{class:'gya-input',value:monitorPath.value,onInput:e=>monitorPath.value=e.target.value,placeholder:'/例如：/光鸭媒体库'}),
            h('button',{class:'gya-btn',disabled:busy.value,onClick:openBrowser},'浏览')
          ]),browser(),
          h('div',{class:'gya-actions',style:{marginTop:'10px'}},[
            h('label',{class:'gya-switch'},[h('input',{type:'checkbox',checked:enabled.value,onChange:e=>enabled.value=e.target.checked}),'启用自动监控整理']),
            h('label',{class:'gya-check'},[h('input',{type:'checkbox',checked:recursive.value,onChange:e=>recursive.value=e.target.checked}),'递归监控子目录'])
          ])
        ]),
        h('div',{class:'gya-card'},[
          h('div',{class:'gya-card-title'},'2. 监控参数'),
          h('div',{class:'gya-card-sub'},'单资源 Worker 保持串行执行；stabilizing/history/retry 等等待态会优先回访，但没有活动任务时会在同一轮继续 known/discovery，不再阻塞新增资源发现。'),
          h('div',{class:'gya-grid'},[
            h('div',{class:'gya-field'},[h('label','扫描间隔（秒）'),h('input',{class:'gya-input',type:'number',min:'30',max:'3600',value:interval.value,onInput:e=>interval.value=e.target.value})]),
            h('div',{class:'gya-field'},[h('label','文件稳定等待（秒）'),h('input',{class:'gya-input',type:'number',min:'0',max:'3600',value:stability.value,onInput:e=>stability.value=e.target.value})]),
            h('div',{class:'gya-field'},[h('label','目录成员限流'),h('input',{class:'gya-input',type:'number',min:'1',max:'500',value:batchSize.value,onInput:e=>batchSize.value=e.target.value})])
          ])
        ]),
        h('div',{class:'gya-note'},[
          h('b','整理规则：MoviePilot 内置'),
          h('span',`　MP 目录配置 ${mp.value.directory_count||0} 条，光鸭相关 ${mp.value.guangya_directory_count||0} 条。`),
          h('br'),
          h('span','插件只负责资源边界、上下文、安全校验与验收；目标目录、分类、重命名、覆盖、刮削和媒体整理历史仍由 MoviePilot 产生。')
        ]),
        message.value?h('div',{class:`gya-msg ${messageKind.value==='error'?'error':messageKind.value==='warn'?'warn':''}`},message.value):null,
        h('div',{class:'gya-actions'},[
          h('button',{class:'gya-btn primary',disabled:busy.value,onClick:save},busy.value?'处理中…':'保存设置'),
          h('button',{class:'gya-btn',disabled:busy.value||monitorPath.value==='/'||gracefulStopping.value||gracefulStopped.value,onClick:scan},'立即扫描'),
          h('button',{class:'gya-btn warn',disabled:busy.value||gracefulStopping.value||gracefulStopped.value,onClick:gracefulStop},gracefulStopping.value?'当前完成后停止中…':gracefulStopped.value?'已安全停止':'安全停止并清理待执行'),
          h('button',{class:'gya-btn',disabled:busy.value,onClick:selfcheck},'运行自检'),
          h('button',{class:'gya-btn',disabled:busy.value,onClick:()=>loadStatus(false)},'刷新状态'),
          blocked.value>0?h('button',{class:'gya-btn warn',disabled:busy.value,onClick:unblock},`重新检查 MP 门控 (${blocked.value})`):null
        ]),
        gracefulStopping.value||gracefulStopped.value?h('div',{class:'gya-msg warn'},status.value.graceful_stop_message||'安全停止不会中断当前 move/rename；当前资源完整收尾后再停止。重新启用请勾选自动监控并保存设置。'):null,
        h('div',{class:'gya-card'},[
          h('div',{class:'gya-card-title'},'运行状态'),
          h('div',{class:'gya-stats'},[
            ['当前任务',status.value.active_resource_tasks],['任务成员',status.value.current_task_members],['本轮已扫描',status.value.scan_files_seen],['当前待处理',status.value.changed],
            ['累计完成',status.value.completed_total],['MP历史确认',status.value.mp_history_confirmed_total],['重试总数',retryTotal.value],['退避中',retryWait.value],
            ['已到期',retryDue.value],['最大尝试',retryMaxAttempts.value],['状态处理中',status.value.state_inflight??status.value.inflight],['安全阻断',status.value.state_blocked??status.value.blocked]
          ].map(([k,v])=>h('div',{class:'gya-stat'},[h('span',k),h('b',String(v||0))]))),
          h('div',{class:'gya-statusline'},[
            h('span',{class:`gya-dot ${statusDot.value}`}),
            h('b',status.value.runtime_label||(running.value?'自动监控已启用':'自动监控未启用')),
            h('span',`上次扫描：${status.value.last_scan||'尚未扫描'}`),
            status.value.duration_ms!=null?h('span',`扫描耗时：${status.value.duration_ms} ms`):null,
            Number(status.value.failed_total||0)>0?h('span',`累计失败：${status.value.failed_total}`):null,
            retryDue.value>0?h('span',`已到期待重试：${retryDue.value}`):null,
            status.value.last_transfer_history_id?h('span',`最近MP历史：#${status.value.last_transfer_history_id}`):null
          ]),
          status.value.current_task_path?h('div',{class:'gya-statuspath'},[
            h('b',runtimePhase.value==='handoff'?'旧版本遗留任务正在安全收尾：':runtimePhase.value==='draining'?'安全停止正在收尾：':'当前资源：'),
            h('span',status.value.current_task_path),
            runtimePhase.value==='handoff'?h('div',{style:{marginTop:'4px',opacity:.68}},'新版本不会并行启动第二个 Worker；该遗留任务结束后自动切换到新的单任务规则。'):null,
            runtimePhase.value==='draining'?h('div',{style:{marginTop:'4px',opacity:.68}},'不会强制中断当前操作；当前资源完整收尾后 Worker 自动停止，未开始任务保持待处理。'):null
          ]):null,
          status.value.scan_is_partial?h('div',{class:'gya-card-sub',style:{marginTop:'8px',marginBottom:'0'}},'单任务流水会在发现当前资源后主动停止继续扫描，因此“本轮已扫描”是当前发现进度，不代表整个媒体库文件总数。'):null,
          !status.value.last_transfer_history_id&&['scanning','queued','transferring','handoff','draining'].includes(runtimePhase.value)?h('div',{class:'gya-card-sub',style:{marginTop:'6px',marginBottom:'0'}},'当前尚未出现 MoviePilot 整理历史编号，说明该任务还没有完成真实整理结算；仅看到识别/目标路径日志不等于已经整理完成。'):null
        ]),
        h('div',{class:'gya-card'},[
          h('div',{class:'gya-card-title'},'最近自动整理流水'),
          h('div',{class:'gya-card-sub'},'“等待执行/文件夹任务”只是调度状态；只有“已整理”并出现 MoviePilot 最终回执后才算真实完成。'),
          h('div',{class:'gya-history'},history.value.length?history.value.map(row=>h('div',{class:'gya-history-row'},[
            h('div',[h('b',row.time||'-')]),
            h('div',[h('b',row.name||'-'),h('small',row.path||''),row.message?h('small',row.message):null,row.transfer_history_id?h('small',`MoviePilot 历史 #${row.transfer_history_id}`):null]),
            h('div',{class:`gya-result ${row.result||''}`},RESULT_TEXT[row.result]||row.result||'-')
          ])):h('div',{class:'gya-card-sub'},'暂无记录'))
        ])
      ])
    ]);

    return()=>h('div',{class:'gya'},[
      h('style',css),
      h('div',{class:'gya-tabs'},[
        h('button',{class:`gya-tab ${tab.value==='account'?'active':''}`,onClick:()=>tab.value='account'},'账号与存储'),
        h('button',{class:`gya-tab ${tab.value==='organize'?'active':''}`,onClick:()=>{tab.value='organize';loadStatus(true);}},'自动整理')
      ]),
      tab.value==='account'?h(AccountPage,{initialConfig:props.initialConfig,api:props.api,onClose:()=>emit('close'),onSwitch:()=>emit('switch')}):organizer()
    ]);
  }
});
