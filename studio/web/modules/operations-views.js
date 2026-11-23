import { esc as h } from '../play-host.js';
import { parts, state } from './state.js';
import { button, date, empty, fmt, heading, historyHtml, kv, pill, stats } from './ui.js';
import { labels } from './labels.js';
import { gameRows } from './project-views.js';

function metricsTable(data, cols) {
  const keys = [
    ...cols,
    ['visitors', '访问玩家'],
    ['players', '开局玩家'],
    ['starts', '开局'],
    ['ends', '完局'],
    ['wins', '胜局'],
    ['entry_rate', '开局率'],
    ['completion_rate', '完局率'],
    ['win_rate', '通关率'],
    ['action_rate', '活动入口点击率'],
  ];
  return (
    '<div class="tablescroll"><table><thead><tr>' +
    keys.map(([, label]) => '<th>' + h(label) + '</th>').join('') +
    '</tr></thead><tbody>' +
    data
      .map(
        (r) =>
          '<tr>' +
          keys
            .map(
              ([k]) =>
                '<td>' +
                h(
                  k === 'game'
                    ? state.overview.games.find((g) => g.id === r.game)?.title || r.game
                    : k === 'rev'
                      ? r.rev.slice(0, 7)
                      : fmt(r[k]) + (k.endsWith('_rate') && r[k] != null ? '%' : ''),
                ) +
                '</td>',
            )
            .join('') +
          '</tr>',
      )
      .join('') +
    '</tbody></table></div>'
  );
}

function channelSection(o) {
  const t = o.report.total;
  const steps = [
    ['进入游戏', t.action_visitors],
    ['开始玩', t.action_starters],
    ['自然完局', t.action_finishers],
    ['点击活动', t.action_players],
  ];
  const funnel = t.action_visitors
    ? '<ol class="funnel">' +
      steps
        .map(
          ([name, n]) =>
            '<li><span>' +
            name +
            '</span><strong>' +
            n +
            '</strong><div class="funnel-track"><i style="width:' +
            (100 * n) / t.action_visitors +
            '%"></i></div></li>',
        )
        .join('') +
      '</ol>'
    : '<p class="funnel-empty">首位玩家通过带按钮的入口进入游戏后，这里会显示参与漏斗。</p>';
  const published = state.overview.games.filter((g) => g.live && (!state.opsGame || g.id === state.opsGame));
  const rows = new Map(o.campaigns.map((c) => [c.id, { ...c }]));
  for (const ch of o.report.channels) {
    const key = ch.campaign || 'direct-' + ch.game;
    rows.set(key, { ...rows.get(key), ...ch, id: ch.campaign, name: ch.channel || '直接访问' });
  }
  const byGame = new Map(state.overview.games.map((g) => [g.id, g.title]));
  const table = rows.size
    ? '<div class="tablescroll"><table class="channel-table"><thead><tr><th>入口</th><th>访客</th><th>开局玩家</th><th>完局玩家</th><th>行动点击人数</th><th>点击率</th><th>分享</th></tr></thead><tbody>' +
      Array.from(
        rows.values(),
        (c) =>
          '<tr><th scope="row">' +
          h(c.name) +
          '<small>' +
          h(byGame.get(c.game) || '') +
          (c.action_label ? ' / ' + h(c.action_label) : '') +
          '</small></th><td>' +
          (c.visitors || 0) +
          '</td><td>' +
          (c.players || 0) +
          '</td><td>' +
          (c.finish_players || 0) +
          '</td><td>' +
          (c.action_label ? c.action_players || 0 : '—') +
          '</td><td>' +
          (c.action_rate == null ? '—' : c.action_rate + '%') +
          '</td><td>' +
          (c.id
            ? button(
                'copy-campaign',
                '复制链接',
                'text-link',
                'data-id="' + h(c.id) + '" data-game="' + h(c.game) + '"',
              )
            : '—') +
          '</td></tr>',
      ).join('') +
      '</tbody></table></div>'
    : '';
  return (
    '<section id="ops-channels" class="channel-panel"><div class="section-head"><h2>活动入口</h2>' +
    (published.length
      ? button('campaign', '创建活动入口', 'secondary')
      : '<a class="text-link" href="#projects">查看游戏项目</a>') +
    '</div>' +
    funnel +
    table +
    '<details class="metric-note"><summary>统计口径</summary><p>仅计算正式对局。按对局进入时间归入观察期，同一浏览器在每个入口去重。漏斗仅包含带行动按钮的入口，点击率为点击人数除以这些入口的访客数。独立访问多个入口的玩家会出现在多行。订单与安装需由业务系统确认。</p></details></section>'
  );
}

function operationsPage(o) {
  const r = o.report,
    total = r.total;
  const select =
    '<select id="ops-filter" aria-label="按游戏筛选"><option value="">所有游戏</option>' +
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
    '</select>';
  const period =
    '<select id="ops-days" aria-label="报表时间范围">' +
    [
      ['7', '最近 7 天'],
      ['30', '最近 30 天'],
      ['', '全部时间'],
    ]
      .map(
        ([v, n]) =>
          '<option value="' + v + '" ' + (v === state.opsDays ? 'selected' : '') + '>' + n + '</option>',
      )
      .join('') +
    '</select>';
  const experiment = (e) => {
    const result = e.result,
      arms = Object.entries(e.arms).map(([k, v]) => ({
        ...v,
        variant: k === 'control' ? 'A 对照' : 'B 实验',
      }));
    return (
      '<section class="card"><div class="cap"><h3>' +
      h(e.title) +
      '</h3>' +
      pill(labels[e.status] || e.status) +
      '</div><p class="muted">到期 ' +
      date(e.due) +
      ' · 玩家固定分组</p>' +
      metricsTable(arms, [['variant', '版本组']]) +
      (result
        ? '<p class="compact">' +
          h(result.conclusion) +
          ' 实际差值 ' +
          h(fmt(result.delta)) +
          '，预期 ' +
          h(result.expected.join(' 至 ')) +
          '。' +
          (result.interval_95_pp
            ? ' 点击率差的 95% 区间 ' + h(result.interval_95_pp.join(' 至 ')) + ' 个百分点。'
            : '') +
          '</p>'
        : '') +
      (e.status === 'decide'
        ? '<div class="actions">' +
          button('promote', '全量实验版', 'primary', 'data-id="' + e.id + '"') +
          button('rollback', '回到对照版', 'secondary', 'data-id="' + e.id + '"') +
          '</div>'
        : '') +
      '</section>'
    );
  };
  return (
    heading(
      '运营与实验',
      '',
      '<div class="actions">' + select + button('analyze', '发起分析', 'primary') + '</div>',
    ) +
    '<div class="section-head"><h2>玩家参与</h2>' +
    period +
    '</div>' +
    stats([
      ['玩家开局', total.starts],
      ['开局玩家', total.players],
      ['通关率', total.win_rate == null ? '—' : total.win_rate + '%'],
      ['人均游玩秒数', total.seconds_per_player],
      ['次日回访 / 成熟首玩', fmt(total.d1_returned) + ' / ' + fmt(total.d1_eligible)],
      ['次日留存率', total.d1_rate == null ? '—' : total.d1_rate + '%'],
    ]) +
    channelSection(o) +
    '<div class="section-head"><h2>游戏与关卡</h2></div><section class="card">' +
    (r.games.length
      ? metricsTable(r.games, [['game', '游戏']])
      : '<p class="muted">发布游戏后，玩家的第一局会出现在这里。</p>') +
    '<details><summary>逐关数据与口径</summary><p class="muted">' +
    h(o.definitions) +
    '</p>' +
    metricsTable(r.levels, [
      ['game', '游戏'],
      ['rev', '版本 ID'],
      ['level', '关卡'],
    ]) +
    '</details>' +
    (r.quadrants?.length ? '<details><summary>局级诊断</summary><p class="muted">达到关卡时限一半计为长局，两次失误及以上计为多失误。只统计支持回放诊断的自然完局。</p><div class="tablescroll"><table><thead><tr><th>版本 / 关卡</th><th>局型</th><th>局数</th><th>使用提示</th><th>可观察救援</th></tr></thead><tbody>' +
      r.quadrants.map(q => '<tr><td>' + h(q.rev.slice(0, 7)) + ' / ' + h(q.level) + '</td><td>' +
        (q.slow_round ? '长局' : '短局') + ' · ' + (q.repeated_errors ? '多失误' : '少失误') +
        '</td><td>' + h(q.rounds) + '</td><td>' + h(q.hinted) + '</td><td>' + h(q.rescue_observed) + '</td></tr>').join('') +
      '</tbody></table></div></details>' : '') + '</section>' +
    '<div id="ops-proposals" class="section-head"><h2>运营提案</h2></div><div class="list">' +
    (o.proposals.length
      ? o.proposals
          .map(
            (p) =>
              '<button class="proposal-row" data-do="proposal" data-id="' +
              p.id +
              '"><span class="grow"><strong>' +
              h(p.doc.bet?.title || p.title) +
              '</strong><small>' +
              h(p.kind === 'new_game' ? '新游戏立项' : '存量迭代') +
              ' · ' +
              h(p.title) +
              ' · ' +
              date(p.created) +
              '</small></span>' +
              pill(labels[p.status] || p.status, p.status === 'review') +
              '<span>↗</span></button>',
          )
          .join('')
      : empty('有正式开局后，可以发起分析。专家意见和预注册预期会随提案一起提交。')) +
    '</div>' +
    '<div id="ops-experiments" class="section-head"><h2>A/B 实验</h2></div><div class="list">' +
    (o.experiments.length
      ? o.experiments.map(experiment).join('')
      : empty('迭代提案通过评审并发布新版本后，会在这里开始分流。')) +
    '</div>' +
    '<div class="section-head"><h2>外部变更</h2>' +
    button('change-log', '记录变更', 'small-btn') +
    '</div>' +
    (o.changes?.length
      ? '<section class="card">' +
        o.changes.map((c) => '<p>' + h(date(c.at)) + ' · ' + h(c.text) + '</p>').join('') +
        '</section>'
      : empty('活动、流量入口或埋点变更可作为归因依据。')) +
    '<div class="section-head"><h2>每日批次</h2>' +
    button('batch', '核对昨日报表', 'small-btn') +
    '</div><section class="card"><p class="muted">北京时间 08:00 处理前一自然日，每 30 分钟巡检。</p>' +
    o.batches
      .map(
        (b) =>
          '<div class="row spread compact">' +
          button('batch-detail', h(b.day), 'ghost', 'data-id="' + h(b.day) + '"') +
          pill(labels[b.status] || b.status) +
          '</div>',
      )
      .join('') +
    '</section>'
  );
}

function memoryPage(m, skills) {
  const tabs = {
    knowledge: '知识评审',
    rules: '核心规则',
    history: '历史记录',
    session: '项目记录',
    preferences: '制作偏好',
    skills: '技能手册',
  };
  let body = '';
  if (state.memoryTab === 'knowledge')
    body = m.entries.length
      ? m.entries
          .map(
            (k) =>
              '<section class="card"><div class="cap"><h3>' +
              h(k.title) +
              '</h3>' +
              pill(labels[k.status] || k.status) +
              '</div><p>' +
              h(k.text) +
              '</p><small>' +
              h(k.grade) +
              ' · 检索权重 ' +
              h(k.confidence) +
              ' · ' +
              date(k.created) +
              '</small>' +
              (k.reviewed_at ? '<p>审核于 ' + date(k.reviewed_at) + (k.review_note ? ' · ' + h(k.review_note) : '') +
                (k.replacement ? ' · 替代记录 ' + h(k.replacement) : '') + '</p>' : '') +
              '<details><summary>原始结算证据</summary>' +
              kv(k.evidence) +
              '</details>' +
              (k.status === 'pending'
                ? '<div class="actions">' +
                  button('know-yes', '采纳', 'primary', 'data-id="' + k.id + '"') +
                  button('know-no', '驳回', 'secondary', 'data-id="' + k.id + '"') +
                  '</div>'
                : '') +
              '</section>',
          )
          .join('')
      : empty('实验结算后，带有证据、适用范围和置信度的知识会进入评审。');
  if (state.memoryTab === 'rules')
    body =
      '<section class="card"><h3>工作室规则</h3><p class="compact">' +
      h(m.rules) +
      '</p></section>' +
      m.games
        .map(
          (g) =>
            '<section class="card"><h3>' +
            h(g.title) +
            '</h3><p class="compact">北极星 · ' +
            h(state.overview.metrics[g.metric]) +
            '</p><p class="muted">' +
            h(g.bounds) +
            '</p></section>',
        )
        .join('');
  if (state.memoryTab === 'history')
    body = m.history.length
      ? '<section class="card">' + historyHtml([...m.history].reverse()) + '</section>'
      : empty('生产、审核和发布动作会保存为原始事件。');
  if (state.memoryTab === 'session') body = gameRows(state.overview.games);
  if (state.memoryTab === 'preferences') {
    const gid = parts()[2] || '';
    const fields = [
      ['audience', '目标玩家', 200], ['visual_style', '画面风格', 240], ['controls', '操作习惯', 200],
      ['audio', '声音偏好', 160], ['avoid', '希望避开的设计', 300],
    ];
    body = '<section class="card preference-panel"><label>编辑范围<select id="preference-scope"><option value="">我在此浏览器的默认偏好</option>' +
      m.games.map(g => '<option value="' + h(g.id) + '"' + (g.id === gid ? ' selected' : '') + '>' + h(g.title) + '</option>').join('') +
      '</select></label><p class="muted">' +
      (gid ? '保存后，下次发起制作、主动返工或运营提案时生效。' : '新建项目会复制这些偏好。已有项目可在上方单独选择。') +
      '</p><form id="preferences" class="fields">' + fields.map(([key, label, max]) =>
        '<label>' + label + '<input name="' + key + '" maxlength="' + max + '" value="' + h(state.preferenceData.values[key] || '') + '"></label>').join('') +
      '<div class="actions"><button class="primary" type="submit">保存偏好</button><small>版本 ' + h(state.preferenceData.version) + '</small></div></form></section>';
  }
  if (state.memoryTab === 'skills')
    body = skills
      .map(
        (s) =>
          '<details class="card"><summary>' +
          h(
            {
              'design-gameplay': '游戏与交互设计',
              'build-playable-levels': '游戏开发与关卡验证',
              'review-game-experiments': '运营实验评审',
              'iterate-live-game': '存量游戏改版',
              'evaluate-new-game': '新游戏立项',
            }[s.name] || s.name,
          ) +
          '</summary><p class="mono muted">' +
          h(s.name) +
          ' @ ' +
          h(s.revision) +
          '</p><p class="muted">适用角色 · ' + h(s.roles.join(' / ')) + '</p><div class="skill-text">' +
          h(s.body) +
          '</div></details>',
      )
      .join('');
  return (
    heading('知识与记忆') +
    '<div class="section-head"><div class="tabs wrap">' +
    Object.entries(tabs)
      .map(([k, v]) => button('memtab', v, k === state.memoryTab ? 'on' : '', 'data-key="' + k + '"'))
      .join('') +
    '</div></div><div class="list">' +
    body +
    '</div>'
  );
}

export { memoryPage, operationsPage };
