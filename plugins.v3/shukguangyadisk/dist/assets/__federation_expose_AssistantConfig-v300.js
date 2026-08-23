import { importShared } from './__federation_fn_import-054b33c3.js';

const { defineComponent, h, shallowRef, ref, onMounted, onErrorCaptured } = await importShared('vue');

export default defineComponent({
  name: 'GuangyaCloudAssistantConfigV300',
  props: {
    initialConfig: { type: Object, default: () => ({}) },
    api: { type: Object, default: null },
  },
  emits: ['close', 'switch'],
  setup(props, { emit }) {
    const InnerConfig = shallowRef(null);
    const loading = ref(true);
    const error = ref('');
    const resolveApi = () => props.api || globalThis.MoviePilotAPI || null;

    const load = async () => {
      loading.value = true;
      error.value = '';
      InnerConfig.value = null;
      try {
        if (!resolveApi()) throw new Error('MoviePilot V3 API client unavailable');
        const mod = await import('./__federation_expose_AssistantConfig-dev.js?v=3.0.0');
        InnerConfig.value = mod.default;
      } catch (err) {
        console.error('[光鸭云盘助手 V3] Config chunk load failed', err);
        error.value = err?.message || String(err || '未知错误');
      } finally {
        loading.value = false;
      }
    };

    onMounted(load);
    onErrorCaptured((err) => {
      console.error('[光鸭云盘助手 V3] Config runtime error', err);
      error.value = err?.message || String(err || '配置页运行异常');
      InnerConfig.value = null;
      loading.value = false;
      return false;
    });

    return () => {
      if (InnerConfig.value) {
        return h(InnerConfig.value, {
          initialConfig: props.initialConfig,
          api: resolveApi(),
          onClose: () => emit('close'),
          onSwitch: () => emit('switch'),
        });
      }
      const style = {
        width: '100%', minHeight: '220px', padding: '24px', boxSizing: 'border-box',
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        gap: '10px', color: 'rgb(var(--v-theme-on-surface))'
      };
      if (loading.value) return h('div', { style }, [h('strong', '光鸭云盘助手'), h('span', '正在加载 V3 设置页…')]);
      return h('div', { style }, [
        h('strong', { style: { color: '#ef4444' } }, '配置页加载失败'),
        h('div', { style: { fontSize: '12px', opacity: '.72', wordBreak: 'break-all' } }, error.value || '未知错误'),
        h('button', { onClick: load }, '重新加载'),
      ]);
    };
  },
});
