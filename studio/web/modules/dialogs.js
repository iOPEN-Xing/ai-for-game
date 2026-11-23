import { esc as h, mountPlayer } from '../play-host.js';
import { api } from '../api-client.js';
import { endpoint } from '../routes.js';
import { state } from './state.js';
import { $, artifact, button, close, content, dialog, form, kv, popup, toast } from './ui.js';
import { labels, titles } from './labels.js';

function newIdea(example) {
  const x = example || {};
  const requestId = Array.from(crypto.getRandomValues(new Uint32Array(4)), (n) =>
    n.toString(16).padStart(8, '0'),
  ).join('');
  const opts = Object.entries(state.overview.metrics)
    .map(([k, v]) => '<option value="' + k + '">' + h(v) + '</option>')
    .join('');
  form(
    '新建游戏项目',
    '<label>项目名称<input name="title" required autofocus maxlength="80" value="' +
      h(x.title) +
      '" placeholder="给游戏取个名字"></label><label>玩法创意<textarea name="brief" required maxlength="2000" placeholder="玩家做什么，怎样赢得一局？">' +
      h(x.brief) +
      '</textarea></label><label>北极星指标<select name="metric">' +
      opts +
      '</select></label><label>行动边界<textarea name="bounds" required maxlength="2000">单手触屏可玩，优先保证首关体验，不加入付费道具。</textarea></label>',
    '开始玩法调研',
    async (f) => {
      const r = await api(endpoint('create'), { request_id: requestId, ...Object.fromEntries(f) });
      location.hash = 'project/' + r.game + '/' + r.rev;
    },
  );
}

function campaignForm(refresh) {
  const games = state.overview.games.filter((g) => g.live && (!state.opsGame || g.id === state.opsGame));
  form(
    '创建活动入口',
    '<label>已发布游戏<select name="game">' +
      games.map((g) => '<option value="' + g.id + '">' + h(g.title) + '</option>').join('') +
      '</select></label><label>入口名称<input name="name" maxlength="80" required placeholder="例如，公众号冬季活动"></label>' +
      '<fieldset><legend>完局后的行动按钮（选填）</legend><label>按钮文字<input name="action_label" maxlength="32" placeholder="查看本周活动"></label><label>目标网址<input type="url" name="action_url" placeholder="https://"></label></fieldset>',
    '生成链接',
    async (f) => {
      const game = f.get('game');
      await api(endpoint('create_campaign', {gid: game}), {
        name: f.get('name'),
        action_label: f.get('action_label').trim() || null,
        action_url: f.get('action_url').trim() || null,
      });
      await refresh();
      toast('入口已创建，可在列表复制链接');
    },
  );
}

async function copyCampaign(game, id) {
  const url = new URL(endpoint('player_page', {gid: game}), state.overview.public_origin || location.origin);
  url.searchParams.set('entry', id);
  try {
    await navigator.clipboard.writeText(url.href);
    toast('活动入口链接已复制');
  } catch {
    popup(
      '活动入口链接',
      '<label>复制此链接<input id="share-url" readonly value="' + h(url.href) + '"></label>',
    );
    $('#share-url').select();
  }
}

async function showPreview(refresh, level = null) {
  const d = state.current;
  popup('构建试玩', '<div id="preview-mount"></div>');
  const mount = $('#preview-mount');
  try {
    const dispose = await mountPlayer(mount, d.game.id, {
      preview: d.revision.id,
      level,
      onFinish: () => {
        refresh();
      },
    });
    if (!dialog.open || !mount.isConnected) dispose();
    else state.modalDispose = dispose;
  } catch (err) {
    mount.textContent = err.message;
  }
}

async function blueprints(refresh) {
  const d = state.current,
    pack = await api(endpoint('blueprints', {rid: d.revision.id}));
  popup(
    '关卡蓝图',
    '<p class="muted">Seed ' +
      pack.seed +
      ' · ' +
      (pack.mode === 'prefab' ? '离线验证的预制关卡' : '按 Seed 运行时生成') +
      '</p><div class="level-control"><label>查看关卡<select id="lv">' +
      pack.levels.map((_, i) => '<option value="' + i + '">第 ' + (i + 1) + ' 关</option>').join('') +
      '</select></label>' +
      button('try-level', '试玩此关', 'small-btn') +
      '</div><canvas class="level-chart" width="400" height="400"></canvas><div id="level-detail"></div><div id="blueprint-editor"></div>',
  );
  const draw = () => {
    const i = Number($('#lv').value),
      L = pack.levels[i],
      c = content.querySelector('canvas').getContext('2d'),
      W = 400;
    c.fillStyle = '#ececd9';
    c.fillRect(0, 0, W, W);
    c.fillStyle = '#405844';
    if (L.grid) {
      const w = W / L.size;
      L.grid.forEach((a, i) => {
        if (!a) c.fillRect((i % L.size) * w, Math.floor(i / L.size) * w, w + 0.5, w + 0.5);
      });
      [L.from, L.to].forEach((a, i) => {
        c.fillStyle = i ? '#c55934' : '#86a67b';
        c.fillRect((a % L.size) * w, Math.floor(a / L.size) * w, w, w);
      });
    } else {
      c.strokeStyle = '#a4ad96';
      c.beginPath();
      L.points.forEach((p, i) => {
        const x = (L.family === 'drift' ? (p.lane + 0.5) / 3 : p.x) * W,
          y = (L.family === 'drift' ? (i + 0.5) / L.points.length : p.y) * W;
        i ? c.lineTo(x, y) : c.moveTo(x, y);
      });
      c.stroke();
      L.points.forEach((p, i) => {
        const x = (L.family === 'drift' ? (p.lane + 0.5) / 3 : p.x) * W,
          y = (L.family === 'drift' ? (i + 0.5) / L.points.length : p.y) * W;
        c.fillStyle = i === 0 ? '#d36239' : '#405844';
        c.beginPath();
        c.arc(x, y, i === 0 ? 8 : 4, 0, Math.PI * 2);
        c.fill();
      });
    }
    $('#level-detail').innerHTML = kv({
      '关卡 Seed': L.seed,
      目标数量: L.quota,
      '时限（秒）': L.seconds,
      验证步数: pack.proof[i].moves,
      较父版本变更: L.changes,
      ...(pack.removed_levels?.length ? { 已移除关卡: pack.removed_levels } : {}),
    });
    if (['quality', 'ready'].includes(d.revision.stage)) {
      const fields = { seconds: '时限（秒）', quota: '目标数量', radius: '目标半径', pace: '节拍', size: '网格边长' };
      const editor = $('#blueprint-editor');
      editor.innerHTML = '<details><summary>调整种子与本关参数</summary><form class="blueprint-form"><label>生成种子<input type="number" min="0" max="2147483647" required name="seed" value="' +
        h(pack.seed) + '"></label>' + Object.entries(fields).map(([key, label]) =>
        '<label>' + label + '<input type="number" step="any" required name="' + key + '" value="' + h(L[key]) + '"></label>').join('') +
        '<label><input type="checkbox" name="reset">恢复本关生成器默认参数</label><button type="submit" class="primary">重建并重新验收</button></form></details>';
      editor.querySelector('form').onsubmit = async e => {
        e.preventDefault();
        const form = new FormData(e.target), values = {...(d.revision.docs.level_code.overrides?.[L.index] || {})};
        Object.keys(fields).forEach(key => { if (Number(form.get(key)) !== L[key]) values[key] = Number(form.get(key)); });
        try {
          await api(endpoint('edit_blueprint', {rid: d.revision.id}), {serial: d.revision.serial, seed: Number(form.get('seed')),
            level: L.index, values: form.has('reset') ? {} : values});
          close(); await refresh();
        } catch (err) { $('#form-error').textContent = err.message; }
      };
    }
  };
  $('#lv').onchange = draw;
  draw();
}

async function proposal(id) {
  const p = await api(endpoint('proposal', {pid: id})),
    bet = p.doc.bet;
  let body = '<p class="muted">' + h(labels[p.status] || p.status) + ' · ' + h(p.day) + '</p>';
  if (p.doc.hold) body += '<h3>需要补充的证据</h3><p>' + h(p.doc.hold.reason) + '</p><ul>' +
    p.doc.hold.required.map(item => '<li>' + h(item) + '</li>').join('') + '</ul>';
  if (bet) {
    const { checks, resolutions, ...summary } = bet;
    body += kv(summary);
    if (checks?.length) body += '<h3>上线前验收</h3><ul>' + checks.map(c => '<li>' +
      (c.kind === 'asset' ? h(c.entity + ' · ' + c.action + ' · ' + c.brief) :
        '第 ' + h(c.level) + ' 关 · ' + h(c.field) + '　' + h(c.before) + ' → ' + h(c.after)) + '</li>').join('') + '</ul>';
    if (resolutions?.length) body += '<h3>专家质询</h3>' + resolutions.map(r => {
      const issue = r.issue.startsWith('b-') ? p.doc[r.issue.slice(2)]?.blocker : p.doc.challenge?.issues?.[Number(r.issue.slice(1)) - 1];
      const reply = p.doc['reply_' + r.issue];
      return '<details class="doc"><summary>' + h(issue?.question || r.issue) + '</summary><p>' +
        h(issue?.owner || '') + ' · ' + h(reply?.response || '待答复') + '</p><p>主持人 · ' + h(r.reason) + '</p><p>独立评审 · ' + h(p.doc['verify_' + r.issue]?.basis || '待复核') + '</p></details>';
    }).join('');
    if (p.doc.final_review) body += '<p><strong>终审意见</strong>　' + h(p.doc.final_review.reason) + '</p>';
  }
  const handoffs = Object.entries(p.doc).filter(([k, v]) => k !== 'bet' && v && typeof v === 'object');
  if (handoffs.length) {
    const roleName = {Analyst: '数据分析师', Engineer: '工程师', Reviewer: '评审', GameDesigner: '游戏设计师', challenge: '专家质询',
      final_review: '独立终审', hold: '补证清单'};
    body += '<details class="doc"><summary>原始交接与审计（' + handoffs.length + ' 项）</summary>' +
      handoffs.map(([k,v]) => {
        const match = /^(reply|resolve|verify)_(.+)$/.exec(k);
        const title = match ? ({reply:'责任人答复',resolve:'主持人裁决',verify:'逐项复核'}[match[1]] + ' · ' + match[2]) : (roleName[k] || titles[k] || k);
        return '<details class="doc"><summary>' + h(title) + '</summary>' + artifact(k,v) + '</details>';
      }).join('') + '</details>';
  }
  body += '<details><summary>冻结的证据</summary>' + kv(p.evidence) + '</details>';
  if (p.status === 'review' && p.doc.protocol === p.current_protocol)
    body +=
      '<label>审核意见<textarea id="verdict" maxlength="1000"></textarea></label><div class="actions">' +
      button('prop-yes', '批准并进入生产', 'primary', 'data-id="' + id + '"') +
      button('prop-no', '驳回', 'secondary', 'data-id="' + id + '"') +
      '</div>';
  if (p.status === 'failed') body += button('prop-retry', '重试分析', 'primary', 'data-id="' + id + '"');
  if (p.status === 'needs_evidence' || (['review', 'production'].includes(p.status) && p.doc.protocol !== p.current_protocol))
    body += '<label>补充证据或来源<textarea id="supplement" maxlength="1000"></textarea></label>' +
      button('prop-retry', '更新样本并重新论证', 'primary', 'data-id="' + id + '"');
  popup(bet?.title || '运营分析', body);
}

export { blueprints, campaignForm, copyCampaign, newIdea, proposal, showPreview };
