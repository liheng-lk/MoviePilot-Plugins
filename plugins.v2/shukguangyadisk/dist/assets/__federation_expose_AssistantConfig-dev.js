import { importShared } from './__federation_fn_import-054b33c3.js';
const { defineComponent, h, reactive, ref, onMounted } = await importShared('vue');
const PLUGIN_ID='ShukGuangYaDisk';

async function getApi(props,path){const p=`plugin/${PLUGIN_ID}${path}`;if(props.api?.get)return props.api.get(p);const r=await fetch(`/api/v1/plugin/${PLUGIN_ID}${path}`);if(!r.ok)throw new Error(`HTTP ${r.status}`);return r.json();}
async function postApi(props,path,body={}){const p=`plugin/${PLUGIN_ID}${path}`;if(props.api?.post)return props.api.post(p,body);const r=await fetch(`/api/v1/plugin/${PLUGIN_ID}${path}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(!r.ok)throw new Error(`HTTP ${r.status}`);return r.json();}
function maskToken(v){const s=String(v||'');if(!s)return '未登录';return s.length>16?`${s.slice(0,6)}••••••${s.slice(-6)}`:'已保存';}

const css=`
.gy-config{width:100%;margin:0;padding:0;box-sizing:border-box;color:rgb(var(--v-theme-on-surface));font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}.gy-config *{box-sizing:border-box}
.gyc-shell{width:100%;background:rgb(var(--v-theme-surface));border-radius:14px;overflow:hidden}.gyc-head{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:15px 18px;border-bottom:1px solid rgba(var(--v-theme-on-surface),.07)}
.gyc-brand{display:flex;align-items:center;gap:11px}.gyc-logo{width:40px;height:40px;border-radius:11px;display:grid;place-items:center;background:rgba(var(--v-theme-primary),.11);color:rgb(var(--v-theme-primary));font-size:20px}.gyc-title{font-size:17px;font-weight:760}.gyc-sub{margin-top:4px;font-size:10.5px;color:rgba(var(--v-theme-on-surface),.48)}.gyc-actions{display:flex;gap:7px}.gyc-btn{height:34px;padding:0 12px;border-radius:8px;border:1px solid rgba(var(--v-theme-on-surface),.12);background:transparent;color:inherit;font-size:11px;cursor:pointer}.gyc-btn.primary{background:rgb(var(--v-theme-primary));color:rgb(var(--v-theme-on-primary));border-color:transparent}.gyc-btn:disabled{opacity:.6;cursor:default}
.gyc-body{padding:14px 18px 12px}.gyc-grid{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(330px,.85fr);gap:12px;align-items:start}.gyc-stack{display:grid;gap:10px}.gyc-card{border:1px solid rgba(var(--v-theme-on-surface),.075);border-radius:11px;background:rgba(var(--v-theme-on-surface),.007);padding:14px}.gyc-card h3{margin:0;font-size:13px}.gyc-card p{margin:3px 0 11px;font-size:10px;color:rgba(var(--v-theme-on-surface),.48);line-height:1.5}
.gyc-switches{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;margin-bottom:10px}.gyc-switch{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 11px;border:1px solid rgba(var(--v-theme-on-surface),.075);border-radius:9px}.gyc-switch span{font-size:11px}.gyc-toggle{width:42px;height:24px;border:0;border-radius:999px;background:rgba(var(--v-theme-on-surface),.12);padding:3px;cursor:pointer;transition:.2s}.gyc-toggle i{display:block;width:18px;height:18px;border-radius:50%;background:white;box-shadow:0 1px 4px rgba(0,0,0,.18);transition:.2s}.gyc-toggle.on{background:rgb(var(--v-theme-primary))}.gyc-toggle.on i{transform:translateX(18px)}.gyc-toggle.danger.on{background:#ef4444}
.gyc-fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.gyc-field label{display:block;font-size:9.7px;color:rgba(var(--v-theme-on-surface),.5);margin-bottom:4px}.gyc-input,.gyc-select{width:100%;height:37px;border:1px solid rgba(var(--v-theme-on-surface),.12);border-radius:8px;background:rgb(var(--v-theme-surface));color:inherit;padding:0 10px;font-size:11.5px;outline:none}.gyc-input[readonly]{background:rgba(var(--v-theme-on-surface),.025);color:rgba(var(--v-theme-on-surface),.65)}.gyc-full{grid-column:1/-1}
.gyc-session{display:grid;gap:8px}.gyc-line{display:grid;grid-template-columns:90px minmax(0,1fr);gap:10px;align-items:center;padding:8px 0;border-bottom:1px solid rgba(var(--v-theme-on-surface),.05)}.gyc-line:last-child{border-bottom:0}.gyc-line span{font-size:9.7px;color:rgba(var(--v-theme-on-surface),.46)}.gyc-line b{font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.gyc-ok{color:#10b981}.gyc-warn{color:#f59e0b}
.gyc-help{display:grid;gap:8px}.gyc-tip{padding:9px 10px;border-radius:8px;background:rgba(var(--v-theme-primary),.055);font-size:10px;line-height:1.6;color:rgba(var(--v-theme-on-surface),.58)}.gyc-msg{margin-top:10px;padding:8px 10px;border-radius:8px;font-size:10.5px;background:rgba(16,185,129,.07);color:#10b981}.gyc-msg.error{background:rgba(239,68,68,.07);color:#ef4444}.gyc-footer{display:flex;justify-content:space-between;gap:10px;padding:8px 18px;border-top:1px solid rgba(var(--v-theme-on-surface),.06);font-size:9px;color:rgba(var(--v-theme-on-surface),.37)}
@media(max-width:1000px){.gyc-switches{grid-template-columns:1fr 1fr}.gyc-grid{grid-template-columns:1fr}}
@media(max-width:640px){.gyc-head{padding:12px}.gyc-body{padding:10px}.gyc-title{font-size:15px}.gyc-sub{display:none}.gyc-fields,.gyc-switches{grid-template-columns:1fr}.gyc-actions{gap:5px}.gyc-btn{padding:0 9px}.gyc-footer{flex-direction:column;padding:8px 10px}}
`;

export default defineComponent({
  name:'GuangyaCloudAssistantConfigDev',
  props:{initialConfig:{type:Object,default:()=>({})},api:{type:Object,default:()=>({})}},
  emits:['close','switch'],
  setup(props,{emit}){
    const cfg=reactive({enabled:false,permanently_delete:false,upload_progress_log:false,client_id:'',device_id:'',poll_interval:5,page_size:100,order_by:3,sort_type:1,access_token:'',refresh_token:'',logged_in:false,storage_name:'光鸭云盘助手'});
    const loading=ref(false),saving=ref(false),message=ref(''),messageType=ref('');
    function apply(d={}){cfg.enabled=Boolean(d.enabled);cfg.permanently_delete=Boolean(d.permanently_delete);cfg.upload_progress_log=Boolean(d.upload_progress_log);cfg.client_id=d.client_id||'';cfg.device_id=d.device_id||'';cfg.poll_interval=Number(d.poll_interval||5);cfg.page_size=Number(d.page_size||100);cfg.order_by=Number(d.order_by||3);cfg.sort_type=Number(d.sort_type??1);cfg.access_token=d.access_token||'';cfg.refresh_token=d.refresh_token||'';cfg.logged_in=Boolean(d.logged_in);cfg.storage_name=d.storage_name||'光鸭云盘助手';}
    async function load(){loading.value=true;message.value='';try{apply(await getApi(props,'/config'));}catch(e){messageType.value='error';message.value=`加载配置失败：${e?.message||e}`;}finally{loading.value=false;}}
    async function save(){saving.value=true;message.value='';try{const r=await postApi(props,'/config',{enabled:cfg.enabled,permanently_delete:cfg.permanently_delete,upload_progress_log:cfg.upload_progress_log,client_id:cfg.client_id,device_id:cfg.device_id,poll_interval:Number(cfg.poll_interval||5),page_size:Number(cfg.page_size||100),order_by:Number(cfg.order_by||3),sort_type:Number(cfg.sort_type??1),access_token:cfg.access_token,refresh_token:cfg.refresh_token});if(r?.success===false)throw new Error(r?.message||'保存失败');if(r?.data)apply(r.data);messageType.value='success';message.value=r?.message||'配置已保存';}catch(e){messageType.value='error';message.value=`保存失败：${e?.message||e}`;}finally{saving.value=false;}}
    onMounted(load);
    const field=(label,node,full=false)=>h('div',{class:`gyc-field ${full?'gyc-full':''}`},[h('label',label),node]);
    const line=(k,v,cls='')=>h('div',{class:'gyc-line'},[h('span',k),h('b',{class:cls},v||'-')]);
    return()=>h('div',{class:'gy-config'},[h('style',css),h('div',{class:'gyc-shell'},[
      h('header',{class:'gyc-head'},[h('div',{class:'gyc-brand'},[h('div',{class:'gyc-logo'},'⚙'),h('div',[h('div',{class:'gyc-title'},'光鸭云盘助手 · 设置'),h('div',{class:'gyc-sub'},'运行参数、上传监控与授权会话管理')])]),h('div',{class:'gyc-actions'},[h('button',{class:'gyc-btn',onClick:()=>emit('switch')},'状态页'),h('button',{class:'gyc-btn primary',disabled:saving.value,onClick:save},saving.value?'保存中…':'保存'),h('button',{class:'gyc-btn',onClick:()=>emit('close')},'关闭')])]),
      h('main',{class:'gyc-body'},[h('div',{class:'gyc-grid'},[
        h('section',{class:'gyc-stack'},[
          h('div',{class:'gyc-card'},[h('h3','运行配置'),h('p','上传进度监控默认关闭；排查整理上传问题时可临时开启。'),h('div',{class:'gyc-switches'},[
            h('div',{class:'gyc-switch'},[h('span','启用插件'),h('button',{class:`gyc-toggle ${cfg.enabled?'on':''}`,onClick:()=>cfg.enabled=!cfg.enabled},[h('i')])]),
            h('div',{class:'gyc-switch'},[h('span','彻底删除'),h('button',{class:`gyc-toggle danger ${cfg.permanently_delete?'on':''}`,onClick:()=>cfg.permanently_delete=!cfg.permanently_delete},[h('i')])]),
            h('div',{class:'gyc-switch'},[h('span','上传进度监控'),h('button',{class:`gyc-toggle ${cfg.upload_progress_log?'on':''}`,onClick:()=>cfg.upload_progress_log=!cfg.upload_progress_log},[h('i')])])
          ]),h('div',{class:'gyc-fields'},[
            field('轮询间隔（秒）',h('input',{class:'gyc-input',type:'number',min:2,max:30,value:cfg.poll_interval,onInput:e=>cfg.poll_interval=e.target.value})),
            field('分页大小',h('select',{class:'gyc-select',value:cfg.page_size,onChange:e=>cfg.page_size=e.target.value},[50,100,200,500].map(v=>h('option',{value:v},String(v))))),
            field('排序字段',h('select',{class:'gyc-select',value:cfg.order_by,onChange:e=>cfg.order_by=e.target.value},[h('option',{value:1},'名称'),h('option',{value:2},'大小'),h('option',{value:3},'更新时间')])),
            field('排序方向',h('select',{class:'gyc-select',value:cfg.sort_type,onChange:e=>cfg.sort_type=e.target.value},[h('option',{value:1},'升序'),h('option',{value:0},'降序')]))
          ])]),
          h('div',{class:'gyc-card'},[h('h3','高级参数'),h('p','Client ID 与设备 ID 由插件维持，通常无需手动修改。'),h('div',{class:'gyc-fields'},[
            field('Client ID',h('input',{class:'gyc-input',value:cfg.client_id,readonly:true})),field('设备 ID',h('input',{class:'gyc-input',value:cfg.device_id,readonly:true})),
            field('Access Token',h('input',{class:'gyc-input',value:maskToken(cfg.access_token),readonly:true}),true),field('Refresh Token',h('input',{class:'gyc-input',value:maskToken(cfg.refresh_token),readonly:true}),true)
          ])])
        ]),
        h('aside',{class:'gyc-stack'},[
          h('div',{class:'gyc-card'},[h('h3','账号与存储'),h('p','登录请在状态页通过扫码或短信完成。'),h('div',{class:'gyc-session'},[line('登录状态',cfg.logged_in?'已登录':'未登录',cfg.logged_in?'gyc-ok':'gyc-warn'),line('插件状态',cfg.enabled?'已启用':'未启用',cfg.enabled?'gyc-ok':'gyc-warn'),line('存储名称',cfg.storage_name),line('进度监控',cfg.upload_progress_log?'已开启':'已关闭',cfg.upload_progress_log?'gyc-ok':''),line('Client ID',cfg.client_id),line('设备 ID',cfg.device_id)])]),
          h('div',{class:'gyc-card'},[h('h3','上传监控说明'),h('p','开启后在 MoviePilot 系统日志中搜索“【光鸭云盘助手】【上传】”。'),h('div',{class:'gyc-help'},[h('div',{class:'gyc-tip'},'上传期间每 5% 输出一次进度，并显示已上传大小和平均速度。'),h('div',{class:'gyc-tip'},'上传结束会记录 task_id、fileId、耗时以及最终确认结果。'),h('div',{class:'gyc-tip'},'即使 task 回执缺少 fileId，只要目标目录确认同名同大小文件存在，也会按成功返回给 MoviePilot。'),h('div',{class:'gyc-tip'},'日常使用建议关闭进度监控，减少日志量。')])])
        ])
      ]),message.value?h('div',{class:`gyc-msg ${messageType.value==='error'?'error':''}`},message.value):null]),
      h('footer',{class:'gyc-footer'},[h('span',loading.value?'正在读取配置…':'光鸭云盘助手 · 设置'),h('span','MoviePilot Vue Federation')])
    ])]);
  }
});
