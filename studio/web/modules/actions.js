import { esc as h } from '../play-host.js';
import { api, fetchBlob } from '../api-client.js';
import { endpoint } from '../routes.js';
import { $, artifact, close, dialog, form, kv, popup, root, toast } from './ui.js';
import { examples } from './labels.js';
import { state } from './state.js';
import { blueprints, campaignForm, copyCampaign, newIdea, proposal, showPreview } from './dialogs.js';
import { project } from './project-views.js';

export function bindActions({ refresh, decide, listeners }) {
  document.addEventListener('click', async (e) => {
    const el = e.target.closest('[data-do]');
    if (!el || el.disabled) return;
    const { do: action, id, key, index } = el.dataset;
    el.disabled = true;
    try {
      if (action === 'campaign') campaignForm(refresh);
      if (action === 'copy-campaign') await copyCampaign(el.dataset.game, id);
      if (action === 'close') close();
      if (action === 'refresh') await refresh();
      if (action === 'create' || action === 'example')
        newIdea(action === 'example' ? examples[Number(index)] : null);
      if (action === 'classic' || action === 'canvas') {
        state.view = action;
        root.innerHTML = project(state.current);
        listeners();
      }
      if (action === 'agent-input') {
        const {run, node, hash} = el.dataset;
        const record = await api(endpoint('inspect_agent_input', {run, node, fingerprint: hash}));
        const pictures = Object.entries(record.images || {}).map(([name, digest]) =>
          '<figure><img alt="' + h(name) + '" loading="lazy" style="max-width:100%;max-height:220px" src="' +
          h(endpoint('archived_reference', {run, digest})) + '"><figcaption>' + h(name) + '</figcaption></figure>').join('');
        popup(record.role + ' · 本次输入', pictures + '<details open><summary>实际提交的资料</summary>' + kv(record.input) +
          '</details><details><summary>系统提示与已注入手册</summary><pre>' + h(record.prompt) + '</pre></details>');
      }
      if (action === 'artifact') popup(state.current.artifacts[key], artifact(key, state.current.revision.docs[key]));
      if (['approve', 'retry', 'accept'].includes(action)) await decide(action);
      if (action === 'publish-confirm')
        form(
          '发布 V' + state.current.revision.num,
          '<p>本次操作将开放玩家入口并记录发布事件。</p>',
          '发布版本',
          async () => {
            await decide('publish');
            toast('版本已发布');
          },
        );
      if (action === 'revise') {
        const s = state.current.revision.stage,
          list = ['direction', 'research', 'references', 'interpret'].includes(s)
            ? ['research']
            : ['plan', 'design'].includes(s)
              ? ['auto', 'design', 'art', 'levels', 'research']
              : ['auto', 'build', 'game_code', 'level_code', 'art', 'levels', 'design', 'research'];
        form(
          '退回修改',
          '<label>重新开始的环节<select name="target">' +
            list
              .map(
                (t) =>
                  '<option value="' +
                  t +
                  '">' +
                  h(
                    state.overview.stages[t] ||
                      {
                        art: '局部重做美术与音频',
                        auto: '由制作人判断影响范围',
                        levels: '局部重做关卡方案',
                        game_code: '重做游戏与关卡代码',
                        level_code: '仅重做关卡代码',
                      }[t],
                  ) +
                  '</option>',
              )
              .join('') +
            '</select></label><label>修改意见<textarea autofocus name="note" required maxlength="1400"></textarea></label>',
          '提交修改',
          async (f) => {
            await decide('revise', Object.fromEntries(f));
          },
        );
      }
      if (action === 'art-media') {
        const a = state.current.revision.docs.art;
        popup(
          '视听资产',
          '<p>' +
            h(a.style) +
            '</p><div class="swatches">' +
            [a.background, a.ink, a.accent]
              .map((c) => '<span style="background:' + h(c) + '"></span>')
              .join('') +
            '</div><div id="asset-preview"></div>',
        );
        const parent = $('#asset-preview'),
          urls = [];
        state.modalDispose = () => urls.forEach((u) => URL.revokeObjectURL(u));
        for (const [name, label, entity] of [
          ...(a.sprites?.length
            ? a.sprites.map((s) => ['sprite', s.title, s.id])
            : [['sprite', '主图形']]),
          ['ui', '界面提示'],
          ['hit', '命中'],
          ['miss', '失误'],
          ['win', '通关'],
          ['bgm', '背景音乐'],
        ]) {
          const blob = await fetchBlob(endpoint('design_media', {rid: state.current.revision.id, asset: name}, entity ? {entity} : undefined));
          if (!parent.isConnected) break;
          const url = URL.createObjectURL(blob);
          urls.push(url);
          const box = document.createElement('figure'),
            media = document.createElement(name.startsWith('sprite') ? 'img' : 'audio');
          media.src = url;
          media.controls = true;
          const cap = document.createElement('figcaption');
          cap.textContent = label;
          box.append(cap, media);
          parent.append(box);
        }
      }
      if (action === 'refs') {
        const d = state.current.revision.docs.research.directions[Number(index)];
        popup(
          d.title + ' · 调研参考',
          d.references
            .map(
              (ref) =>
                '<figure class="research-ref"><img src="' +
                h(ref.image) +
                '" alt="' +
                h(ref.title) +
                '"><figcaption>' +
                h(ref.title) +
                ' · ' +
                h(ref.credit) +
                '</figcaption></figure>',
            )
            .join(''),
        );
      }
      if (action === 'preview') await showPreview(refresh);
      if (action === 'try-level') await showPreview(refresh, Number($('#lv').value) + 1);
      if (action === 'blueprints') await blueprints(refresh);
      if (action === 'download') {
        const blob = await fetchBlob(endpoint('download', {rid: state.current.revision.id}));
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'game-v' + state.current.revision.num + '.zip';
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 5000);
      }
      if (action === 'analyze') {
        const games = state.overview.games.filter((g) => g.live);
        if (!games.length) {
          toast('发布游戏并收到正式开局后即可分析');
          return;
        }
        form(
          '发起运营分析',
          '<label>游戏<select name="game">' +
            games
              .map(
                (g) =>
                  '<option value="' +
                  g.id +
                  '" ' +
                  (g.id === state.opsGame ? 'selected' : '') +
                  '>' +
                  h(g.title) +
                  '</option>',
              )
              .join('') +
            '</select></label><label>任务类型<select name="kind"><option value="iteration">存量游戏迭代</option><option value="new_game">新游戏立项</option></select></label><p class="muted">冻结最近七天的正式对局、当前源码、关卡与版本记录。</p>',
          '启动专家分析',
          async (f) => {
            await api(endpoint('analysis'), Object.fromEntries(f));
            await refresh();
          },
        );
      }
      if (action === 'change-log') {
        if (!state.overview.games.length) {
          toast('请先创建游戏项目');
          return;
        }
        form(
          '记录外部变更',
          '<label>游戏<select name="game">' +
            state.overview.games
              .map(
                (g) =>
                  '<option value="' +
                  g.id +
                  '" ' +
                  (g.id === state.opsGame ? 'selected' : '') +
                  '>' +
                  h(g.title) +
                  '</option>',
              )
              .join('') +
            '</select></label><label>变更内容<textarea name="text" required placeholder="例如流量入口调整或上线新活动"></textarea></label><label>对实验口径的影响<select name="affects"><option value="yes">可能影响测量</option><option value="no">仅记录背景</option></select></label>',
          '保存变更',
          async (f) => {
            await api(endpoint('external_change'), {
              game: f.get('game'),
              text: f.get('text'),
              affects_measurement: f.get('affects') === 'yes',
            });
            await refresh();
          },
        );
      }
      if (action === 'batch-detail') {
        const b = await api(endpoint('batch_details', {day: id}));
        popup('批次 ' + b.day, kv(b.doc));
      }
      if (action === 'batch') {
        const b = await api(endpoint('batch'), {});
        toast('已核对 ' + b.day + ' 批次');
        await refresh();
      }
      if (action === 'proposal') await proposal(id);
      if (action === 'prop-retry') {
        await api(endpoint('retry_proposal', {pid: id}), { note: $('#supplement')?.value || '' });
        close();
        await refresh();
      }
      if (action === 'prop-yes' || action === 'prop-no') {
        const r = await api(endpoint('review_proposal', {pid: id}), {
          accept: action === 'prop-yes',
          note: $('#verdict').value,
        });
        close();
        if (r.production) location.hash = 'project/' + r.production.game + '/' + r.production.rev;
        else await refresh();
      }
      if (action === 'promote' || action === 'rollback')
        form(
          action === 'promote' ? '全量发布实验版' : '回到对照版',
          '<p>确认后将更新正式玩家入口的默认版本。</p>',
          '确认版本变更',
          async () => {
            await api(endpoint('exp_decision', {eid: id}), { accept: action === 'promote' });
            await refresh();
          },
        );
      if (action === 'memtab') {
        location.hash = 'memory/' + key;
      }
      if (action === 'know-yes' || action === 'know-no') {
        const entry = state.memoryData.entries.find(k => k.id === id);
        const approved = action === 'know-yes';
        const candidates = approved && entry.evidence.attribution === '假设错'
          ? state.memoryData.entries.filter(k => entry.evidence.citations?.includes(k.id) && k.game === entry.game && k.status === 'active') : [];
        if (candidates.length) {
          form('采纳结算记录', '<fieldset><legend>本次证据推翻了哪些已有结论？</legend>' +
            candidates.map(k => '<label><input type="checkbox" name="prior" value="' + h(k.id) + '"> ' + h(k.text) + '</label>').join('') +
            '</fieldset>', '保存评审', async f => {
              await api(endpoint('review_memory', {kid: id}), {accept: true, supersede: f.getAll('prior')}); await refresh();
            });
        } else {
          await api(endpoint('review_memory', {kid: id}), {accept: approved}); await refresh();
        }
      }
    } catch (err) {
      if (dialog.open && $('#form-error')) $('#form-error').textContent = err.message;
      else toast(err.message);
    } finally {
      if (el.isConnected) el.disabled = false;
    }
  });
}
