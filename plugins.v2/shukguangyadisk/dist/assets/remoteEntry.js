import { dynamicLoadingCss, get as legacyGet, init } from './remoteEntry_legacy.js';

const get = (module) => {
  if (module === './Page') {
    return import('./__federation_expose_AssistantPage-216.js').then((mod) => () => mod.default);
  }
  if (module === './Config') {
    return import('./__federation_expose_AssistantConfig-dev.js').then((mod) => () => mod.default);
  }
  return legacyGet(module);
};

export { dynamicLoadingCss, get, init };
