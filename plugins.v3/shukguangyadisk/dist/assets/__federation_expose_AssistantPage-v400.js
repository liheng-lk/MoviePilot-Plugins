import AccountPage from './__federation_expose_AssistantPage-dev.js?v=4.0.0-alpha1';
import { importShared } from './__federation_fn_import-054b33c3.js';

const { defineComponent, h, ref, computed, onMounted, onUnmounted } = await importShared('vue');
const PLUGIN_ID = 'ShukGuangYaDisk';

async function getApi(props, path) {
  const endpoint = `plugin/${PLUGIN_ID}${path}`;
  if (props.api?.get) return props.api.get(endpoint);
  const response = await fetch(`/api/v1/plugin/${PLUGIN_ID}${path}`);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

async function postApi(props, path, body = {}) {
  const endpoint = `plugin/${PLUGIN_ID}${path}`;
  if (props.api?.post) return props.api.post(endpoint, body);
  const response = await fetch(`/api/v1/plugin/${PLUGIN_ID}${path}`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function fmtTime(value) {
  const time = Number(value || 0);
  if (!time) return '-';
  try { return new Date(time * 1000).toLocaleString(); } catch { return '-'; }
}

function stateText(state) {
  return ({
    STABILIZING: '等待稳定',
    READY: '等待执行',
    RUNNING: '正在整理',
    RETRY: '等待重试',
    VERIFYING: '等待 MP 历史确认',
    BLOCKED: '安全阻断',
    COMPLETED: '已完成',
  })[String(state || '').toUpperCase()] || String(state || '-');
}

const css = `
.gyv4{width:100%;color:rgb(var(--v-theme-on-surface));font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}.gyv4 *{box-sizing:border-box}
.gyv4-tabs{display:flex;gap:7px;padding:10px 14px;border:1px solid rgba(var(--v-theme-on-surface),.08);border-radius:12px;margin-bottom:10px;background:rgb(var(--v-theme-surface))}
.gyv4-tab{height:34px;padding:0 14px;border-radius:9px;border:1px solid rgba(var(--v-theme-on-surface),.1);background:transparent;color:inherit;cursor:pointer;font-size:12px}.gyv4-tab.active{background:rgb(var(--v-theme-primary));border-color:transparent;color:rgb(var(--v-theme-on-primary));font-weight:700}
.gyv4-shell{background:rgb(var(--v-theme-surface));border:1px solid rgba(var(--v-theme-on-surface),.08);border-radius:14px;overflow:hidden}.gyv4-head{padding:16px 18px;border-bottom:1px solid rgba(var(--v-theme-on-surface),.07);display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.gyv4-title{font-size:17px;font-weight:760}.gyv4-sub{font-size:10.5px;opacity:.58;margin-top:4px;line-height:1.6}.gyv4-badge{font-size:10px;padding:5px 8px;border-radius:999px;background:rgba(var(--v-theme-primary),.08);color:rgb(var(--v-theme-primary));white-space:nowrap}
.gyv4-body{padding:14px 18px 18px;display:grid;gap:12px}.gyv4-card{border:1px solid rgba(var(--v-theme-on-surface),.075);border-radius:11px;padding:13px;background:rgba(var(--v-theme-on-surface),.008)}.gyv4-card-title{font-size:13px;font-weight:740;margin-bottom:4px}.gyv4-card-sub{font-size:10px;opacity:.55;line-height:1.6;margin-bottom:10px}
.gyv4-grid{display:grid;grid-template-columns:1.6fr .8fr .8fr;gap:10px}.gyv4-field label{display:block;font-size:10px;opacity:.55;margin-bottom:4px}.gyv4-input{width:100%;height:38px;border:1px solid rgba(var(--v-theme-on-surface),.13);border-radius:8px;padding:0 10px;background:rgb(var(--v-theme-surface));color:inherit;font-size:11.5px}.gyv4-path{display:grid;grid-template-columns:1fr auto;gap:7px}
.gyv4-actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.gyv4-btn{height:36px;padding:0 13px;border-radius:8px;border:1px solid rgba(var(--v-theme-on-surface),.13);background:transparent;color:inherit;cursor:pointer;font-size:11px}.gyv4-btn.primary{background:rgb(var(--v-theme-primary));color:rgb(var(--v-theme-on-primary));border-color:transparent}.gyv4-btn.warn{border-color:rgba(245,158,11,.45);color:#f59e0b}.gyv4-btn:disabled{opacity:.4;cursor:not-allowed}.gyv4-switch{display:flex;align-items:center;gap:7px;font-size:11px}
.gyv4-stats{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:7px}.gyv4-stat{padding:9px;border:1px solid rgba(var(--v-theme-on-surface),.07);border-radius:8px;min-width:0}.gyv4-stat span{display:block;font-size:9px;opacity:.48}.gyv4-stat b{display:block;font-size:14px;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.gyv4-status{margin-top:9px;padding:9px 10px;border-radius:8px;background:rgba(var(--v-theme-primary),.045);font-size:10px;line-height:1.65;word-break:break-all}
.gyv4-msg{padding:9px 10px;border-radius:8px;font-size:10.5px;background:rgba(16,185,129,.08);color:#10b981;white-space:pre-wrap}.gyv4-msg.warn{background:rgba(245,158,11,.08);color:#f59e0b}.gyv4-msg.error{background:rgba(239,68,68,.08);color:#ef4444}
.gyv4-browser{border:1px solid rgba(var(--v-theme-on-surface),.1);border-radius:10px;padding:10px;margin-top:9px}.gyv4-browser-head{display:flex;gap:7px;align-items:center;margin-bottom:8px}.gyv4-browser-path{flex:1;font-size:10px;word-break:break-all;opacity:.65}.gyv4-folders{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;max-height:220px;overflow:auto}.gyv4-folder{padding:8px;border:1px solid rgba(var(--v-theme-on-surface),.08);border-radius:8px;cursor:pointer;font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;background:transparent;color:inherit;text-align:left}
.gyv4-history{display:grid;gap:6px;max-height:360px;overflow:auto}.gyv4-row{display:grid;grid-template-columns:150px minmax(180px,1fr) 145px;gap:8px;align-items:center;padding:8px;border:1px solid rgba(var(--v-theme-on-surface),.07);border-radius:8px;font-size:10px}.gyv4-row small{display:block;opacity:.55;word-break:break-all;margin-top:2px}.gyv4-state{padding:3px 7px;border-radius:999px;text-align:center;background:rgba(var(--v-theme-primary),.08)}.gyv4-state.COMPLETED{color:#10b981;background:rgba(16,185,129,.1)}.gyv4-state.BLOCKED{color:#f59e0b;background:rgba(245,158,11,.1)}.gyv4-state.RETRY{color:#3b82f6;background:rgba(59,130,246,.1)}
@media(max-width:1000px){.gyv4-stats{grid-template-columns:repeat(4,minmax(0,1fr))}}@media(max-width:760px){.gyv4-head{display:block}.gyv4-badge{display:inline-block;margin-top:8px}.gyv4-grid{grid-template-columns:1fr}.gyv4-stats{grid-template-columns:repeat(2,minmax(0,1fr))}.gyv4-row{grid-template-columns:1fr}.gyv4-folders{grid-template-columns:1fr 1fr}}
`;

export default defineComponent({
  name: 'GuangYaAssistantV400',
  props: {initialConfig: {type: Object, default: () => ({})}, api: {type: Object, default: null}},
  emits: ['close', 'switch'],
  setup(props, {emit}) {
    const tab = ref('account');
    const enabled = ref(false);
    const monitorPath = ref('/');
    const interval = ref(60);
    const stability = ref(30);
    const batchSize = ref(100);
    const recursive = ref(true);
    const status = ref({});
    const history = ref([]);
    const pending = ref([]);
    const busy = ref('');
    const message = ref('');
    const messageKind = ref('ok');
    const browserOpen = ref(false);
    const browserPath = ref('/');
    const browserFolders = ref([]);
    const browserBusy = ref(false);
    let timer = null;

    const stats = computed(() => status.value?.task_stats || {});
    const gracefulPaused = computed(() => ['paused', 'finishing_current'].includes(status.value?.graceful_stop_state || ''));
    const workerBusy = computed(() => Boolean(status.value?.worker_busy));
    const currentTask = computed(() => status.value?.current_task_path || '-');

    function setMessage(text, kind = 'ok') {
      message.value = text || '';
      messageKind.value = kind;
    }

    function applyConfig(config = {}) {
      enabled.value = Boolean(config.enabled);
      monitorPath.value = config.path || '/';
      interval.value = Number(config.interval || 60);
      stability.value = Number(config.stability ?? 30);
      batchSize.value = Number(config.batch_size || 100);
      recursive.value = config.recursive !== false;
    }

    async function loadConfig(silent = true) {
      try {
        const result = await getApi(props, '/organize/monitor/config');
        if (!result?.success) throw new Error(result?.message || '读取自动整理配置失败');
        applyConfig(result?.data?.config || {});
      } catch (error) {
        if (!silent) setMessage(error?.message || '读取自动整理配置失败', 'error');
      }
    }

    async function loadStatus(silent = true) {
      try {
        const result = await getApi(props, '/organize/monitor/status');
        if (!result?.success) throw new Error(result?.message || '读取运行状态失败');
        status.value = result?.data?.status || {};
        history.value = result?.data?.history || [];
        pending.value = result?.data?.pending_sample || [];
      } catch (error) {
        if (!silent) setMessage(error?.message || '读取运行状态失败', 'error');
      }
    }

    async function save() {
      busy.value = 'save';
      setMessage('');
      try {
        const result = await postApi(props, '/organize/monitor/config', {
          enabled: enabled.value,
          path: monitorPath.value,
          interval: Number(interval.value || 60),
          stability: Number(stability.value || 0),
          batch_size: Number(batchSize.value || 100),
          recursive: recursive.value,
        });
        if (!result?.success) throw new Error(result?.message || '保存失败');
        applyConfig(result?.data?.config || {});
        setMessage(result?.message || '设置已保存');
        await loadStatus(true);
      } catch (error) {
        setMessage(error?.message || '保存自动整理设置失败', 'error');
      } finally {
        busy.value = '';
      }
    }

    async function scan() {
      busy.value = 'scan';
      setMessage('');
      try {
        const result = await postApi(props, '/organize/monitor/scan', {});
        if (!result?.success) throw new Error(result?.message || '扫描失败');
        setMessage(result?.message || '扫描已推进');
        await loadStatus(true);
      } catch (error) {
        setMessage(error?.message || '扫描失败', 'error');
      } finally {
        busy.value = '';
      }
    }

    async function pause() {
      busy.value = 'pause';
      setMessage('');
      try {
        const result = await postApi(props, '/organize/monitor/graceful-stop', {});
        if (!result?.success) throw new Error(result?.message || '暂停失败');
        enabled.value = false;
        setMessage(result?.message || '自动整理已暂停', result?.data?.state === 'finishing_current' ? 'warn' : 'ok');
        await loadStatus(true);
      } catch (error) {
        setMessage(error?.message || '暂停失败', 'error');
      } finally {
        busy.value = '';
      }
    }

    async function unblock() {
      busy.value = 'unblock';
      try {
        const result = await postApi(props, '/organize/monitor/unblock', {});
        if (!result?.success) throw new Error(result?.message || '解除阻断失败');
        setMessage(result?.message || '阻断任务已重新进入 READY');
        await loadStatus(true);
      } catch (error) {
        setMessage(error?.message || '解除阻断失败', 'error');
      } finally {
        busy.value = '';
      }
    }

    async function browse(path = browserPath.value) {
      browserBusy.value = true;
      try {
        const result = await postApi(props, '/organize/folders', {path: path || '/'});
        if (!result?.success) throw new Error(result?.message || '目录读取失败');
        browserOpen.value = true;
        browserPath.value = result?.data?.path || '/';
        browserFolders.value = result?.data?.folders || [];
      } catch (error) {
        setMessage(error?.message || '目录读取失败', 'error');
      } finally {
        browserBusy.value = false;
      }
    }

    function parentPath() {
      if (browserPath.value === '/') return '/';
      return browserPath.value.split('/').slice(0, -1).join('/') || '/';
    }

    function selectBrowserPath() {
      monitorPath.value = browserPath.value;
      browserOpen.value = false;
    }

    onMounted(async () => {
      await Promise.all([loadConfig(true), loadStatus(true)]);
      timer = setInterval(() => {
        if (tab.value === 'organize') loadStatus(true);
      }, 3000);
    });
    onUnmounted(() => { if (timer) clearInterval(timer); });

    const browser = () => !browserOpen.value ? null : h('div', {class: 'gyv4-browser'}, [
      h('div', {class: 'gyv4-browser-head'}, [
        h('button', {class: 'gyv4-btn', disabled: browserPath.value === '/' || browserBusy.value, onClick: () => browse(parentPath())}, '上一级'),
        h('div', {class: 'gyv4-browser-path'}, browserPath.value),
        h('button', {class: 'gyv4-btn primary', disabled: browserPath.value === '/', onClick: selectBrowserPath}, '设为监控目录'),
        h('button', {class: 'gyv4-btn', onClick: () => browserOpen.value = false}, '关闭'),
      ]),
      h('div', {class: 'gyv4-folders'}, browserFolders.value.length
        ? browserFolders.value.map(folder => h('button', {class: 'gyv4-folder', title: folder.path, onClick: () => browse(folder.path)}, `📁 ${folder.name}`))
        : h('div', {class: 'gyv4-card-sub'}, browserBusy.value ? '读取中…' : '当前目录没有子文件夹')),
    ]);

    const organizer = () => h('div', {class: 'gyv4-shell'}, [
      h('div', {class: 'gyv4-head'}, [
        h('div', [
          h('div', {class: 'gyv4-title'}, '自动整理 · V4'),
          h('div', {class: 'gyv4-sub'}, '光鸭只负责发现与存储动作；识别、分类、目标目录、命名、覆盖、刮削和整理历史全部交给 MoviePilot V3。任务按文件独立稳定，READY 不会被同目录仍在上传的文件阻塞。'),
        ]),
        h('span', {class: 'gyv4-badge'}, 'ResourceStore → MoviePilot V3'),
      ]),
      h('div', {class: 'gyv4-body'}, [
        h('div', {class: 'gyv4-card'}, [
          h('div', {class: 'gyv4-card-title'}, '监控目录'),
          h('div', {class: 'gyv4-card-sub'}, '请选择具体媒体入口目录。为避免误扫整个网盘，V4 禁止把根目录 / 作为启用后的监控目录。'),
          h('div', {class: 'gyv4-path'}, [
            h('input', {class: 'gyv4-input', value: monitorPath.value, onInput: event => monitorPath.value = event.target.value, placeholder: '/光鸭媒体库'}),
            h('button', {class: 'gyv4-btn', disabled: Boolean(busy.value), onClick: () => browse(monitorPath.value || '/')}, '浏览'),
          ]),
          browser(),
          h('div', {class: 'gyv4-actions', style: {marginTop: '10px'}}, [
            h('label', {class: 'gyv4-switch'}, [
              h('input', {type: 'checkbox', checked: enabled.value, onChange: event => enabled.value = event.target.checked}),
              '启用自动监控',
            ]),
            h('label', {class: 'gyv4-switch'}, [
              h('input', {type: 'checkbox', checked: recursive.value, onChange: event => recursive.value = event.target.checked}),
              '递归子目录',
            ]),
          ]),
        ]),
        h('div', {class: 'gyv4-card'}, [
          h('div', {class: 'gyv4-card-title'}, '监控参数'),
          h('div', {class: 'gyv4-grid'}, [
            h('div', {class: 'gyv4-field'}, [h('label', '扫描周期（秒）'), h('input', {class: 'gyv4-input', type: 'number', min: '15', max: '3600', value: interval.value, onInput: event => interval.value = event.target.value})]),
            h('div', {class: 'gyv4-field'}, [h('label', '稳定等待（秒）'), h('input', {class: 'gyv4-input', type: 'number', min: '0', max: '3600', value: stability.value, onInput: event => stability.value = event.target.value})]),
            h('div', {class: 'gyv4-field'}, [h('label', '每轮目录预算'), h('input', {class: 'gyv4-input', type: 'number', min: '1', max: '500', value: batchSize.value, onInput: event => batchSize.value = event.target.value})]),
          ]),
        ]),
        message.value ? h('div', {class: `gyv4-msg ${messageKind.value === 'warn' ? 'warn' : messageKind.value === 'error' ? 'error' : ''}`}, message.value) : null,
        h('div', {class: 'gyv4-actions'}, [
          h('button', {class: 'gyv4-btn primary', disabled: Boolean(busy.value), onClick: save}, busy.value === 'save' ? '保存中…' : '保存设置'),
          h('button', {class: 'gyv4-btn', disabled: Boolean(busy.value) || monitorPath.value === '/', onClick: scan}, busy.value === 'scan' ? '扫描中…' : '立即扫描'),
          h('button', {class: 'gyv4-btn warn', disabled: Boolean(busy.value) || gracefulPaused.value, onClick: pause}, workerBusy.value ? '当前任务收尾后暂停' : '暂停自动整理'),
          Number(stats.value.BLOCKED || 0) > 0 ? h('button', {class: 'gyv4-btn warn', disabled: Boolean(busy.value), onClick: unblock}, `重新检查阻断 (${stats.value.BLOCKED})`) : null,
          h('button', {class: 'gyv4-btn', disabled: Boolean(busy.value), onClick: () => loadStatus(false)}, '刷新状态'),
        ]),
        gracefulPaused.value ? h('div', {class: 'gyv4-msg warn'}, status.value?.graceful_stop_message || '自动整理已暂停；持久待处理任务保留。重新启用并保存后继续。') : null,
        h('div', {class: 'gyv4-card'}, [
          h('div', {class: 'gyv4-card-title'}, 'ResourceStore 状态'),
          h('div', {class: 'gyv4-stats'}, [
            ['稳定中', stats.value.STABILIZING || 0],
            ['READY', stats.value.READY || 0],
            ['运行中', stats.value.RUNNING || 0],
            ['重试', stats.value.RETRY || 0],
            ['验收中', stats.value.VERIFYING || 0],
            ['阻断', stats.value.BLOCKED || 0],
            ['完成', stats.value.COMPLETED || 0],
          ].map(([key, value]) => h('div', {class: 'gyv4-stat'}, [h('span', key), h('b', String(value))]))),
          h('div', {class: 'gyv4-status'}, [
            h('div', `运行阶段：${status.value?.runtime_phase || (enabled.value ? 'idle' : 'disabled')} ｜ Worker：${workerBusy.value ? '忙' : '空闲'} ｜ 扫描：${status.value?.scan_active ? '进行中' : '空闲'} ｜ BFS剩余：${status.value?.scan_remaining || 0}`),
            h('div', `当前任务：${currentTask.value}`),
            status.value?.last_result_path ? h('div', `最近结果：${status.value.last_result_state || '-'} ｜ ${status.value.last_result_path} ｜ ${status.value.last_result_message || ''}`) : null,
            h('div', `最近心跳：${fmtTime(status.value?.last_tick)} ｜ 最近全量扫描：${fmtTime(status.value?.last_scan_at)}`),
          ]),
        ]),
        pending.value.length ? h('div', {class: 'gyv4-card'}, [
          h('div', {class: 'gyv4-card-title'}, '待处理样本'),
          h('div', {class: 'gyv4-history'}, pending.value.map(row => h('div', {class: 'gyv4-row'}, [
            h('div', stateText(row.state)),
            h('div', [h('b', row.path || '-'), row.last_error ? h('small', row.last_error) : null]),
            h('div', row.next_run ? `下次：${fmtTime(row.next_run)}` : '-'),
          ]))),
        ]) : null,
        h('div', {class: 'gyv4-card'}, [
          h('div', {class: 'gyv4-card-title'}, '最近自动整理结果'),
          h('div', {class: 'gyv4-card-sub'}, 'COMPLETED 必须来自 MoviePilot 成功历史确认；源文件消失但没有成功历史会进入 BLOCKED，而不是误判成功。'),
          h('div', {class: 'gyv4-history'}, history.value.length
            ? history.value.map(row => h('div', {class: 'gyv4-row'}, [
                h('div', fmtTime(row.time)),
                h('div', [h('b', row.path?.split('/').pop() || '-'), h('small', row.path || ''), row.message ? h('small', row.message) : null]),
                h('div', {class: `gyv4-state ${String(row.state || '').toUpperCase()}`}, stateText(row.state)),
              ]))
            : h('div', {class: 'gyv4-card-sub'}, '暂无整理结果')),
        ]),
      ]),
    ]);

    return () => h('div', {class: 'gyv4'}, [
      h('style', css),
      h('div', {class: 'gyv4-tabs'}, [
        h('button', {class: `gyv4-tab ${tab.value === 'account' ? 'active' : ''}`, onClick: () => tab.value = 'account'}, '账号与存储'),
        h('button', {class: `gyv4-tab ${tab.value === 'organize' ? 'active' : ''}`, onClick: () => { tab.value = 'organize'; loadStatus(true); }}, '自动整理'),
      ]),
      tab.value === 'account'
        ? h(AccountPage, {initialConfig: props.initialConfig, api: props.api, onClose: () => emit('close'), onSwitch: () => emit('switch')})
        : organizer(),
    ]);
  },
});
