import OldPage from './__federation_expose_Page-3595592a.js';
import { importShared } from './__federation_fn_import-054b33c3.js';

const { defineComponent, h, ref } = await importShared('vue');
const PLUGIN_ID = 'ShukGuangYaDisk';

function rewritePluginPath(path) {
  return String(path || '').replace(/^plugin\/GuangyaDisk/, `plugin/${PLUGIN_ID}`);
}

function createApiProxy(api) {
  if (!api) return api;
  return {
    ...api,
    get: api.get ? ((path, options) => api.get(rewritePluginPath(path), options)) : undefined,
    post: api.post ? ((path, body, options) => api.post(rewritePluginPath(path), body, options)) : undefined,
    put: api.put ? ((path, body, options) => api.put(rewritePluginPath(path), body, options)) : undefined,
    delete: api.delete ? ((path, options) => api.delete(rewritePluginPath(path), options)) : undefined,
  };
}

async function apiPost(props, path, body) {
  const apiPath = `plugin/${PLUGIN_ID}${path}`;
  if (props.api?.post) return props.api.post(apiPath, body || {});
  const response = await fetch(`/api/v1/plugin/${PLUGIN_ID}${path}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

const DualLoginPage = defineComponent({
  name: 'DualLoginPage213',
  props: { initialConfig: { type: Object, default: () => ({}) }, api: { type: Object, default: () => ({}) } },
  emits: ['close', 'switch'],
  setup(props, { emit }) {
    const mode = ref('qr');
    const phone = ref('');
    const code = ref('');
    const verificationId = ref('');
    const sending = ref(false);
    const logging = ref(false);
    const message = ref('');
    const messageType = ref('');
    const proxiedApi = createApiProxy(props.api);

    const clearMessage = () => { message.value = ''; messageType.value = ''; };

    const sendCode = async () => {
      if (!phone.value.trim()) { messageType.value = 'error'; message.value = '请输入手机号'; return; }
      sending.value = true; clearMessage();
      try {
        const result = await apiPost(props, '/login/sms/send', { phone_number: phone.value.trim() });
        if (!result?.success) throw new Error(result?.message || '发送验证码失败');
        verificationId.value = result.verification_id || '';
        messageType.value = 'success'; message.value = '验证码已发送';
      } catch (err) { messageType.value = 'error'; message.value = err?.message || '发送验证码失败'; }
      finally { sending.value = false; }
    };

    const login = async () => {
      if (!phone.value.trim() || !code.value.trim()) { messageType.value = 'error'; message.value = '请输入手机号和验证码'; return; }
      logging.value = true; clearMessage();
      try {
        const result = await apiPost(props, '/login/sms/verify', {
          phone_number: phone.value.trim(), verification_code: code.value.trim(), verification_id: verificationId.value,
        });
        if (!result?.success) throw new Error(result?.message || '短信登录失败');
        messageType.value = 'success'; message.value = '登录成功';
      } catch (err) { messageType.value = 'error'; message.value = err?.message || '短信登录失败'; }
      finally { logging.value = false; }
    };

    const styles = `
      .gy-login-shell{width:100%;max-width:720px;margin:0 auto;box-sizing:border-box;overflow:hidden}
      .gy-login-mode{margin:0 14px 12px;padding:14px 16px;border:1px solid rgba(var(--v-theme-on-surface),.09);border-radius:14px;background:rgb(var(--v-theme-surface));box-shadow:0 5px 18px rgba(0,0,0,.035)}
      .gy-login-mode-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:10px}
      .gy-login-mode-title{font-size:14px;font-weight:700}.gy-login-mode-sub{font-size:11.5px;color:rgba(var(--v-theme-on-surface),.56);margin-top:2px}
      .gy-login-select{width:210px;max-width:45%;min-height:38px;padding:7px 10px;border-radius:9px;border:1px solid rgba(var(--v-theme-on-surface),.14);background:rgb(var(--v-theme-surface));color:rgb(var(--v-theme-on-surface));font-size:13px;outline:none}
      .gy-sms-card{margin:0 14px 16px;padding:16px;border:1px solid rgba(var(--v-theme-on-surface),.09);border-radius:14px;background:rgb(var(--v-theme-surface));box-shadow:0 5px 18px rgba(0,0,0,.035)}
      .gy-sms-title{font-size:14px;font-weight:700;margin-bottom:14px}.gy-sms-row{display:grid;grid-template-columns:82px minmax(0,1fr);gap:10px;align-items:center;margin-bottom:12px}.gy-sms-label{font-size:12.5px;color:rgba(var(--v-theme-on-surface),.68)}
      .gy-sms-input{width:100%;min-width:0;min-height:40px;padding:8px 11px;border-radius:9px;border:1px solid rgba(var(--v-theme-on-surface),.14);background:rgb(var(--v-theme-surface));color:rgb(var(--v-theme-on-surface));font-size:13px;outline:none;box-sizing:border-box}
      .gy-sms-code{display:flex;gap:8px;min-width:0}.gy-sms-btn{min-height:40px;padding:0 13px;border-radius:9px;border:1px solid rgba(var(--v-theme-primary),.22);background:rgba(var(--v-theme-primary),.08);color:rgb(var(--v-theme-primary));font-size:12.5px;white-space:nowrap}.gy-sms-login{min-width:110px;background:rgb(var(--v-theme-primary));color:rgb(var(--v-theme-on-primary));border:0;font-weight:650}
      .gy-sms-msg{margin:-2px 0 10px 92px;font-size:12px}.gy-sms-actions{display:flex;justify-content:flex-end}
      @media(max-width:640px){.gy-login-shell{max-width:100%}.gy-login-mode{margin:0 10px 10px;padding:12px}.gy-login-mode-head{align-items:flex-start;flex-direction:column;gap:8px}.gy-login-select{width:100%;max-width:100%}.gy-sms-card{margin:0 10px 14px;padding:13px}.gy-sms-row{grid-template-columns:1fr;gap:6px}.gy-sms-code{flex-direction:column}.gy-sms-btn{width:100%}.gy-sms-msg{margin:0 0 10px}.gy-sms-login{width:100%}}
    `;

    const smsForm = () => h('div', { class: 'gy-sms-card' }, [
      h('div', { class: 'gy-sms-title' }, '短信验证'),
      h('div', { class: 'gy-sms-row' }, [
        h('div', { class: 'gy-sms-label' }, '手机号'),
        h('input', { class: 'gy-sms-input', value: phone.value, onInput: e => { phone.value = e.target.value; }, inputmode: 'tel', autocomplete: 'tel', placeholder: '请输入绑定手机号' }),
      ]),
      h('div', { class: 'gy-sms-row' }, [
        h('div', { class: 'gy-sms-label' }, '验证码'),
        h('div', { class: 'gy-sms-code' }, [
          h('input', { class: 'gy-sms-input', value: code.value, onInput: e => { code.value = e.target.value; }, inputmode: 'numeric', autocomplete: 'one-time-code', placeholder: '请输入验证码' }),
          h('button', { class: 'gy-sms-btn', disabled: sending.value, onClick: sendCode }, sending.value ? '发送中...' : '获取验证码'),
        ]),
      ]),
      message.value ? h('div', { class: 'gy-sms-msg', style: { color: messageType.value === 'error' ? '#ef4444' : '#10b981' } }, message.value) : null,
      h('div', { class: 'gy-sms-actions' }, [
        h('button', { class: 'gy-sms-btn gy-sms-login', disabled: logging.value, onClick: login }, logging.value ? '登录中...' : '登录'),
      ]),
    ]);

    return () => h('div', { class: 'gy-login-shell' }, [
      h('style', null, styles),
      h('div', { class: 'gy-login-mode' }, [
        h('div', { class: 'gy-login-mode-head' }, [
          h('div', null, [
            h('div', { class: 'gy-login-mode-title' }, '登录方式'),
            h('div', { class: 'gy-login-mode-sub' }, mode.value === 'qr' ? '使用光鸭云盘 App 扫码并确认授权' : '使用绑定手机号接收验证码登录'),
          ]),
          h('select', { class: 'gy-login-select', value: mode.value, onChange: e => { mode.value = e.target.value; clearMessage(); } }, [
            h('option', { value: 'qr' }, '扫码登录'),
            h('option', { value: 'sms' }, '短信登录'),
          ]),
        ]),
      ]),
      mode.value === 'qr'
        ? h(OldPage, { initialConfig: props.initialConfig, api: proxiedApi, onClose: () => emit('close'), onSwitch: () => emit('switch') })
        : smsForm(),
    ]);
  },
});

export default DualLoginPage;
