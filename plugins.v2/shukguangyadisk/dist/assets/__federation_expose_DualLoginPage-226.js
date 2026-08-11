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
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`HTTP ${response.status}${text ? `: ${text.slice(0, 180)}` : ''}`);
  }
  return response.json();
}

const fieldStyle = {
  width: '100%', boxSizing: 'border-box', minHeight: '42px', padding: '9px 12px', borderRadius: '8px',
  border: '1px solid rgba(var(--v-theme-on-surface),0.16)', background: 'rgb(var(--v-theme-surface))',
  color: 'rgb(var(--v-theme-on-surface))', fontSize: '14px', outline: 'none',
};

const DualLoginPage = defineComponent({
  name: 'DualLoginPage226',
  props: { initialConfig: { type: Object, default: () => ({}) }, api: { type: Object, default: () => ({}) } },
  emits: ['close', 'switch'],
  setup(props, { emit }) {
    const mode = ref('qr'); const phone = ref(''); const code = ref(''); const verificationId = ref('');
    const sending = ref(false); const logging = ref(false); const message = ref(''); const messageType = ref('');
    const clearMessage = () => { message.value = ''; messageType.value = ''; };
    const proxiedApi = createApiProxy(props.api);

    const sendCode = async () => {
      if (!phone.value.trim()) { messageType.value = 'error'; message.value = '请输入手机号'; return; }
      sending.value = true; clearMessage();
      try {
        const result = await apiPost(props, '/login/sms/send', { phone_number: phone.value.trim() });
        if (!result?.success) throw new Error(result?.message || '发送验证码失败');
        verificationId.value = result.verification_id || ''; messageType.value = 'success'; message.value = '验证码已发送，请查收短信';
      } catch (err) { messageType.value = 'error'; message.value = err?.message || '发送验证码失败'; }
      finally { sending.value = false; }
    };

    const login = async () => {
      if (!phone.value.trim() || !code.value.trim()) { messageType.value = 'error'; message.value = '请输入手机号和验证码'; return; }
      logging.value = true; clearMessage();
      try {
        const result = await apiPost(props, '/login/sms/verify', { phone_number: phone.value.trim(), verification_code: code.value.trim(), verification_id: verificationId.value });
        if (!result?.success) throw new Error(result?.message || '短信登录失败');
        messageType.value = 'success'; message.value = '登录成功'; setTimeout(() => { mode.value = 'qr'; }, 700);
      } catch (err) { messageType.value = 'error'; message.value = err?.message || '短信登录失败'; }
      finally { logging.value = false; }
    };

    const row = (label, control) => h('div', { style: { display: 'grid', gridTemplateColumns: '96px minmax(0,1fr)', gap: '12px', alignItems: 'center', marginBottom: '12px' } }, [
      h('div', { style: { fontSize: '14px' } }, label), control,
    ]);

    const selector = h('div', { style: { margin: '12px 16px 14px', padding: '14px 16px', borderRadius: '12px', border: '1px solid rgba(var(--v-theme-on-surface),0.10)', background: 'rgb(var(--v-theme-surface))' } }, [
      row('登录方式', h('select', { value: mode.value, onChange: e => { mode.value = e.target.value; clearMessage(); }, style: fieldStyle }, [
        h('option', { value: 'qr' }, '扫码登录'), h('option', { value: 'sms' }, '短信验证'),
      ])),
      h('div', { style: { marginLeft: '108px', marginTop: '-4px', fontSize: '12px', lineHeight: '1.6', opacity: '.62' } }, mode.value === 'qr' ? '使用光鸭云盘 App 扫描二维码并确认授权。' : '使用账号绑定手机号接收验证码完成登录。'),
    ]);

    const smsForm = () => h('div', { style: { margin: '0 16px 16px', padding: '16px', borderRadius: '12px', border: '1px solid rgba(var(--v-theme-on-surface),0.10)', background: 'rgb(var(--v-theme-surface))' } }, [
      h('div', { style: { fontSize: '16px', fontWeight: '650', marginBottom: '14px' } }, '短信验证'),
      row('手机号', h('input', { value: phone.value, onInput: e => { phone.value = e.target.value; }, inputmode: 'tel', autocomplete: 'tel', placeholder: '请输入绑定手机号', style: fieldStyle })),
      row('验证码', h('div', { style: { display: 'flex', gap: '8px', minWidth: '0' } }, [
        h('input', { value: code.value, onInput: e => { code.value = e.target.value; }, inputmode: 'numeric', autocomplete: 'one-time-code', placeholder: '请输入验证码', style: { ...fieldStyle, flex: '1', minWidth: '0' } }),
        h('button', { disabled: sending.value, onClick: sendCode, style: { minWidth: '104px', padding: '0 12px', borderRadius: '8px', border: '1px solid rgba(var(--v-theme-primary),0.28)', background: 'rgba(var(--v-theme-primary),0.08)', color: 'rgb(var(--v-theme-primary))', fontSize: '13px' } }, sending.value ? '发送中...' : '获取验证码'),
      ])),
      message.value ? h('div', { style: { margin: '2px 0 10px 108px', fontSize: '13px', color: messageType.value === 'error' ? '#ef4444' : '#10b981' } }, message.value) : null,
      h('div', { style: { display: 'flex', justifyContent: 'flex-end' } }, [
        h('button', { disabled: logging.value, onClick: login, style: { minWidth: '112px', minHeight: '40px', padding: '8px 18px', border: '0', borderRadius: '8px', fontWeight: '600', background: 'rgb(var(--v-theme-primary))', color: 'rgb(var(--v-theme-on-primary))' } }, logging.value ? '登录中...' : '登录'),
      ]),
    ]);

    return () => h('div', { style: { width: '100%', boxSizing: 'border-box' } }, [
      selector,
      mode.value === 'qr' ? h(OldPage, { initialConfig: props.initialConfig, api: proxiedApi, onClose: () => emit('close'), onSwitch: () => emit('switch') }) : smsForm(),
    ]);
  },
});

export default DualLoginPage;
