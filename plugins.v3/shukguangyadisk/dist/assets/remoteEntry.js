const moduleMap = {
  './Page': () => import('./__federation_expose_AssistantPage-v352.js?v=3.5.6').then((mod) => () => mod.default),
  './Config': () => import('./__federation_expose_AssistantConfig-v300.js?v=3.0.0').then((mod) => () => mod.default),
};

const seenCss = new Set();
const dynamicLoadingCss = (cssFilePaths = [], dontAppendStylesToHead = false, exposeItemName = '') => {
  const metaUrl = import.meta.url;
  const baseUrl = metaUrl.substring(0, metaUrl.lastIndexOf('/') + 1);
  for (const cssPath of cssFilePaths || []) {
    const href = new URL(cssPath, baseUrl).href;
    if (dontAppendStylesToHead) {
      const key = `css__ShukGuangYaDisk__${exposeItemName}`;
      window[key] = window[key] || [];
      window[key].push(href);
      continue;
    }
    if (seenCss.has(href)) continue;
    seenCss.add(href);
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = href;
    document.head.appendChild(link);
  }
};

const get = (module) => {
  const loader = moduleMap[module];
  if (!loader) throw new Error(`Can not find remote module ${module}`);
  return loader();
};

const init = (shareScope) => {
  globalThis.__federation_shared__ = globalThis.__federation_shared__ || {};
  Object.entries(shareScope || {}).forEach(([key, value]) => {
    Object.entries(value || {}).forEach(([versionKey, versionValue]) => {
      const scope = versionValue.scope || 'default';
      globalThis.__federation_shared__[scope] = globalThis.__federation_shared__[scope] || {};
      const shared = globalThis.__federation_shared__[scope];
      (shared[key] = shared[key] || {})[versionKey] = versionValue;
    });
  });
};

export { dynamicLoadingCss, get, init };
