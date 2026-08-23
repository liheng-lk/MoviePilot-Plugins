import AssistantPage from './__federation_expose_AssistantPage-dev.js';
import { importShared } from './__federation_fn_import-054b33c3.js';

const { defineComponent, h, onMounted, onUpdated, nextTick } = await importShared('vue');

export default defineComponent({
  name: 'GuangyaCloudAssistant216',
  props: {
    initialConfig: { type: Object, default: () => ({}) },
    api: { type: Object, default: () => ({}) },
  },
  emits: ['close', 'switch'],
  setup(props, { emit }) {
    const syncVersion = async () => {
      await nextTick();
      document.querySelectorAll('.gy-version').forEach((el) => {
        if (el.textContent !== 'v2.2.16') el.textContent = 'v2.2.16';
      });
    };
    onMounted(syncVersion);
    onUpdated(syncVersion);
    return () => h(AssistantPage, {
      initialConfig: props.initialConfig,
      api: props.api,
      onClose: () => emit('close'),
      onSwitch: () => emit('switch'),
    });
  },
});
