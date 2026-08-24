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
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

const css = `
.gya{width:100%;color:rgb(var(--v-theme-on-surface));font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}.gya *{box-sizing:border-box}
.gya-tabs{display:flex;gap:7px;padding:10px 14px;border:1px solid rgba(var(--v-theme-on-surface),.08);border-radius:12px;margin-bottom:10px;background:rgb(var(--v-theme-surface))}.gya-tab{height:34px;padding:0 14px;border-radius:9px;border:1px solid rgba(var(--v-theme-on-surface),.1);background:transparent;color:inherit;cursor:pointer;font-size:12px}.gya-tab.active{background:rgb(var(--v-theme-primary));border-color:transparent;color:rgb(var(--v-theme-on-primary));font-weight:700}
.gya-shell{background:rgb(var(--v-theme-surface));border:1px solid rgba(var(--v-theme-on-surface),.08);border-radius:14px;overflow:hidden}.gya-head{padding:16px 18px;border-bottom:1px solid rgba(var(--v-theme-on-surface),.07);display:flex;justify-content:space-between;align-items:center;gap:12px}.gya-title{font-size:17px;font-weight:760}.gya-sub{font-size:10.5px;opacity:.55;margin-top:3px;line-height:1.6}.gya-badge{font-size:10px;padding:4px 8px;border-radius:999px;background:rgba(var(--v-theme-primary),.1);color:rgb(var(--v-theme-primary))}
.gya-body{padding:14px 18px 18px;display:grid;gap:12px}.gya-card{border:1px solid rgba(var(--v-theme-on-surface),.075);border-radius:11px;padding:13px;background:rgba(var(--v-theme-on-surface),.008)}.gya-card-title{font-size:13px;font-weight:740;margin-bottom:3px}.gya-card-sub{font-size:10px;opacity:.52;margin-bottom:10px;line-height:1.55}.gya-grid{display:grid;grid-template-columns:1.6fr .8fr .8fr;gap:10px}.gya-field label{display:block;font-size:10px;opacity:.55;margin-bottom:4px}.gya-input,.gya-select{width:100%;height:38px;border:1px solid rgba(var(--v-theme-on-surface),.13);border-radius:8px;padding:0 10px;background:rgb(var(--v-theme-surface));color:inherit;font-size:11.5px}.gya-path{display:grid;grid-template-columns:1fr auto;gap:7px}.gya-btn{height:36px;padding:0 13px;border-radius:8px;border:1px solid rgba(var(--v-theme-on-surface),.13);background:transparent;color:inherit;cursor:pointer;font-size:11px}.gya-btn.primary{background:rgb(var(--v-theme-primary));color:rgb(var(--v-theme-on-primary));border-color:transparent}.gya-btn:disabled{opacity:.4;cursor:not-allowed}.gya-actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.gya-check{display:flex;gap:7px;align-items:center;font-size:10.5px;opacity:.78}.gya-switch{display:flex;align-items:center;gap:8px;font-size:11.5px;font-weight:650}
.gya-note{padding:10px;border-radius:8px;background:rgba(var(--v-theme-primary),.055);font-size:10.5px;line-height:1.65}.gya-note b{color:rgb(var(--v-theme-primary))}.gya-msg{padding:9px 10px;border-radius:8px;font-size:10.5px;background:rgba(16,185,129,.08);color:#10b981}.gya-msg.error{background:rgba(239,68,68,.08);color:#ef4444}
.gya-stats{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:7px}.gya-stat{padding:9px;border:1px solid rgba(var(--v-theme-on-surface),.07);border-radius:8px}.gya-stat span{display:block;font-size:9px;opacity:.48}.gya-stat b{font-size:15px}.gya-statusline{display:flex;gap:10px;align-items:center;flex-wrap:wrap;font-size:10px;opacity:.67;margin-top:8px}.gya-dot{width:8px;height:8px;border-radius:50%;background:#9ca3af}.gya-dot.on{background:#10b981}.gya-dot.err{background:#ef4444}
.gya-browser{border:1px solid rgba(var(--v-theme-on-surface),.1);border-radius:10px;padding:10px;margin-top:9px}.gya-browser-head{display:flex;gap:7px;align-items:center;margin-bottom:8px}.gya-browser-path{flex:1;font-size:10px;word-break:break-all;opacity:.65}.gya-folders{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;max-height:220px;overflow:auto}.gya-folder{padding:8px;border:1px solid rgba(var(--v-theme-on-surface),.08);border-radius:8px;cursor:pointer;font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;background:transparent;color:inherit;text-align:left}.gya-folder:hover{border-color:rgb(var(--v-theme-primary))}
.gya-history{display:grid;gap:6px;max-height:320px;overflow:auto}.gya-history-row{display:grid;grid-template-columns:145px minmax(170px,1fr) 120px;gap:8px;align-items:center;padding:8px;border:1px solid rgba(var(--v-theme-on-surface),.07);border-radius:8px;font-size:10px}.gya-history-row small{opacity:.5;word-break:break-all}.gya-result{padding:3px 7px;border-radius:999px;text-align:center;background:rgba(var(--v-theme-primary),.08)}.gya-result.submitted{color:#10b981;background:rgba(16,185,129,.1)}.gya-result.gated{color:#f59e0b;background:rgba(245,158,11,.1)}
@media(max-width:900px){.gya-grid{grid-template-columns:1fr}.gya-stats{grid-template-columns:repeat(2,1fr)}.gya-history-row{grid-template-columns:1fr}.gya-folders{grid-template-columns:1fr 1fr}}
`;

export default defineComponent({
  name: 'GuangyaCloudAssistantV320',
  props: { initialConfig: {type:Object, default:()=>({})}, api: {type:Object, default:null} },
  emits: ['close','switch'],
  setup(props,{emit}) {
    const tab=ref('account');
    const enabled=ref(false), monitorPath=ref('/'), interval=ref(60), stability=ref(30), batchSize=ref(100), recursive=ref(true);
    const mp=ref({}), status=ref({}), history=ref([]), busy=ref(false), message=ref(''), messageError=ref(false);
    const browserOpen=ref(false), browserPath=ref('/'), browserFolders=ref([]), browserBusy=ref(false);
    let timer=null;
    const running=computed(()=>Boolean(enabled.value));
    const statusDot=computed(()=>status.value?.failed>0?'err':running.value?'on':'');
    function setMsg(text,error=false){message.value=text||'';messageError.value=error;}
    function applyConfig(c={}){enabled.value=Boolean(c.enabled);monitorPath.value=c.path||'/';interval.value=Number(c.interval||60);stability.value=Number(c.stability??30);batchSize.value=Number(c.batch_size||100);recursive.value=c.recursive!==false;}
    async function loadConfig(){try{const r=await getApi(props,'/organize/monitor/config');if(!r?.success)throw new Error(r?.message||'读取失败');applyConfig(r?.data?.config||{});mp.value=r?.data?.mp||{};}catch(e){setMsg(e?.message||'读取自动整理设置失败',true);}}
    async function loadStatus(silent=true){try{const r=await getApi(props,'/organize/monitor/status');if(!r?.success)throw new Error(r?.message||'读取失败');status.value=r?.data?.status||{};history.value=r?.data?.history||[];mp.value=r?.data?.mp||mp.value;if(!silent&&r?.message)setMsg(r.message);}catch(e){if(!silent)setMsg(e?.message||'读取运行状态失败',true);}}
    async function save(){busy.value=true;setMsg('');try{const r=await postApi(props,'/organize/monitor/config',{enabled:enabled.value,path:monitorPath.value,interval:Number(interval.value||60),stability:Number(stability.value||0),batch_size:Number(batchSize.value||100),recursive:recursive.value});if(!r?.success)throw new Error(r?.message||'保存失败');applyConfig(r?.data?.config||{});mp.value=r?.data?.mp||mp.value;setMsg(r?.message||'设置已保存');await loadStatus(true);}catch(e){setMsg(e?.message||'保存自动整理设置失败',true);}finally{busy.value=false;}}
    async function scan(){busy.value=true;setMsg('');try{const r=await postApi(props,'/organize/monitor/scan',{});setMsg(r?.message||'扫描完成',!r?.success);await loadStatus(true);}catch(e){setMsg(e?.message||'立即扫描失败',true);}finally{busy.value=false;}}
    async function browse(path=browserPath.value){browserBusy.value=true;try{const r=await postApi(props,'/organize/folders',{path:path||'/'});if(!r?.success)throw new Error(r?.message||'目录读取失败');browserOpen.value=true;browserPath.value=r.data.path||'/';browserFolders.value=r.data.folders||[];}catch(e){setMsg(e?.message||'目录读取失败',true);}finally{browserBusy.value=false;}}
    async function openBrowser(){await browse(monitorPath.value||'/');}
    function chooseCurrent(){monitorPath.value=browserPath.value;browserOpen.value=false;}
    function parentPath(){return browserPath.value==='/'?'/':(browserPath.value.split('/').slice(0,-1).join('/')||'/');}
    onMounted(async()=>{await Promise.all([loadConfig(),loadStatus(true)]);timer=setInterval(()=>{if(tab.value==='organize')loadStatus(true);},10000);});
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
        h('div',[h('div',{class:'gya-title'},'自动整理监控'),h('div',{class:'gya-sub'},'插件只监控光鸭目录；识别、分类、重命名、目标路径、整理方式和刮削全部交给 MoviePilot 内置整理链。')]),
        h('span',{class:'gya-badge'},'v3.2.0')
      ]),
      h('div',{class:'gya-body'},[
        h('div',{class:'gya-card'},[
          h('div',{class:'gya-card-title'},'1. 监控目录'),
          h('div',{class:'gya-card-sub'},'检测该目录中新出现或内容发生变化的媒体文件。光鸭云盘属于远程存储，因此采用轻量轮询，不使用本地文件系统监听。'),
          h('div',{class:'gya-path'},[
            h('input',{class:'gya-input',value:monitorPath.value,onInput:e=>monitorPath.value=e.target.value,placeholder:'/例如：/转存待整理'}),
            h('button',{class:'gya-btn',disabled:busy.value,onClick:openBrowser},'浏览')
          ]),browser(),
          h('div',{class:'gya-actions',style:{marginTop:'10px'}},[
            h('label',{class:'gya-switch'},[h('input',{type:'checkbox',checked:enabled.value,onChange:e=>enabled.value=e.target.checked}),'启用自动监控整理']),
            h('label',{class:'gya-check'},[h('input',{type:'checkbox',checked:recursive.value,onChange:e=>recursive.value=e.target.checked}),'递归监控子目录'])
          ])
        ]),
        h('div',{class:'gya-card'},[
          h('div',{class:'gya-card-title'},'2. 监控参数'),
          h('div',{class:'gya-card-sub'},'这些参数只控制“什么时候发现文件”，不会改变 MoviePilot 的整理规则。'),
          h('div',{class:'gya-grid'},[
            h('div',{class:'gya-field'},[h('label','扫描间隔（秒）'),h('input',{class:'gya-input',type:'number',min:'30',max:'3600',value:interval.value,onInput:e=>interval.value=e.target.value})]),
            h('div',{class:'gya-field'},[h('label','文件稳定等待（秒）'),h('input',{class:'gya-input',type:'number',min:'0',max:'3600',value:stability.value,onInput:e=>stability.value=e.target.value})]),
            h('div',{class:'gya-field'},[h('label','单次提交上限'),h('input',{class:'gya-input',type:'number',min:'1',max:'500',value:batchSize.value,onInput:e=>batchSize.value=e.target.value})])
          ])
        ]),
        h('div',{class:'gya-note'},[
          h('b','整理规则：MoviePilot 内置'),
          h('span',`　当前 MP 目录配置 ${mp.value.directory_count||0} 条，其中启用整理 ${mp.value.organize_enabled_count||0} 条。`),
          h('br'),
          h('span',mp.value.message||'插件不会建立自己的电影/电视剧分类表，也不会自己拼接文件夹或文件名。')
        ]),
        message.value?h('div',{class:`gya-msg ${messageError.value?'error':''}`},message.value):null,
        h('div',{class:'gya-actions'},[
          h('button',{class:'gya-btn primary',disabled:busy.value,onClick:save},busy.value?'处理中…':'保存设置'),
          h('button',{class:'gya-btn',disabled:busy.value||monitorPath.value==='/',onClick:scan},'立即扫描'),
          h('button',{class:'gya-btn',disabled:busy.value,onClick:()=>loadStatus(false)},'刷新状态')
        ]),
        h('div',{class:'gya-card'},[
          h('div',{class:'gya-card-title'},'运行状态'),
          h('div',{class:'gya-stats'},[
            ['扫描文件',status.value.inventory],['发现变化',status.value.changed],['提交 MP',status.value.submitted],['MP 门控',status.value.gated],['等待稳定',status.value.waiting],['失败',status.value.failed]
          ].map(([k,v])=>h('div',{class:'gya-stat'},[h('span',k),h('b',String(v||0))]))),
          h('div',{class:'gya-statusline'},[
            h('span',{class:`gya-dot ${statusDot.value}`}),
            h('span',running.value?'自动监控已启用':'自动监控未启用'),
            h('span',`上次扫描：${status.value.last_scan||'尚未扫描'}`),
            status.value.duration_ms!=null?h('span',`耗时：${status.value.duration_ms} ms`):null,
            status.value.truncated?h('span','扫描达到安全上限，后续文件将在下一轮继续处理'):null
          ])
        ]),
        h('div',{class:'gya-card'},[
          h('div',{class:'gya-card-title'},'最近监控整理记录'),
          h('div',{class:'gya-card-sub'},'这里记录的是“提交给 MP / 被 MP 门控”的结果，真正的分类、重命名和整理结果继续以 MoviePilot 整理历史为准。'),
          h('div',{class:'gya-history'},history.value.length?history.value.map(row=>h('div',{class:'gya-history-row'},[
            h('div',[h('b',row.time||'-')]),
            h('div',[h('b',row.name||'-'),h('small',row.path||'')]),
            h('div',{class:`gya-result ${row.result||''}`},row.result==='submitted'?'已提交 MP':'MP 门控')
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
