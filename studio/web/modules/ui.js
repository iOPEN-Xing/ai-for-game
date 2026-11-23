import { esc as h } from '../play-host.js';
import { state } from './state.js';
import { titles } from './labels.js';

let toastTimer = null;

const $ = (s) => document.querySelector(s),
  root = $('#app'),
  dialog = $('#dialog'),
  content = $('#dialog-content');

const fmt = (n) => (n === null || n === undefined ? '—' : String(n));

const date = (s) =>
  new Date(s * 1000).toLocaleString('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });

const pill = (s, warm = false) => '<span class="pill' + (warm ? ' warm' : '') + '">' + h(s) + '</span>';

const button = (action, text, cls = 'secondary', attrs = '') =>
  '<button type="button" class="' +
  cls +
  '" data-do="' +
  action +
  '" ' +
  attrs +
  '>' +
  text +
  '</button>';

const back = (url, label) => '<a class="ghost" href="#' + url + '">← ' + h(label) + '</a>';

const heading = (title, sub = '', action = '') =>
  '<div class="page-head"><div><h1>' +
  h(title) +
  '</h1>' +
  (sub ? '<p class="muted">' + h(sub) + '</p>' : '') +
  '</div>' +
  action +
  '</div>';

const reviewStages = new Set(['references', 'direction', 'plan', 'quality', 'ready']);

const needsReview = (game) => reviewStages.has(game.stage) || game.job_state === 'failed';

const empty = (text, action = '') =>
  '<div class="empty"><span>' + h(text) + '</span>' + action + '</div>';

function toast(text) {
  $('#toast').textContent = text;
  $('#toast').classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $('#toast').classList.remove('show'), 3200);
}

function close() {
  if (dialog.open) dialog.close();
}

dialog.addEventListener('close', () => {
  state.modalDispose?.();
  state.modalDispose = null;
  content.innerHTML = '';
});

dialog.addEventListener('click', (e) => {
  if (e.target === dialog) close();
});

function popup(title, body) {
  state.modalDispose?.();
  state.modalDispose = null;
  content.innerHTML =
    '<div class="dialog-head"><h2>' +
    h(title) +
    '</h2><button type="button" aria-label="关闭" data-do="close">×</button></div>' +
    body +
    '<div role="alert" class="err" id="form-error"></div>';
  if (!dialog.open) dialog.showModal();
}

function formButton(label) {
  return (
    '<div class="form-end">' +
    button('close', '取消', 'secondary') +
    '<button class="primary" type="submit">' +
    h(label) +
    '</button></div>'
  );
}

function form(title, fields, submit, call) {
  popup(title, '<form class="fields">' + fields + formButton(submit) + '</form>');
  content.querySelector('form').onsubmit = async (e) => {
    e.preventDefault();
    const b = e.target.querySelector('[type=submit]');
    b.disabled = true;
    try {
      await call(new FormData(e.target));
      if (dialog.open) close();
    } catch (err) {
      $('#form-error').textContent = err.message;
      b.disabled = false;
    }
  };
}

function stats(entries) {
  return (
    '<div class="strips">' +
    entries
      .map(
        ([k, v]) =>
          '<div class="stat"><span>' + h(k) + '</span><b class="metric-num">' + h(fmt(v)) + '</b></div>',
      )
      .join('') +
    '</div>'
  );
}

function value(v) {
  if (v === null || v === undefined) return '—';
  if (Array.isArray(v))
    return v.length
      ? v
          .map((x) =>
            typeof x === 'object' ? '<pre>' + h(JSON.stringify(x, null, 2)) + '</pre>' : h(x),
          )
          .join('<br>')
      : '无';
  if (typeof v === 'object') return kv(v);
  return h(v);
}

function kv(o) {
  return (
    '<dl class="kv">' +
    Object.entries(o)
      .filter(([k]) => k !== '_run')
      .map(
        ([k, v]) =>
          '<dt>' +
          h(titles[k] || k) +
          '</dt><dd>' +
          (k === 'source' ? '<pre>' + h(v) + '</pre>' : value(v)) +
          '</dd>',
      )
      .join('') +
    '</dl>'
  );
}

function artifact(key, v) {
  const p = v._run,
    att = p
      ? '<p class="status-inline">' +
        h(p.role) +
        ' · ' +
        h(p.model) +
        ' · ' +
        h(p.provider) +
        '<br>技能 ' +
        h(
          Object.entries(p.skills || {})
            .map(([n, rev]) => n + '@' + rev.slice(0, 7))
            .join(' / '),
        ) +
        (p.context_sha256 ? '<br>上下文 ' + h(p.context_sha256.slice(0, 12)) +
          ' · 偏好版本 ' + h(p.preference_version ?? '—') +
          ' · ' + h(p.context_bytes) + ' 字节 · 系统提示 ' + h((p.prompt_revision || '').slice(0, 12)) : '') +
        '</p>'
      : '';
  return kv(v) + att + (p?.run_id && p.context_sha256 ? button('agent-input', '查看本次输入与系统提示', 'small-btn',
    'data-run="' + h(p.run_id) + '" data-node="' + h(p.node) + '" data-hash="' + h(p.context_sha256) + '"') : '');
}

function historyHtml(items) {
  return (
    '<div class="history">' +
    [...items]
      .reverse()
      .map(
        (i) =>
          '<div class="history-item"><small>' +
          h(date(i.at)) +
          ' · ' +
          h(i.role) +
          '</small><p>' +
          h(i.text) +
          '</p></div>',
      )
      .join('') +
    '</div>'
  );
}

export { $, artifact, back, button, close, content, date, dialog, empty, fmt, form, heading, historyHtml, kv, needsReview, pill, popup, root, stats, toast };
