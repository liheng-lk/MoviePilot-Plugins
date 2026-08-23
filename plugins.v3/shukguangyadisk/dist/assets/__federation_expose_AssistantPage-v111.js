import { importShared } from './__federation_fn_import-054b33c3.js';

const { defineComponent, h, ref, shallowRef, onMounted, onErrorCaptured } = await importShared('vue');

export default defineComponent({
  name: 'GuangyaCloudAssistantV111',
  props: {
    initialConfig: { type: Object, default: () => ({}) },
    api: { type: Object, default: () => ({}) },
  },
  emits: ['close', 'switch'],
  setup(props, { emit }) {
    const InnerPage = shallowRef(null);
    const loading = ref(true);
    const error = ref('');

    const load = async () => {
      loading.value = true;
      error.value = '';
      InnerPage.value = null;
      try {
        const mod = await import('./__federation_expose_AssistantPage-dev.js?v=1.1.1');
        InnerPage.value = mod.default;
      } catch (err) {
        console.error('[光鸭云盘助手] Page chunk load failed', err);
        error.value = err?.message || String(err || '未知错误');
      } finally {
        loading.value = false;
      }
    };

    onMounted(load);
    onErrorCaptured((err) => {
      console.error('[光鸭云盘助手] Page runtime error', err);
      error.value = err?.message || String(err || '页面运行异常');
      InnerPage.value = null;
      loading.value = false;
      return false;
    });

    return () => {
      if (InnerPage.value) {
        return h(InnerPage.value, {
          initialConfig: props.initialConfig,
          api: props.api,
          onClose: () => emit('close'),
          onSwitch: () => emit('switch'),
        });
      }

      const boxStyle = {
        width: '100%', minHeight: '280px', padding: '28px', boxSizing: 'border-box',
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        gap: '12px', color: 'rgb(var(--v-theme-on-surface))'
      };
      const btnStyle = {
        height: '36px', padding: '0 16px', borderRadius: '9px', cursor: 'pointer',
        border: '1px solid rgba(var(--v-theme-on-surface),.14)', background: 'rgb(var(--v-theme-surface))',
        color: 'inherit'
      };
      if (loading.value) {
        return h('div', { style: boxStyle }, [h('strong', '光鸭云盘助手'), h('span', '正在加载插件界面…')]);
      }
      return h('div', { style: boxStyle }, [
        h('strong', { style: { color: '#ef4444', fontSize: '16px' } }, '插件界面加载失败'),
        h('div', { style: { maxWidth: '760px', fontSize: '12px', opacity: '.72', wordBreak: 'break-all', textAlign: 'center' } }, error.value || '未知错误'),
        h('button', { style: btnStyle, onClick: load }, '重新加载'),
        h('div', { style: { fontSize: '10px', opacity: '.45' } }, '光鸭云盘助手 v1.1.1 · 前端故障隔离模式'),
      ]);
    };
  },
});
