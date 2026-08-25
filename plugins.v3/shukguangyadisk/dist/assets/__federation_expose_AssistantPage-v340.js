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
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

const css = `
.gya{width:100%;color:rgb(var(--v-theme-on-surface));font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}.gya *{box-sizing:border-box}
.gya-tabs{display:flex;gap:7px;padding:10px 14px;border:1px solid rgba(var(--v-theme-on-surface),.08);border-radius:12px;margin-bottom:10px;background:rgb(var(--v-theme-surface))}.gya-tab{height:34px;padding:0 14px;border-radius:9px;border:1px solid rgba(var(--v-theme-on-surface),.1);background:transparent;color:inherit;cursor:pointer;font-size:12px}.gya-tab.active{background:rgb(var(--v-theme-primary));border-color:transparent;color:rgb(var(--v-theme-on-primary));font-weight:700}
.gya-shell{background:rgb(var(--v-theme-surface));border:1px solid rgba(var(--v-theme-on-surface),.08);border-radius:14px;overflow:hidden}.gya-head{padding:16px 18px;border-bottom:1px solid rgba(var(--v-theme-on-surface),.07);display:flex;justify-content:space-between;align-items:center;gap:12px}.gya-title{font-size:17px;font-weight:760}.gya-sub{font-size:10.5px;opacity:.6;margin-top:3px;line-height:1.6}.gya-badge{font-size:10px;padding:4px 8px;border-radius:999px;background:rgba(var(--v-theme-primary),.1);color:rgb(var(--v-theme-primary));white-space:nowrap}
.gya-body{padding:14px 18px 18px;display:grid;gap:12px}.gya-card{border:1px solid rgba(var(--v-theme-on-surface),.075);border-radius:11px;padding:13px;background:rgba(var(--v-theme-on-surface),.008)}.gya-card-title{font-size:13px;font-weight:740;margin-bottom:3px}.gya-card-sub{font-size:10px;opacity:.56;margin-bottom:10px;line-height:1.55}.gya-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.gya-field label{display:block;font-size:10px;opacity:.57;margin-bottom:4px}.gya-input{width:100%;height:38px;border:1px solid rgba(var(--v-theme-on-surface),.13);border-radius:8px;padding:0 10px;background:rgb(var(--v-theme-surface));color:inherit;font-size:11.5px}.gya-path{display:grid;grid-template-columns:1fr auto;gap:7px}.gya-btn{height:36px;padding:0 13px;border-radius:8px;border:1px solid rgba(var(--v-theme-on-surface),.13);background:transparent;color:inherit;cursor:pointer;font-size:11px}.gya-btn.primary{background:rgb(var(--v-theme-primary));color:rgb(var(--v-theme-on-primary));border-color:transparent}.gya-btn.warn{border-color:rgba(245,158,11,.45);color:#f59e0b}.gya-btn:disabled{opacity:.4;cursor:not-allowed}.gya-actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.gya-check,.gya-switch{display:flex;gap:7px;align-items:center;font-size:10.5px}.gya-switch{font-size:11.5px;font-weight:650}
.gya-note{padding:10px;border-radius:8px;background:rgba(var(--v-theme-primary),.055);font-size:10.5px;line-height:1.65}.gya-note b{color:rgb(var(--v-theme-primary))}.gya-note.warn{background:rgba(245,158,11,.09)}.gya-note.error{background:rgba(239,68,68,.08)}.gya-msg{padding:9px 10px;border-radius:8px;font-size:10.5px;background:rgba(16,185,129,.08);color:#10b981;white-space:pre-wrap}.gya-msg.error{background:rgba(239,68,68,.08);color:#ef4444}.gya-msg.warn{background:rgba(245,158,11,.08);color:#f59e0b}
.gya-stats{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:7px}.gya-stat{padding:9px;border:1px solid rgba(var(--v-theme-on-surface),.07);border-radius:8px}.gya-stat span{display:block;font-size:9px;opacity:.48}.gya-stat b{font-size:15px}.gya-statusline{display:flex;gap:10px;align-items:center;flex-wrap:wrap;font-size:10px;opacity:.72;margin-top:8px}.gya-dot{width:8px;height:8px;border-radius:50%;background:#9ca3af}.gya-dot.on{background:#10b981}.gya-dot.warn{background:#f59e0b}.gya-dot.err{background:#ef4444}
.gya-browser{border:1px solid rgba(var(--v-theme-on-surface),.1);border-radius:10px;padding:10px;margin-top:9px}.gya-browser-head{display:flex;gap:7px;align-items:center;margin-bottom:8px}.gya-browser-path{flex:1;font-size:10px;word-break:break-all;opacity:.65}.gya-folders{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;max-height:220px;overflow:auto}.gya-folder{padding:8px;border:1px solid rgba(var(--v-theme-on-surface),.08);border-radius:8px;cursor:pointer;font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;background:transparent;color:inherit;text-align:left}.gya-folder:hover{border-color:rgb(var(--v-theme-primary))}
.gya-groups{display:grid;gap:8px;max-height:560px;overflow:auto}.gya-group{border:1px solid rgba(var(--v-theme-on-surface),.08);border-radius:10px;overflow:hidden}.gya-group-head{width:100%;display:grid;grid-template-columns:auto minmax(180px,1fr) auto;gap:10px;align-items:center;padding:10px 11px;border:0;background:rgba(var(--v-theme-on-surface),.012);color:inherit;text-align:left;cursor:pointer}.gya-group-head:hover{background:rgba(var(--v-theme-primary),.045)}.gya-group-arrow{font-size:10px;opacity:.6}.gya-group-main b{display:block;font-size:11.5px}.gya-group-main small{display:block;font-size:9.5px;opacity:.48;word-break:break-all;margin-top:2px}.gya-group-metrics{display:flex;gap:5px;justify-content:flex-end;flex-wrap:wrap}.gya-chip{font-size:9px;padding:3px 6px;border-radius:999px;background:rgba(var(--v-theme-on-surface),.055);white-space:nowrap}.gya-chip.ok{color:#10b981;background:rgba(16,185,129,.09)}.gya-chip.run{color:#3b82f6;background:rgba(59,130,246,.09)}.gya-chip.warn{color:#f59e0b;background:rgba(245,158,11,.09)}.gya-group-body{padding:9px;border-top:1px solid rgba(var(--v-theme-on-surface),.06);display:grid;gap:7px}.gya-group-summary{padding:8px;border-radius:7px;background:rgba(var(--v-theme-primary),.045);font-size:9.5px;line-height:1.5;opacity:.82}.gya-history-row{display:grid;grid-template-columns:140px minmax(180px,1fr) 100px;gap:8px;align-items:center;padding:7px;border:1px solid rgba(var(--v-theme-on-surface),.065);border-radius:7px;font-size:9.5px}.gya-history-row small{display:block;opacity:.5;word-break:break-all;margin-top:2px}.gya-result{padding:3px 6px;border-radius:999px;text-align:center;background:rgba(var(--v-theme-primary),.08)}.gya-result.completed,.gya-result.history_completed{color:#10b981}.gya-result.queued{color:#3b82f6}.gya-result.failed,.gya-result.deferred,.gya-result.blocked{color:#f59e0b}
@media(max-width:900px){.gya-grid{grid-template-columns:1fr}.gya-stats{grid-template-columns:repeat(2,1fr)}.gya-folders{grid-template-columns:1fr 1fr}.gya-group-head{grid-template-columns:auto 1fr}.gya-group-metrics{grid-column:2;justify-content:flex-start}.gya-history-row{grid-template-columns:1fr}}
`;

const RESULT_TEXT = {
  queued:'等待 MP', completed:'已整理', failed:'整理失败', history_completed:'历史已完成',
  deferred:'等待重试', blocked:'MP 门控', ignored:'已忽略', submitted:'等待 MP', gated:'MP 门控',
  folder_batch:'目录批次'
};

function secondsText(value) {
  const n = Number(value || 0);
  if (!n) return '0 秒';
  if (n < 60) return `${Math.round(n)} 秒`;
  if (n < 3600) return `${Math.floor(n/60)} 分 ${Math.round(n%60)} 秒`;
  return `${Math.floor(n/3600)} 小时 ${Math.floor((n%3600)/60)} 分`;
}

export default defineComponent({
  name: 'GuangyaCloudAssistantV340',
  props: {initialConfig:{type:Object,default:()=>({})}, api:{type:Object,default:null}},
  emits: ['close','switch'],
  setup(props,{emit}) {
    const tab=ref('account');
    const enabled=ref(false), monitorPath=ref('/'), interval=ref(60), stability=ref(30), batchSize=ref(100), recursive=ref(true);
    const maxInflight=ref(1), stallTimeout=ref(900);
    const mp=ref({}), status=ref({}), history=ref([]), folderHistory=ref([]), busy=ref(false), message=ref(''), messageKind=ref('ok');
    const browserOpen=ref(false), browserPath=ref('/'), browserFolders=ref([]), browserBusy=ref(false);
    const expandedGroups=ref(new Set());
    let timer=null;

    const running=computed(()=>Boolean(enabled.value));
    const blocked=computed(()=>Number(status.value?.state_blocked ?? status.value?.blocked ?? 0));
    const hostThreads=computed(()=>Number(status.value?.dispatch_host_transfer_threads||0));
    const effectiveLimit=computed(()=>Number(status.value?.queue_limit||maxInflight.value||1));
    const inflight=computed(()=>Number(status.value?.dispatch_inflight ?? status.value?.state_inflight ?? 0));
    const queueSlots=computed(()=>Number(status.value?.queue_slots||0));
    const stalled=computed(()=>Boolean(status.value?.dispatch_stalled));
    const strictIsolation=computed(()=>status.value?.dispatch_strict_isolation === true);
    const legacyBacklog=computed(()=>Math.max(inflight.value-effectiveLimit.value,0));
    const statusDot=computed(()=>stalled.value?'err':legacyBacklog.value>0||blocked.value>0?'warn':running.value?'on':'');

    function setMsg(text,kind='ok'){message.value=text||'';messageKind.value=kind;}
    function applyConfig(c={}){
      enabled.value=Boolean(c.enabled); monitorPath.value=c.path||'/'; interval.value=Number(c.interval||60);
      stability.value=Number(c.stability??30); batchSize.value=Number(c.batch_size||100); recursive.value=c.recursive!==false;
      maxInflight.value=Number(c.max_inflight||1); stallTimeout.value=Number(c.stall_timeout||900);
    }
    function groupKey(group){return group?.group_path||group?.group_name||'unknown';}
    function toggleGroup(group){const key=groupKey(group),next=new Set(expandedGroups.value);next.has(key)?next.delete(key):next.add(key);expandedGroups.value=next;}
    function groupMetrics(group){
      const c=group?.counts||{}, current=group?.current||{};
      return [
        {text:`文件 ${group?.total_files||0}`,cls:''},
        {text:`已完成 ${c.completed||0}`,cls:'ok'},
        {text:`整理中 ${current.inflight??c.inflight??0}`,cls:'run'},
        {text:`重试 ${current.retry??c.retry??0}`,cls:'warn'},
        {text:`门控 ${current.blocked??c.blocked??0}`,cls:'warn'}
      ];
    }

    async function loadConfig(){
      try{const r=await getApi(props,'/organize/monitor/config');if(!r?.success)throw new Error(r?.message||'读取失败');applyConfig(r?.data?.config||{});mp.value=r?.data?.mp||{};}
      catch(e){setMsg(e?.message||'读取自动整理设置失败','error');}
    }
    async function loadStatus(silent=true){
      try{const r=await getApi(props,'/organize/monitor/status');if(!r?.success)throw new Error(r?.message||'读取失败');status.value=r?.data?.status||{};history.value=r?.data?.history||[];folderHistory.value=r?.data?.folder_history||[];mp.value=r?.data?.mp||mp.value;if(!silent&&r?.message)setMsg(r.message);}
      catch(e){if(!silent)setMsg(e?.message||'读取运行状态失败','error');}
    }
    async function save(){
      busy.value=true;setMsg('');
      try{
        const r=await postApi(props,'/organize/monitor/config',{
          enabled:enabled.value,path:monitorPath.value,interval:Number(interval.value||60),stability:Number(stability.value||0),
          batch_size:Number(batchSize.value||100),max_inflight:Number(maxInflight.value||1),stall_timeout:Number(stallTimeout.value||900),recursive:recursive.value
        });
        if(!r?.success)throw new Error(r?.message||'保存失败');applyConfig(r?.data?.config||{});mp.value=r?.data?.mp||mp.value;setMsg(r?.message||'设置已保存');await loadStatus(true);
      }catch(e){setMsg(e?.message||'保存自动整理设置失败','error');}finally{busy.value=false;}
    }
    async function scan(){busy.value=true;setMsg('');try{const r=await postApi(props,'/organize/monitor/scan',{});setMsg(r?.message||'扫描完成',r?.success?'ok':'error');await loadStatus(true);}catch(e){setMsg(e?.message||'立即扫描失败','error');}finally{busy.value=false;}}
    async function selfcheck(){
      busy.value=true;
      try{
        const r=await getApi(props,'/organize/monitor/selfcheck');if(!r?.success)throw new Error(r?.message||'自检失败');
        const d=r?.data||{},c=d.checks||{};
        const lines=[
          `自动整理自检：${d.healthy?'正常':d.degraded?'队列降级':'存在异常'}`,
          `运行时桥：${c.runtime_bridge?'正常':'异常'}｜存储：${c.storage_ready?'正常':'未就绪'}｜监控目录：${c.monitor_path_exists?'正常':'异常'}`,
          `MP整理线程：${c.dispatch_host_transfer_threads??'-'}｜光鸭实际上限：${c.dispatch_max_inflight??'-'}｜当前占用：${c.dispatch_inflight??0}｜可用槽位：${c.dispatch_slots??0}`,
          `目录等待：${c.pending_group_count??0}｜最老任务：${secondsText(c.dispatch_oldest_age_seconds||0)}｜熔断：${c.dispatch_stalled?'是':'否'}`,
          `隔离能力：${c.dispatch_strict_isolation?'已保留非光鸭 worker':'MP 仅 1 个 worker，当前只能防止队列灌满，不能真正并行隔离'}`
        ];
        setMsg(lines.join('\n'),d.healthy&&!d.isolation_limited?'ok':'warn');
      }catch(e){setMsg(e?.message||'自检失败','error');}finally{busy.value=false;}
    }
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

    const isolationNotice=()=>{
      if(stalled.value) return h('div',{class:'gya-note error'},[
        h('b','已触发整理熔断　'),
        h('span',status.value?.dispatch_pause_reason||`最老光鸭任务已 ${secondsText(status.value?.dispatch_oldest_age_seconds)} 未收到 MP 最终回执，插件停止新增任务。`),
        status.value?.dispatch_oldest_path?h('div',{style:{marginTop:'4px',wordBreak:'break-all'}},`最老任务：${status.value.dispatch_oldest_path}`):null
      ]);
      if(legacyBacklog.value>0) return h('div',{class:'gya-note warn'},[
        h('b','检测到旧版本队列积压　'),
        h('span',`当前光鸭未终态 ${inflight.value}，高于新上限 ${effectiveLimit.value}，约 ${legacyBacklog.value} 个属于升级前已提交任务。插件不会再追加新任务，等待 MoviePilot 消化；不会自动清空 MP 全局队列。`)
      ]);
      if(hostThreads.value===1) return h('div',{class:'gya-note warn'},[
        h('b','MoviePilot 当前只有 1 个整理线程　'),
        h('span','插件已限制为最多 1 个光鸭未终态任务，可防止再次灌满队列，但单个远程任务仍会占用唯一 worker。若希望普通整理与光鸭整理真正并行，请在 MoviePilot 中将 TRANSFER_THREADS 调整为至少 2。')
      ]);
      if(strictIsolation.value) return h('div',{class:'gya-note'},[
        h('b','队列隔离已生效　'),h('span',`MoviePilot 共 ${hostThreads.value} 个整理线程；光鸭实际占用上限 ${effectiveLimit.value}，至少为其它 MoviePilot 整理保留 1 个 worker。`)
      ]);
      return null;
    };

    const folderGroups=()=>h('div',{class:'gya-groups'},folderHistory.value.length?folderHistory.value.map(group=>{
      const key=groupKey(group),expanded=expandedGroups.value.has(key),metrics=groupMetrics(group);
      return h('div',{class:'gya-group'},[
        h('button',{class:'gya-group-head',onClick:()=>toggleGroup(group)},[
          h('span',{class:'gya-group-arrow'},expanded?'▼':'▶'),
          h('div',{class:'gya-group-main'},[h('b',group.group_name||'-'),h('small',group.group_path||''),group.latest_time?h('small',`最近：${group.latest_time}`):null]),
          h('div',{class:'gya-group-metrics'},metrics.map(m=>h('span',{class:`gya-chip ${m.cls}`},m.text)))
        ]),
        expanded?h('div',{class:'gya-group-body'},[
          group.summary_message?h('div',{class:'gya-group-summary'},group.summary_message):null,
          ...(group.rows||[]).map(row=>h('div',{class:'gya-history-row'},[
            h('div',row.time||'-'),
            h('div',[h('b',row.name||'-'),h('small',row.path||''),row.message?h('small',row.message):null]),
            h('div',{class:`gya-result ${row.result||''}`},RESULT_TEXT[row.result]||row.result||'-')
          ]))
        ]):null
      ]);
    }):h('div',{class:'gya-card-sub'},'暂无子目录整理历史'));

    const organizer=()=>h('div',{class:'gya-shell'},[
      h('div',{class:'gya-head'},[
        h('div',[h('div',{class:'gya-title'},'自动整理监控'),h('div',{class:'gya-sub'},'子目录完整扫描 → 受控背压入队 → MoviePilot 原生整理 → 最终回执。扫描批次与 MP 队列容量完全分离。')]),
        h('span',{class:'gya-badge'},'v3.4.0 preview')
      ]),
      h('div',{class:'gya-body'},[
        h('div',{class:'gya-card'},[
          h('div',{class:'gya-card-title'},'1. 监控目录'),
          h('div',{class:'gya-card-sub'},'按监控根的直接子文件夹形成整理批次；一个目录扫描完整后即可进入受控队列，不等待整棵目录扫描结束。'),
          h('div',{class:'gya-path'},[h('input',{class:'gya-input',value:monitorPath.value,onInput:e=>monitorPath.value=e.target.value,placeholder:'/例如：/光鸭媒体库'}),h('button',{class:'gya-btn',disabled:busy.value,onClick:openBrowser},'浏览')]),browser(),
          h('div',{class:'gya-actions',style:{marginTop:'10px'}},[
            h('label',{class:'gya-switch'},[h('input',{type:'checkbox',checked:enabled.value,onChange:e=>enabled.value=e.target.checked}),'启用自动监控整理']),
            h('label',{class:'gya-check'},[h('input',{type:'checkbox',checked:recursive.value,onChange:e=>recursive.value=e.target.checked}),'递归扫描批次内部目录'])
          ])
        ]),
        h('div',{class:'gya-card'},[
          h('div',{class:'gya-card-title'},'2. 扫描与队列参数'),
          h('div',{class:'gya-card-sub'},'“单轮候选上限”只限制一次扫描处理量；“光鸭 MP 占用上限”才限制真正进入 MoviePilot 全局整理队列的未终态任务。默认只占 1 个。'),
          h('div',{class:'gya-grid'},[
            h('div',{class:'gya-field'},[h('label','扫描间隔（秒）'),h('input',{class:'gya-input',type:'number',min:'30',max:'3600',value:interval.value,onInput:e=>interval.value=e.target.value})]),
            h('div',{class:'gya-field'},[h('label','文件稳定等待（秒）'),h('input',{class:'gya-input',type:'number',min:'0',max:'3600',value:stability.value,onInput:e=>stability.value=e.target.value})]),
            h('div',{class:'gya-field'},[h('label','单轮候选处理上限'),h('input',{class:'gya-input',type:'number',min:'1',max:'500',value:batchSize.value,onInput:e=>batchSize.value=e.target.value})]),
            h('div',{class:'gya-field'},[h('label','光鸭 MP 占用上限（1–8）'),h('input',{class:'gya-input',type:'number',min:'1',max:'8',value:maxInflight.value,onInput:e=>maxInflight.value=e.target.value})]),
            h('div',{class:'gya-field'},[h('label','无最终回执熔断（秒）'),h('input',{class:'gya-input',type:'number',min:'120',max:'7200',value:stallTimeout.value,onInput:e=>stallTimeout.value=e.target.value})]),
            h('div',{class:'gya-field'},[h('label','当前实际上限'),h('input',{class:'gya-input',disabled:true,value:String(effectiveLimit.value)})])
          ])
        ]),
        isolationNotice(),
        h('div',{class:'gya-note'},[h('b','整理规则仍由 MoviePilot 决定　'),h('span',`MP 目录配置 ${mp.value.directory_count||0} 条，光鸭相关 ${mp.value.guangya_directory_count||0} 条。目标目录、重命名、整理方式、覆盖、刮削和最终媒体身份均不在插件中复制。`)]),
        message.value?h('div',{class:`gya-msg ${messageKind.value==='error'?'error':messageKind.value==='warn'?'warn':''}`},message.value):null,
        h('div',{class:'gya-actions'},[
          h('button',{class:'gya-btn primary',disabled:busy.value,onClick:save},busy.value?'处理中…':'保存设置'),
          h('button',{class:'gya-btn',disabled:busy.value||monitorPath.value==='/',onClick:scan},'立即扫描'),
          h('button',{class:'gya-btn',disabled:busy.value,onClick:selfcheck},'运行自检'),
          h('button',{class:'gya-btn',disabled:busy.value,onClick:()=>loadStatus(false)},'刷新状态'),
          blocked.value>0?h('button',{class:'gya-btn warn',disabled:busy.value,onClick:unblock},`重新检查 MP 门控 (${blocked.value})`):null
        ]),
        h('div',{class:'gya-card'},[
          h('div',{class:'gya-card-title'},'运行状态'),
          h('div',{class:'gya-stats'},[
            ['扫描文件',status.value.inventory],['本轮提交',status.value.submitted],['光鸭占用',inflight.value],['可用槽位',queueSlots.value],['目录等待',status.value.pending_group_count],
            ['已完成',status.value.state_completed??status.value.completed],['重试等待',status.value.state_retry_wait??status.value.retry_wait],['MP 门控',status.value.state_blocked??status.value.blocked],['等待稳定',status.value.state_stabilizing??status.value.waiting],['旧队列超额',legacyBacklog.value]
          ].map(([k,v])=>h('div',{class:'gya-stat'},[h('span',k),h('b',String(v||0))]))),
          h('div',{class:'gya-statusline'},[
            h('span',{class:`gya-dot ${statusDot.value}`}),
            h('span',running.value?'自动监控已启用':'自动监控未启用'),
            h('span',`MP整理线程：${hostThreads.value||'-'}`),
            h('span',`光鸭实际上限：${effectiveLimit.value}`),
            h('span',`子目录：${status.value.groups_scanned||0}/${status.value.groups_discovered||0}`),
            status.value.current_group_name?h('span',`当前：${status.value.current_group_name}`):null,
            status.value.pending_group?h('span',`优先等待：${String(status.value.pending_group).split('/').pop()}`):null,
            h('span',`上次扫描：${status.value.last_scan||'尚未扫描'}`),
            status.value.duration_ms!=null?h('span',`耗时：${status.value.duration_ms} ms`):null,
            status.value.truncated?h('span','已触发部分扫描保护'):null
          ])
        ]),
        h('div',{class:'gya-card'},[
          h('div',{class:'gya-card-title'},'按子文件夹整理历史'),
          h('div',{class:'gya-card-sub'},'折叠态查看目录整体完成/整理中/重试/门控；展开后查看文件级最终回执。同一文件 queued → completed 只按最近状态计数。'),
          folderGroups()
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
