import { createApp } from 'vue';
import Hls from 'hls.js';

window.Vue = { createApp };
window.Hls = Hls;
window.axios = {
  get: (url, config = {}) =>
    fetch(url, config).then(async r => ({ data: await r.json() })),
  post: (url, data = {}, config = {}) =>
    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(config.headers || {}) },
      body: JSON.stringify(data),
      ...config
    }).then(async r => ({ data: await r.json() }))
};
