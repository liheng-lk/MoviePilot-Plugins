import OldPage from './__federation_expose_Page-3595592a.js';
import { importShared } from './__federation_fn_import-054b33c3.js';

const { defineComponent, h, ref, reactive, computed, onMounted, onBeforeUnmount, nextTick } = await importShared('vue');
const PLUGIN_ID = 'ShukGuangYaDisk';

const rewrite = p => String(p || '').replace(/^plugin\/GuangyaDisk/, `plugin/${PLUGIN_ID}`);
function apiProxy(api) {
  if (!api) return api;
  return {
    ...api,
    get: api.get ? ((p,o) => api.get(rewrite(p),o)) : undefined,
    post: api.post ? ((p,b,o) => api.post(rewrite(p),b,o)) : undefined,
    put: api.put ? ((p,b,o) => api.put(rewrite(p),b,o)) : undefined,
    delete: api.delete ? ((p,o) => api.delete(rewrite(p),o)) : undefined,
  };
}
async function getApi(props,path){
  const p=`plugin/${PLUGIN_ID}${path}`;
  if(props.api?.get) return props.api.get(p);
  const r=await fetch(`/api/v1/plugin/${PLUGIN_ID}${path}`);
  if(!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
async function postApi(props,path,body={}){
  const p=`plugin/${PLUGIN_ID}${path}`;
  if(props.api?.post) return props.api.post(p,body);
  const r=await fetch(`/api/v1/plugin/${PLUGIN_ID}${path}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  if(!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
function fmtSize(value){
  let n=Number(value||0); if(!n) return '0 B';
  const u=['B','KB','MB','GB','TB','PB']; let i=0;
  while(n>=1024&&i<u.length-1){n/=1024;i++;}
  return `${n.toFixed(n>=100||i===0?0:n>=10?1:2)} ${u[i]}`;
}
function maskPhone(v){const s=String(v||'');return s.length>=7?`${s.slice(0,3)}****${s.slice(-4)}`:(s||'-');}

const css=`
.gy-assistant{width:100%;margin:0;padding:0;box-sizing:border-box;color:rgb(var(--v-theme-on-surface));font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
.gy-assistant *{box-sizing:border-box}.gy-shell{width:100%;margin:0;background:rgb(var(--v-theme-surface));border-radius:14px;overflow:hidden}
.gy-header{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:15px 18px;border-bottom:1px solid rgba(var(--v-theme-on-surface),.07)}
.gy-brand{display:flex;align-items:center;gap:11px;min-width:0}.gy-logo{width:40px;height:40px;border-radius:11px;display:grid;place-items:center;background:rgba(var(--v-theme-primary),.11);color:rgb(var(--v-theme-primary));font-size:21px;flex:none}.gy-title{font-size:17px;font-weight:760;line-height:1.15}.gy-version{margin-left:7px;padding:2px 7px;border-radius:999px;background:rgba(var(--v-theme-primary),.1);color:rgb(var(--v-theme-primary));font-size:9px}.gy-sub{margin-top:4px;font-size:10.5px;color:rgba(var(--v-theme-on-surface),.48)}
.gy-actions{display:flex;gap:7px;flex:none}.gy-iconbtn{width:34px;height:34px;border:1px solid rgba(var(--v-theme-on-surface),.1);border-radius:9px;background:transparent;color:inherit;cursor:pointer}
.gy-body{padding:14px 18px 12px}.gy-stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:12px}.gy-stat{padding:10px 12px;border:1px solid rgba(var(--v-theme-on-surface),.075);border-radius:10px;background:rgba(var(--v-theme-on-surface),.01)}.gy-stat-k{font-size:9.5px;color:rgba(var(--v-theme-on-surface),.46);margin-bottom:4px}.gy-stat-v{font-size:13px;font-weight:730;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.gy-ok{color:#10b981}.gy-warn{color:#f59e0b}.gy-pri{color:rgb(var(--v-theme-primary))}
.gy-main{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(320px,.6fr);gap:12px;align-items:start}.gy-side{display:grid;gap:10px}.gy-card{border:1px solid rgba(var(--v-theme-on-surface),.075);border-radius:11px;background:rgba(var(--v-theme-on-surface),.007);padding:13px}.gy-card-title{font-size:13px;font-weight:740}.gy-card-sub{font-size:10px;color:rgba(var(--v-theme-on-surface),.48);margin:3px 0 10px}
.gy-select,.gy-input{width:100%;height:37px;border:1px solid rgba(var(--v-theme-on-surface),.12);border-radius:8px;padding:0 10px;background:rgb(var(--v-theme-surface));color:inherit;font-size:11.5px;outline:none}.gy-select{margin-bottom:10px}
.gy-qr{min-height:300px;border:1px dashed rgba(var(--v-theme-on-surface),.13);border-radius:10px;display:flex;flex-direction:column;align-items:center;justify-content:center;background:rgba(var(--v-theme-on-surface),.005);padding:14px}.gy-qr img{width:205px;height:205px;max-width:56vw;max-height:56vw;object-fit:contain;background:#fff;border-radius:8px;padding:4px}.gy-qr-placeholder{font-size:11px;color:rgba(var(--v-theme-on-surface),.45)}.gy-hint{margin-top:9px;font-size:10px;color:rgba(var(--v-theme-on-surface),.5);text-align:center}.gy-buttons{display:flex;gap:8px;justify-content:center;margin-top:9px}
.gy-btn{height:34px;padding:0 12px;border-radius:8px;border:1px solid rgba(var(--v-theme-on-surface),.12);background:transparent;color:inherit;font-size:11px;cursor:pointer}.gy-btn.primary{background:rgb(var(--v-theme-primary));color:rgb(var(--v-theme-on-primary));border-color:transparent}.gy-btn.danger{color:#ef4444;border-color:rgba(239,68,68,.22)}
.gy-form{display:grid;gap:9px}.gy-field label{display:block;font-size:10px;color:rgba(var(--v-theme-on-surface),.5);margin-bottom:4px}.gy-code{display:grid;grid-template-columns:1fr 100px;gap:8px}.gy-msg{padding:8px 9px;border-radius:8px;background:rgba(16,185,129,.07);color:#10b981;font-size:10.5px}.gy-msg.error{background:rgba(239,68,68,.07);color:#ef4444}
.gy-login-ok{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:12px;min-height:92px}.gy-check{width:46px;height:46px;border-radius:50%;display:grid;place-items:center;background:rgba(16,185,129,.11);color:#10b981;font-size:25px}.gy-login-ok strong{font-size:13px}.gy-login-ok p{margin:3px 0 0;font-size:10px;color:rgba(var(--v-theme-on-surface),.5)}
.gy-info{display:grid;grid-template-columns:1fr 1fr;gap:0 14px}.gy-item{padding:8px 0;border-bottom:1px solid rgba(var(--v-theme-on-surface),.05);min-width:0}.gy-item span{display:block;font-size:9.5px;color:rgba(var(--v-theme-on-surface),.45);margin-bottom:3px}.gy-item b{display:block;font-size:11.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.gy-space-top{display:flex;justify-content:space-between;align-items:end;margin-bottom:8px}.gy-space-top strong{font-size:17px}.gy-space-top span{font-size:10px;color:rgba(var(--v-theme-on-surface),.46)}.gy-bar{height:6px;background:rgba(var(--v-theme-on-surface),.07);border-radius:99px;overflow:hidden;margin-bottom:7px}.gy-bar i{display:block;height:100%;background:rgb(var(--v-theme-primary));border-radius:99px}.gy-space-row{display:flex;justify-content:space-between;line-height:1.75;font-size:10px;color:rgba(var(--v-theme-on-surface),.54)}
.gy-note{padding:9px;border-radius:8px;background:rgba(var(--v-theme-primary),.055);font-size:10px;line-height:1.55;color:rgba(var(--v-theme-on-surface),.58)}.gy-footer{display:flex;justify-content:space-between;gap:10px;padding:8px 18px;border-top:1px solid rgba(var(--v-theme-on-surface),.06);font-size:9px;color:rgba(var(--v-theme-on-surface),.37)}
.gy-engine{position:fixed!important;left:-12000px!important;top:-12000px!important;width:420px!important;height:420px!important;opacity:0!important;pointer-events:none!important;overflow:hidden!important}
@media(max-width:900px){.gy-main{grid-template-columns:1fr}.gy-qr{min-height:260px}}
@media(max-width:640px){.gy-header{padding:12px}.gy-body{padding:10px}.gy-stats{grid-template-columns:1fr 1fr;gap:7px}.gy-info{grid-template-columns:1fr}.gy-title{font-size:15px}.gy-sub{display:none}.gy-logo{width:35px;height:35px}.gy-login-ok{grid-template-columns:auto 1fr}.gy-login-ok .gy-btn{grid-column:1/-1;width:100%}.gy-footer{flex-direction:column;padding:8px 10px}.gy-code{grid-template-columns:1fr}.gy-code .gy-btn{width:100%}}
`;

export default defineComponent({
  name:'GuangyaCloudAssistantDev',
  props:{initialConfig:{type:Object,default:()=>({})},api:{type:Object,default:()=>({})}},
  emits:['close','switch'],
  setup(props,{emit}){
    const mode=ref('qr'), engineKey=ref(1), engineHost=ref(null), qr=ref('');
    const phone=ref(''), code=ref(''), verificationId=ref(''), sending=ref(false), logging=ref(false), refreshing=ref(false), message=ref(''), messageType=ref('');
    const status=reactive({enabled:false,logged_in:false,user_name:'',user_id:'',phone:'',email:'',vip_level:'',total_space:0,used_space:0,free_space:0,file_count:0});
    const proxied=apiProxy(props.api); let timer=null, observer=null;
    const pct=computed(()=>status.total_space?Math.min(100,Math.max(0,Math.round(status.used_space/status.total_space*1000)/10)):0);
    const clearMsg=()=>{message.value='';messageType.value='';};
    async function refresh(){refreshing.value=true;try{const d=await getApi(props,'/config');Object.assign(status,{enabled:Boolean(d?.enabled),logged_in:Boolean(d?.logged_in),user_name:d?.user_name||'',user_id:d?.user_id||'',phone:d?.phone||d?.mobile||'',email:d?.email||'',vip_level:d?.vip_level||'',total_space:Number(d?.total_space||0),used_space:Number(d?.used_space||0),free_space:Number(d?.free_space||0),file_count:Number(d?.file_count||0)});}catch{}finally{refreshing.value=false;}}
    function scanQr(){const root=engineHost.value;if(!root)return;const img=root.querySelector('img.gy-qrcode-image,img[alt*="二维码"],.gy-qrcode-box img,img');if(img?.src&&img.src!==qr.value)qr.value=img.src;}
    function bind(){if(observer)observer.disconnect();if(!engineHost.value)return;observer=new MutationObserver(scanQr);observer.observe(engineHost.value,{subtree:true,childList:true,attributes:true,attributeFilter:['src']});scanQr();}
    async function reloadQr(){qr.value='';engineKey.value+=1;await nextTick();bind();}
    async function sendCode(){if(!phone.value.trim()){messageType.value='error';message.value='请输入手机号';return;}sending.value=true;clearMsg();try{const r=await postApi(props,'/login/sms/send',{phone_number:phone.value.trim()});if(!r?.success)throw new Error(r?.message||'发送失败');verificationId.value=r.verification_id||'';messageType.value='success';message.value='验证码已发送';}catch(e){messageType.value='error';message.value=e?.message||'发送失败';}finally{sending.value=false;}}
    async function smsLogin(){if(!phone.value.trim()||!code.value.trim()){messageType.value='error';message.value='请输入手机号和验证码';return;}logging.value=true;clearMsg();try{const r=await postApi(props,'/login/sms/verify',{phone_number:phone.value.trim(),verification_code:code.value.trim(),verification_id:verificationId.value});if(!r?.success)throw new Error(r?.message||'登录失败');messageType.value='success';message.value='登录成功';await refresh();}catch(e){messageType.value='error';message.value=e?.message||'登录失败';}finally{logging.value=false;}}
    async function logout(){try{await postApi(props,'/login/logout',{});qr.value='';await refresh();await reloadQr();}catch{}}
    onMounted(async()=>{await nextTick();bind();await refresh();timer=setInterval(()=>{refresh();scanQr();},3000);});
    onBeforeUnmount(()=>{if(timer)clearInterval(timer);if(observer)observer.disconnect();});
    const info=(k,v)=>h('div',{class:'gy-item'},[h('span',k),h('b',v||'-')]);
    const loginContent=()=>status.logged_in?h('div',{class:'gy-login-ok'},[
      h('div',{class:'gy-check'},'✓'),h('div',[h('strong','已登录'),h('p','光鸭云盘授权有效，目录浏览与整理上传可直接使用。')]),h('button',{class:'gy-btn danger',onClick:logout},'退出登录')
    ]):h('div',[
      h('select',{class:'gy-select',value:mode.value,onChange:e=>{mode.value=e.target.value;clearMsg();}},[h('option',{value:'qr'},'扫码登录'),h('option',{value:'sms'},'短信登录')]),
      mode.value==='qr'?h('div',[h('div',{class:'gy-qr'},[qr.value?h('img',{src:qr.value,alt:'光鸭云盘登录二维码'}):h('div',{class:'gy-qr-placeholder'},'二维码加载中…'),h('div',{class:'gy-hint'},'打开光鸭云盘 App → 扫一扫 → 确认登录'),h('div',{class:'gy-buttons'},[h('button',{class:'gy-btn',onClick:reloadQr},'刷新二维码')])]),h('div',{class:'gy-note',style:{marginTop:'9px'}},'扫码确认后页面会自动刷新账号与空间信息。')]):h('div',{class:'gy-form'},[
        h('div',{class:'gy-field'},[h('label','手机号'),h('input',{class:'gy-input',value:phone.value,onInput:e=>phone.value=e.target.value,inputmode:'tel',placeholder:'请输入绑定手机号'})]),
        h('div',{class:'gy-field'},[h('label','验证码'),h('div',{class:'gy-code'},[h('input',{class:'gy-input',value:code.value,onInput:e=>code.value=e.target.value,inputmode:'numeric',placeholder:'请输入验证码'}),h('button',{class:'gy-btn',disabled:sending.value,onClick:sendCode},sending.value?'发送中…':'获取验证码')])]),
        message.value?h('div',{class:`gy-msg ${messageType.value==='error'?'error':''}`},message.value):null,
        h('button',{class:'gy-btn primary',disabled:logging.value,onClick:smsLogin},logging.value?'登录中…':'登录')
      ])
    ]);
    return()=>h('div',{class:'gy-assistant'},[h('style',css),h('div',{class:'gy-shell'},[
      h('header',{class:'gy-header'},[h('div',{class:'gy-brand'},[h('div',{class:'gy-logo'},'☁'),h('div',[h('div',{class:'gy-title'},['光鸭云盘助手',h('span',{class:'gy-version'},'v2.2.15')]),h('div',{class:'gy-sub'},'MoviePilot 光鸭云盘存储插件')])]),h('div',{class:'gy-actions'},[h('button',{class:'gy-iconbtn',title:'刷新状态',onClick:refresh},refreshing.value?'◔':'↻'),h('button',{class:'gy-iconbtn',title:'设置',onClick:()=>emit('switch')},'⚙'),h('button',{class:'gy-iconbtn',title:'关闭',onClick:()=>emit('close')},'×')])]),
      h('main',{class:'gy-body'},[h('section',{class:'gy-stats'},[
        h('div',{class:'gy-stat'},[h('div',{class:'gy-stat-k'},'登录状态'),h('div',{class:`gy-stat-v ${status.logged_in?'gy-ok':'gy-warn'}`},status.logged_in?'在线':'离线')]),
        h('div',{class:'gy-stat'},[h('div',{class:'gy-stat-k'},'插件状态'),h('div',{class:`gy-stat-v ${status.enabled?'gy-ok':'gy-warn'}`},status.enabled?'已启用':'未启用')]),
        h('div',{class:'gy-stat'},[h('div',{class:'gy-stat-k'},'空间使用'),h('div',{class:'gy-stat-v gy-pri'},fmtSize(status.used_space))]),
        h('div',{class:'gy-stat'},[h('div',{class:'gy-stat-k'},'授权方式'),h('div',{class:'gy-stat-v gy-pri'},status.logged_in?'已授权':mode.value==='qr'?'扫码登录':'短信登录')])
      ]),h('section',{class:'gy-main'},[
        h('div',{class:'gy-card'},[h('div',{class:'gy-card-title'},status.logged_in?'授权状态':'登录方式'),h('div',{class:'gy-card-sub'},status.logged_in?'当前账号已完成授权':'选择一种方式完成光鸭云盘账号授权'),loginContent()]),
        h('aside',{class:'gy-side'},[
          h('div',{class:'gy-card'},[h('div',{class:'gy-card-title'},'用户信息'),h('div',{class:'gy-card-sub'},status.logged_in?'当前授权账号':'登录后自动显示账号信息'),h('div',{class:'gy-info'},[info('用户名',status.user_name),info('用户 ID',status.user_id),info('手机号',maskPhone(status.phone)),info('会员信息',status.vip_level||'普通用户')])]),
          h('div',{class:'gy-card'},[h('div',{class:'gy-card-title'},'空间使用'),h('div',{class:'gy-space-top'},[h('strong',`${fmtSize(status.used_space)} / ${fmtSize(status.total_space)}`),h('span',`${pct.value}%`)]),h('div',{class:'gy-bar'},[h('i',{style:{width:`${pct.value}%`}})]),h('div',{class:'gy-space-row'},[h('span','已用空间'),h('span',fmtSize(status.used_space))]),h('div',{class:'gy-space-row'},[h('span','剩余空间'),h('span',fmtSize(status.free_space))]),h('div',{class:'gy-space-row'},[h('span','文件数量'),h('span',String(status.file_count||0))])])
        ])
      ])]),h('footer',{class:'gy-footer'},[h('span','光鸭云盘助手 · MoviePilot 存储插件'),h('span','扫码 / 短信 · 目录浏览 · 整理上传')])
    ]),h('div',{class:'gy-engine',ref:engineHost},[h(OldPage,{key:engineKey.value,initialConfig:props.initialConfig,api:proxied,onClose:()=>{},onSwitch:()=>{}})])]);
  }
});
