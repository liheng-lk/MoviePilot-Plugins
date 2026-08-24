import AccountPage from './__federation_expose_AssistantPage-dev.js?v=3.0.0';
import { importShared } from './__federation_fn_import-054b33c3.js';

const { defineComponent, h, ref, computed, onMounted } = await importShared('vue');
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
.gyo{width:100%;color:rgb(var(--v-theme-on-surface));font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}.gyo *{box-sizing:border-box}
.gyo-tabs{display:flex;gap:7px;padding:10px 14px;border:1px solid rgba(var(--v-theme-on-surface),.08);border-radius:12px;margin-bottom:10px;background:rgb(var(--v-theme-surface))}.gyo-tab{height:34px;padding:0 14px;border-radius:9px;border:1px solid rgba(var(--v-theme-on-surface),.1);background:transparent;color:inherit;cursor:pointer;font-size:12px}.gyo-tab.active{background:rgb(var(--v-theme-primary));border-color:transparent;color:rgb(var(--v-theme-on-primary));font-weight:700}
.gyo-shell{background:rgb(var(--v-theme-surface));border:1px solid rgba(var(--v-theme-on-surface),.08);border-radius:14px;overflow:hidden}.gyo-head{padding:16px 18px;border-bottom:1px solid rgba(var(--v-theme-on-surface),.07);display:flex;justify-content:space-between;align-items:center;gap:12px}.gyo-title{font-size:17px;font-weight:760}.gyo-sub{font-size:10.5px;opacity:.52;margin-top:3px}.gyo-badge{font-size:10px;padding:4px 8px;border-radius:999px;background:rgba(var(--v-theme-primary),.1);color:rgb(var(--v-theme-primary))}
.gyo-body{padding:14px 18px 18px;display:grid;gap:12px}.gyo-card{border:1px solid rgba(var(--v-theme-on-surface),.075);border-radius:11px;padding:13px;background:rgba(var(--v-theme-on-surface),.008)}.gyo-card-title{font-size:13px;font-weight:740;margin-bottom:3px}.gyo-card-sub{font-size:10px;opacity:.5;margin-bottom:10px}.gyo-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.gyo-grid3{display:grid;grid-template-columns:1.5fr 1fr 1fr;gap:10px}.gyo-field label{display:block;font-size:10px;opacity:.55;margin-bottom:4px}.gyo-input,.gyo-select{width:100%;height:38px;border:1px solid rgba(var(--v-theme-on-surface),.13);border-radius:8px;padding:0 10px;background:rgb(var(--v-theme-surface));color:inherit;font-size:11.5px}.gyo-path{display:grid;grid-template-columns:1fr auto;gap:7px}.gyo-btn{height:36px;padding:0 13px;border-radius:8px;border:1px solid rgba(var(--v-theme-on-surface),.13);background:transparent;color:inherit;cursor:pointer;font-size:11px}.gyo-btn.primary{background:rgb(var(--v-theme-primary));color:rgb(var(--v-theme-on-primary));border-color:transparent}.gyo-btn.danger{color:#ef4444;border-color:rgba(239,68,68,.3)}.gyo-btn:disabled{opacity:.4;cursor:not-allowed}.gyo-actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.gyo-check{display:flex;gap:7px;align-items:center;font-size:10.5px;opacity:.75}
.gyo-policy{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px;margin-top:9px}.gyo-chip{padding:8px;border-radius:8px;background:rgba(var(--v-theme-primary),.055);font-size:9.5px;min-width:0}.gyo-chip span{display:block;opacity:.48;margin-bottom:2px}.gyo-chip b{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:10.5px}
.gyo-msg{padding:9px 10px;border-radius:8px;font-size:10.5px;background:rgba(16,185,129,.08);color:#10b981}.gyo-msg.error{background:rgba(239,68,68,.08);color:#ef4444}.gyo-note{padding:9px;border-radius:8px;background:rgba(var(--v-theme-primary),.05);font-size:10px;opacity:.7;line-height:1.55}
.gyo-summary{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:7px}.gyo-stat{padding:9px;border:1px solid rgba(var(--v-theme-on-surface),.07);border-radius:8px}.gyo-stat span{display:block;font-size:9px;opacity:.46}.gyo-stat b{font-size:15px}.gyo-table{display:grid;gap:6px;max-height:430px;overflow:auto}.gyo-row{display:grid;grid-template-columns:minmax(170px,1.2fr) minmax(150px,1fr) minmax(150px,1.1fr) 84px;gap:8px;align-items:center;padding:8px;border:1px solid rgba(var(--v-theme-on-surface),.07);border-radius:8px;font-size:10px}.gyo-row small{display:block;opacity:.5;margin-top:2px;word-break:break-all}.gyo-status{padding:3px 7px;border-radius:999px;text-align:center;background:rgba(var(--v-theme-primary),.08)}.gyo-status.ready{color:#10b981;background:rgba(16,185,129,.1)}.gyo-status.conflict{color:#f59e0b;background:rgba(245,158,11,.1)}.gyo-status.unrecognized,.gyo-status.skipped{color:#ef4444;background:rgba(239,68,68,.08)}
.gyo-browser{border:1px solid rgba(var(--v-theme-on-surface),.1);border-radius:10px;padding:10px;margin-top:9px}.gyo-browser-head{display:flex;gap:7px;align-items:center;margin-bottom:8px}.gyo-browser-path{flex:1;font-size:10px;word-break:break-all;opacity:.65}.gyo-folders{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;max-height:220px;overflow:auto}.gyo-folder{padding:8px;border:1px solid rgba(var(--v-theme-on-surface),.08);border-radius:8px;cursor:pointer;font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;background:transparent;color:inherit;text-align:left}.gyo-folder:hover{border-color:rgb(var(--v-theme-primary))}
@media(max-width:850px){.gyo-grid,.gyo-grid3{grid-template-columns:1fr}.gyo-policy{grid-template-columns:1fr 1fr}.gyo-summary{grid-template-columns:repeat(2,1fr)}.gyo-row{grid-template-columns:1fr}.gyo-folders{grid-template-columns:1fr 1fr}}
`;

export default defineComponent({
  name: 'GuangyaCloudAssistantV320',
  props: { initialConfig: {type:Object, default:()=>({})}, api: {type:Object, default:null} },
  emits: ['close','switch'],
  setup(props,{emit}) {
    const tab=ref('account'), policies=ref([]), policyId=ref('auto'), sourcePath=ref('/'), targetPath=ref('/'), operation=ref('policy'), allowOverwrite=ref(false), maxItems=ref(100);
    const busy=ref(false), message=ref(''), messageError=ref(false), plan=ref(null), browserFor=ref(''), browserPath=ref('/'), browserFolders=ref([]), browserBusy=ref(false), history=ref([]);
    const selectedPolicy=computed(()=>policies.value.find(p=>p.id===policyId.value)||null);
    const summary=computed(()=>plan.value?.summary||{});
    const canExecute=computed(()=>Number(summary.value.ready||0)>0 && Boolean(plan.value?.plan_id));
    const statusText=s=>({ready:'可执行',conflict:'冲突',unrecognized:'未识别',skipped:'跳过'}[s]||s||'-');
    function setMsg(text,error=false){message.value=text||'';messageError.value=error;}
    async function loadPolicies(){try{const r=await getApi(props,'/organize/policies');if(!r?.success)throw new Error(r?.message||'读取失败');policies.value=r?.data?.policies||[];}catch(e){setMsg(e?.message||'读取 MoviePilot 目录策略失败',true);}}
    async function loadHistory(){try{const r=await getApi(props,'/organize/history');history.value=r?.data?.history||[];}catch{}}
    async function browse(path,forField=browserFor.value){browserBusy.value=true;try{const r=await postApi(props,'/organize/folders',{path:path||'/'});if(!r?.success)throw new Error(r?.message||'目录读取失败');browserFor.value=forField;browserPath.value=r.data.path;browserFolders.value=r.data.folders||[];}catch(e){setMsg(e?.message||'目录读取失败',true);}finally{browserBusy.value=false;}}
    async function openBrowser(which){await browse(which==='source'?sourcePath.value:targetPath.value,which);}
    function chooseCurrent(){if(browserFor.value==='source')sourcePath.value=browserPath.value;else if(browserFor.value==='target')targetPath.value=browserPath.value;browserFor.value='';plan.value=null;}
    async function preview(){busy.value=true;setMsg('');plan.value=null;try{const r=await postApi(props,'/organize/preview',{source_path:sourcePath.value,target_path:targetPath.value,policy_id:policyId.value,operation:operation.value,allow_overwrite:allowOverwrite.value,max_items:Number(maxItems.value||100)});if(!r?.success)throw new Error(r?.message||'预览失败');plan.value=r.data;setMsg(r.message||'预览完成');}catch(e){setMsg(e?.message||'预览失败',true);}finally{busy.value=false;}}
    async function execute(){if(!canExecute.value)return;const ok=globalThis.confirm?globalThis.confirm(`确认执行 ${summary.value.ready||0} 项网盘整理？\n源：${plan.value.source_path}\n目标：${plan.value.target_path}`):true;if(!ok)return;busy.value=true;try{const r=await postApi(props,'/organize/execute',{plan_id:plan.value.plan_id,confirm:true});setMsg(r?.message||'执行完成',!r?.success);plan.value=null;await loadHistory();}catch(e){setMsg(e?.message||'执行失败',true);}finally{busy.value=false;}}
    onMounted(async()=>{await Promise.all([loadPolicies(),loadHistory()]);});
    const policyCard=()=>selectedPolicy.value?h('div',{class:'gyo-policy'},[
      h('div',{class:'gyo-chip'},[h('span','媒体类型 / 类别'),h('b',`${selectedPolicy.value.media_type||'全部'} / ${selectedPolicy.value.media_category||'全部'}`)]),
      h('div',{class:'gyo-chip'},[h('span','类型/类别子目录'),h('b',`${selectedPolicy.value.library_type_folder?'开':'关'} / ${selectedPolicy.value.library_category_folder?'开':'关'}`)]),
      h('div',{class:'gyo-chip'},[h('span','MP整理 / 重命名 / 覆盖'),h('b',`${selectedPolicy.value.transfer_type||'-'} / ${selectedPolicy.value.renaming?'智能命名':'保留名'} / ${selectedPolicy.value.overwrite_mode||'never'}`)]),
      h('div',{class:'gyo-chip'},[h('span','MP媒体库参考路径'),h('b',selectedPolicy.value.library_path||'-')])
    ]):h('div',{class:'gyo-note'},'自动模式会按 MoviePilot 当前媒体库目录配置的优先级、媒体类型和媒体类别逐条匹配。');
    const browser=()=>!browserFor.value?null:h('div',{class:'gyo-browser'},[
      h('div',{class:'gyo-browser-head'},[h('button',{class:'gyo-btn',disabled:browserPath.value==='/'||browserBusy.value,onClick:()=>browse(browserPath.value.split('/').slice(0,-1).join('/')||'/')},'上一级'),h('div',{class:'gyo-browser-path'},browserPath.value),h('button',{class:'gyo-btn primary',onClick:chooseCurrent},`设为${browserFor.value==='source'?'源':'目标'}目录`),h('button',{class:'gyo-btn',onClick:()=>browserFor.value=''},'关闭')]),
      h('div',{class:'gyo-folders'},browserFolders.value.length?browserFolders.value.map(f=>h('button',{class:'gyo-folder',title:f.path,onClick:()=>browse(f.path)},`📁 ${f.name}`)):h('div',{class:'gyo-card-sub'},browserBusy.value?'读取中…':'当前目录没有子文件夹'))
    ]);
    const previewTable=()=>!plan.value?null:h('div',{class:'gyo-card'},[
      h('div',{class:'gyo-card-title'},'完整重新整理预览'),h('div',{class:'gyo-card-sub'},plan.value.safe_note||'先预览、后确认执行'),
      h('div',{class:'gyo-summary'},[
        ['扫描项目',summary.value.total],['可执行',summary.value.ready],['未识别',summary.value.unrecognized],['冲突',summary.value.conflict],['跳过',summary.value.skipped]
      ].map(([k,v])=>h('div',{class:'gyo-stat'},[h('span',k),h('b',String(v||0))]))),
      h('div',{class:'gyo-table',style:{marginTop:'9px'}},(plan.value.items||[]).map(row=>h('div',{class:'gyo-row'},[
        h('div',[h('b',row.source_name||'-'),h('small',row.source_path||'')]),
        h('div',[h('b',row.media?`${row.media.type||''} · ${row.media.title||''}`:'未识别'),h('small',row.media?`${row.media.category||'未分类'} ${row.media.year||''}`:(row.reason||''))]),
        h('div',[h('b',row.target_path||'-'),h('small',row.policy?`${row.policy.name} · ${row.operation||'-'}`:(row.reason||''))]),
        h('div',{class:`gyo-status ${row.status||''}`,title:row.reason||''},statusText(row.status))
      ]))),
      h('div',{class:'gyo-actions',style:{marginTop:'10px'}},[h('button',{class:'gyo-btn primary',disabled:busy.value||!canExecute.value,onClick:execute},busy.value?'处理中…':`确认执行 ${summary.value.ready||0} 项`),h('button',{class:'gyo-btn',disabled:busy.value,onClick:preview},'重新预览')])
    ]);
    const organizer=()=>h('div',{class:'gyo-shell'},[
      h('div',{class:'gyo-head'},[h('div',[h('div',{class:'gyo-title'},'网盘整理'),h('div',{class:'gyo-sub'},'MoviePilot 负责识别、分类与智能重命名；光鸭按预览结果重建目录并同盘移动/复制')]),h('span',{class:'gyo-badge'},'v3.2.0')]),
      h('div',{class:'gyo-body'},[
        h('div',{class:'gyo-card'},[h('div',{class:'gyo-card-title'},'1. 选择源目录与目标目录'),h('div',{class:'gyo-card-sub'},'首版禁止直接整理根目录，也禁止把目标目录放在源目录内部'),h('div',{class:'gyo-grid'},[
          h('div',{class:'gyo-field'},[h('label','光鸭源目录'),h('div',{class:'gyo-path'},[h('input',{class:'gyo-input',value:sourcePath.value,onInput:e=>{sourcePath.value=e.target.value;plan.value=null;}}),h('button',{class:'gyo-btn',onClick:()=>openBrowser('source')},'浏览')])]),
          h('div',{class:'gyo-field'},[h('label','光鸭目标根目录'),h('div',{class:'gyo-path'},[h('input',{class:'gyo-input',value:targetPath.value,onInput:e=>{targetPath.value=e.target.value;plan.value=null;}}),h('button',{class:'gyo-btn',onClick:()=>openBrowser('target')},'浏览')])])
        ]),browser()]),
        h('div',{class:'gyo-card'},[h('div',{class:'gyo-card-title'},'2. MoviePilot 目录分类策略'),h('div',{class:'gyo-card-sub'},'选项实时来自 MP 媒体库目录配置，不在插件内另建分类表'),h('div',{class:'gyo-grid3'},[
          h('div',{class:'gyo-field'},[h('label','目录策略'),h('select',{class:'gyo-select',value:policyId.value,onChange:e=>{policyId.value=e.target.value;plan.value=null;}},[h('option',{value:'auto'},'自动按 MoviePilot 优先级匹配'),...policies.value.map(p=>h('option',{value:p.id},`${p.name} · ${p.media_type||'全部'}${p.media_category?'/'+p.media_category:''}`))])]),
          h('div',{class:'gyo-field'},[h('label','整理方式'),h('select',{class:'gyo-select',value:operation.value,onChange:e=>{operation.value=e.target.value;plan.value=null;}},[h('option',{value:'policy'},'按 MP 配置'),h('option',{value:'move'},'强制移动'),h('option',{value:'copy'},'强制复制')])]),
          h('div',{class:'gyo-field'},[h('label','单次扫描上限'),h('input',{class:'gyo-input',type:'number',min:'1',max:'300',value:maxItems.value,onInput:e=>{maxItems.value=e.target.value;plan.value=null;}})])
        ]),policyCard(),h('div',{class:'gyo-actions',style:{marginTop:'9px'}},[h('label',{class:'gyo-check'},[h('input',{type:'checkbox',checked:allowOverwrite.value,onChange:e=>{allowOverwrite.value=e.target.checked;plan.value=null;}}),'允许按 MP 覆盖策略处理同名目标（危险，默认关闭）']),h('button',{class:'gyo-btn',onClick:loadPolicies},'刷新 MP 策略')])]),
        h('div',{class:'gyo-note'},'当前 v3.1.0 使用 MP 的媒体类型、媒体类别、library_type_folder、library_category_folder、transfer_type 与 overwrite_mode 进行云盘分类；保持光鸭原文件/目录名称，不在首版直接启用智能重命名，避免误改大批文件名。'),
        message.value?h('div',{class:`gyo-msg ${messageError.value?'error':''}`},message.value):null,
        h('div',{class:'gyo-actions'},[h('button',{class:'gyo-btn primary',disabled:busy.value,onClick:preview},busy.value?'正在识别与规划…':'预览整理计划')]),
        previewTable(),
        history.value.length?h('div',{class:'gyo-card'},[h('div',{class:'gyo-card-title'},'最近整理记录'),h('div',{class:'gyo-card-sub'},'仅展示最近 5 次'),...history.value.slice(0,5).map(x=>h('div',{class:'gyo-note',style:{marginBottom:'6px'}},`${x.time||''} · ${x.source_path||''} → ${x.target_path||''} · 成功 ${x.success||0} / 失败 ${x.failed||0}`))]):null
      ])
    ]);
    return()=>h('div',{class:'gyo'},[h('style',css),h('div',{class:'gyo-tabs'},[h('button',{class:`gyo-tab ${tab.value==='account'?'active':''}`,onClick:()=>tab.value='account'},'账号与存储'),h('button',{class:`gyo-tab ${tab.value==='organize'?'active':''}`,onClick:()=>tab.value='organize'},'网盘整理')]),tab.value==='account'?h(AccountPage,{initialConfig:props.initialConfig,api:props.api,onClose:()=>emit('close'),onSwitch:()=>emit('switch')}):organizer()]);
  }
});
