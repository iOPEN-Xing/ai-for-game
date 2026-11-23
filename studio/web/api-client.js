export function pathFor(paths, name, parameters = {}, query) {
  if (!Object.hasOwn(paths, name)) throw new Error('未知接口 ' + name);
  const path = paths[name].replace(/\{(\w+)\}/g, (_, key) => {
    if (parameters[key] == null) throw new Error('缺少接口参数 ' + key);
    return encodeURIComponent(parameters[key]);
  });
  const search = new URLSearchParams(query).toString();
  return search ? path + '?' + search : path;
}

async function request(path, options = {}) {
  const headers = new Headers(options.headers);
  const url = new URL(path, location.href);
  const res = await fetch(url, { ...options, headers });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    const wait = res.headers.get('Retry-After');
    const detail = Array.isArray(data.detail) ? data.detail.map((e) => e.msg).join(' · ') : data.detail;
    const reason = data.message || detail || ('服务返回 HTTP ' + res.status);
    const error = new Error(wait ? reason + '（' + wait + ' 秒后可重试）' : reason);
    error.status = res.status;
    error.code = data.code;
    error.requestId = res.headers.get('X-Request-Id');
    throw error;
  }
  return res;
}

export async function api(path, body, method = body === undefined ? 'GET' : 'POST') {
  const options = { method };
  if (body !== undefined) {
    options.headers = { 'Content-Type': 'application/json' };
    options.body = JSON.stringify(body);
  }
  return (await request(path, options)).json();
}

export async function fetchBlob(path) {
  return (await request(path)).blob();
}
