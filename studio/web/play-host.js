import { api } from './api-client.js';
import { endpoint } from './player-routes.js';
export function esc(value = '') {
  return String(value ?? '').replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
  );
}
function playerId() {
  let id = localStorage.getItem('loop-player');
  if (!id) {
    id = Array.from(crypto.getRandomValues(new Uint8Array(16)), (n) =>
      n.toString(16).padStart(2, '0'),
    ).join('');
    localStorage.setItem('loop-player', id);
  }
  return id;
}
export async function mountPlayer(
  root,
  gid,
  { preview = null, level = null, sample = false, campaign = null, onFinish = () => {} } = {},
) {
  let dispose = () => {},
    closed = false;
  const nonce = Array.from(crypto.getRandomValues(new Uint32Array(3)), (n) => n.toString(36)).join('');
  root.innerHTML = '<p class="muted">正在装载游戏模块…</p>';
  const payload = sample
    ? { game: await api(sample === 'harbor' ? '/static/sample-harbor.json' : '/static/sample-game.json'),
        level: level || 1, version: sample === 'harbor' ? 1 : 2 }
    : await api(endpoint('open_round', {gid}), {
        player: playerId(),
        preview,
        level,
        campaign,
        delivery: 'cached',
      });
  const game = payload.game || { ...(await api(payload.game_url)), ...payload.game_info };
  if (!root.isConnected) return () => {};
  const { round } = payload;
  const isPublicPage = root.id === 'player';
  if (isPublicPage) document.title = game.title + ' · 回路制作室';
  const title = isPublicPage
    ? '<h1>' + esc(game.title) + '</h1>'
    : '<div><span class="eyebrow">' + (preview ? '构建试玩' : '试玩') + ' / V' + esc(payload.version) + '</span><h3>' + esc(game.title) + '</h3></div>';
  root.innerHTML = `<div class="player-head">${title}<strong class="pill">第 ${payload.level} / ${game.count} 关</strong></div>
    <p class="instructions">${esc(game.controls)}</p><iframe class="game-frame" title="可交互游戏画面" sandbox="allow-scripts"></iframe><div class="play-actions"><span class="play-status" role="status">正在加载…</span><button class="primary act" disabled>开始游戏</button></div><div class="campaign-action"></div><div class="feedback-area"></div>`;
  const frame = root.querySelector('iframe'),
    btn = root.querySelector('.act'),
    feedback = root.querySelector('.feedback-area'),
    status = root.querySelector('.play-status');
  const hint = document.createElement('button');
  hint.className = 'secondary';
  hint.textContent = '玩法提示';
  hint.hidden = true;
  btn.after(hint);
  hint.onclick = async () => {
    try {
      if (!sample) await api(endpoint('show_hint', {token: round}), {});
      status.textContent = game.controls;
      frame.focus();
    } catch (err) { status.textContent = err.message; }
  };
  const send = (type, extra = {}) =>
    frame.contentWindow?.postMessage({ loop: nonce, type, payload: extra }, '*');
  let state = 'loading',
    startPromise = null,
    finished = false,
    lastEnd = null;
  async function recordEnd(result) {
    hint.hidden = true;
    await startPromise;
    if (!sample) await api(endpoint('event', {token: round}), { event: 'end', ...result });
    finished = true;
    status.textContent = (result.won ? '通关' : '本局结束') + ' · ' + result.score + ' 分';
    state = 'ended';
    btn.disabled = false;
    btn.textContent = result.won && payload.level < game.count ? '下一关' : '再玩一局';
    onFinish(result);
    if (!preview && !sample) {
      if (payload.action_label && result.finish === 'natural') {
        root.querySelector('.campaign-action').innerHTML =
          '<form action="' +
          esc(endpoint('visit_activity', {token: round})) +
          '" method="post" target="_blank" rel="noopener"><button class="primary">' +
          esc(payload.action_label) +
          '</button></form>';
      }
      feedback.innerHTML =
        '<form><label>本局体验<select name="rating"><option value="5">5 · 很喜欢</option><option value="4">4 · 喜欢</option><option value="3">3 · 一般</option><option value="2">2 · 较差</option><option value="1">1 · 很差</option></select></label><label>玩家反馈<input name="comment" maxlength="500" placeholder="这一关哪里有趣或困难？"></label><button class="secondary">提交反馈</button></form>';
      feedback.querySelector('form').onsubmit = async (e) => {
        e.preventDefault();
        const form = new FormData(e.target);
        try {
          await api(endpoint('feedback', {token: round}), {
            rating: Number(form.get('rating')),
            comment: form.get('comment'),
          });
          feedback.textContent = '已记录本局反馈';
        } catch (err) {
          status.textContent = err.message;
        }
      };
    }
  }
  const receive = async (e) => {
    if (closed || e.source !== frame.contentWindow || e.data?.loop !== nonce) return;
    try {
      const { type, payload: d } = e.data;
      if (type === 'queryGameConfig') send('config', { game, level: payload.level });
      if (type === 'onReady' && state === 'loading') {
        state = 'ready';
        status.textContent = '画面就绪';
        btn.disabled = false;
      }
      if (type === 'onGameStart' && state === 'starting') {
        hint.hidden = false;
        state = 'playing';
        status.textContent = '游戏中';
        btn.textContent = '结束本局';
        btn.disabled = false;
      }
      if (type === 'onGameEnd' && !lastEnd && state === 'playing') {
        lastEnd = {
          won: d.won === true,
          score: Number(d.score) || 0,
          finish: d.finish,
          inputs: d.inputs || [],
        };
        btn.disabled = true;
        await recordEnd(lastEnd);
      }
      if (type === 'error') {
        status.textContent = d.message;
        state = 'error';
        btn.disabled = true;
      }
    } catch (err) {
      status.textContent = err.message;
      state = lastEnd ? 'save' : 'ready';
      btn.textContent = lastEnd ? '重试保存' : '重新开始';
      btn.disabled = false;
    }
  };
  btn.onclick = async () => {
    try {
      if (state === 'ready') {
        btn.disabled = true;
        state = 'starting';
        startPromise = sample
          ? Promise.resolve()
          : api(endpoint('event', {token: round}), { event: 'start' });
        await startPromise;
        send('host:event', { name: 'start' });
        frame.focus();
      } else if (state === 'playing') send('host:event', { name: 'stop' });
      else if (state === 'save') await recordEnd(lastEnd);
      else if (state === 'ended') {
        dispose();
        const next = lastEnd.won ? Math.min(payload.level + 1, game.count) : payload.level;
        const nextDispose = await mountPlayer(root, gid, {
          preview,
          level: next,
          sample,
          campaign,
          onFinish,
        });
        dispose = nextDispose;
      }
    } catch (err) {
      status.textContent = err.message;
      btn.disabled = false;
      if (!lastEnd) state = 'ready';
    }
  };
  const leave = () => {
    if (!sample && state === 'playing' && !finished && !lastEnd)
      navigator.sendBeacon(
        endpoint('event', {token: round}),
        new Blob([JSON.stringify({ event: 'end', won: false, score: 0, finish: 'quit' })], {
          type: 'application/json',
        }),
      );
  };
  dispose = () => {
    if (closed) return;
    leave();
    closed = true;
    window.removeEventListener('message', receive);
    window.removeEventListener('pagehide', leave);
  };
  window.addEventListener('message', receive);
  window.addEventListener('pagehide', leave);
  frame.src = '/static/frame.html#' + nonce;
  return () => dispose();
}
