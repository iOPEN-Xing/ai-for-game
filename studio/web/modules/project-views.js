import { esc as h } from '../play-host.js';
import { state } from './state.js';
import { artifact, back, button, empty, heading, historyHtml, needsReview, pill } from './ui.js';
import { examples, stages } from './labels.js';
import { endpoint } from '../routes.js';

function gameRows(games) {
  if (!games.length)
    return empty(
      '这里会显示你的游戏、所在阶段和当前版本。',
      button('create', '创建第一个项目 ↗', 'ghost'),
    );
  return (
    '<div class="list">' +
    games
      .map(
        (g) =>
          '<a class="game-row" href="#project/' +
          g.id +
          '/' +
          g.rev +
          '"><img alt="" class="thumb" src="/static/reference-' +
          (g.family || 'custom') +
          '.png"><span class="grow"><strong>' +
          h(g.title) +
          '</strong><small>V' +
          g.num +
          ' · ' +
          h(state.overview.metrics[g.metric]) +
          '</small></span>' +
          pill(g.job_state === 'failed' ? '等待重试' : state.overview.stages[g.stage], needsReview(g)) +
          '<span class="arrow">↗</span></a>',
      )
      .join('') +
    '</div>'
  );
}

function home() {
  const games = state.overview.games;
  const waiting = games.filter(needsReview);
  const tasks = [
    [
      '制作待办',
      '方向、验收和返工',
      waiting.length,
      waiting.length === 1 ? '#project/' + waiting[0].id + '/' + waiting[0].rev : '#projects/review',
    ],
    ['运营提案', '等待确认的改版建议', state.overview.reviews, '#ops/all/proposals'],
    ['实验决策', '选择全量发布或回滚', state.overview.decisions, '#ops/all/experiments'],
    ['知识评审', '可供下一版引用的经验', state.overview.knowledge_pending, '#memory/knowledge'],
  ];
  const drafts = examples
    .map(
      (x, i) =>
        '<button class="draft-row" data-do="example" data-index="' +
        i +
        '"><img src="/static/reference-' +
        x.type +
        '.png" alt=""><span><strong>' +
        h(x.title) +
        '</strong><small>' +
        h(x.tag) +
        '</small></span><span class="draft-add" aria-hidden="true">＋</span></button>',
    )
    .join('');
  const today = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: 'long',
    day: 'numeric',
    weekday: 'long',
  }).format(new Date());
  return (
    heading(
      '工作室总览',
      '',
      '<div class="head-actions"><time>' +
        h(today) +
        '</time>' +
        button('create', '新建游戏项目', 'primary add-button') +
        '</div>',
    ) +
    '<div class="front-desk"><section class="sample-cover" aria-labelledby="sample-name"><div class="cover-copy"><span class="sample-type"><span class="pixel-light" aria-hidden="true"></span>可玩样片</span><h2 id="sample-name">潮汐信标</h2><p>预判灯阵的连锁反应，点亮整座港湾。</p><a class="play-sample" href="/sample" target="_blank" rel="noopener"><span aria-hidden="true">▶</span> 试玩示例</a></div><div class="cover-spec">灯阵解谜 <span></span> 3 章 12 关</div></section>' +
    '<section class="dispatch"><h2>待我处理</h2><ul>' +
    tasks
      .map(
        ([label, desc, n, href]) =>
          '<li><a href="' +
          href +
          '"><span><strong>' +
          label +
          '</strong><small>' +
          desc +
          '</small></span><b class="' +
          (n ? 'has-tasks' : '') +
          '">' +
          n +
          '</b></a></li>',
      )
      .join('') +
    '</ul></section></div>' +
    '<div class="library-grid"><section><div class="section-head"><h2>最近项目</h2><a class="text-link" href="#projects">全部项目</a></div>' +
    (games.length
      ? gameRows(games.slice(0, 5))
      : '<div class="empty-library"><span class="cartridge-icon" aria-hidden="true"><i></i></span><div><h3>创建你的第一个游戏</h3><p>写下玩法和目标，或选一份草稿开始制作。</p>' +
        button('create', '新建项目', 'text-link') +
        '</div></div>') +
    '</section><section><div class="section-head"><h2>玩法草稿</h2></div><div class="draft-list">' +
    drafts +
    '</div></section></div>'
  );
}

function projects() {
  const filtered = state.overview.games.filter(
    (g) => !state.listFilter || (state.listFilter === 'review' ? needsReview(g) : g.stage === state.listFilter),
  );
  return (
    heading('游戏项目', '', button('create', '新建游戏项目', 'primary add-button')) +
    '<div class="section-head"><h2>项目列表</h2><div class="actions"><select aria-label="按生产阶段筛选" id="list-filter"><option value="">全部阶段</option><option value="review" ' +
    (state.listFilter === 'review' ? 'selected' : '') +
    '>等待审核</option>' +
    stages
      .map(
        (s) =>
          '<option value="' +
          s +
          '" ' +
          (s === state.listFilter ? 'selected' : '') +
          '>' +
          state.overview.stages[s] +
          '</option>',
      )
      .join('') +
    '</select></div></div>' +
    (filtered.length || !state.listFilter ? gameRows(filtered) : empty('当前阶段没有项目。'))
  );
}

function gate(d) {
  const r = d.revision,
    s = r.stage,
    failed = d.job?.state === 'failed';
  let title,
    body = '';
  if (failed) {
    title = '任务等待重试';
    body =
      '<p>' +
      h(d.job.error) +
      '</p>' +
      button('retry', '从断点重试', 'primary') +
      button('revise', '修改后重做');
  } else if (s === 'references') {
    title = '选取调研参考图';
    body = '<p>' + h(r.docs.discovery.search_status) + '。选 1 至 4 张，分析它们的玩法和画面。</p>' +
      '<form id="select-references"><div class="research-gallery">' +
      r.docs.discovery.references.map(ref => '<div><label><img loading="lazy" alt="" src="' + h(ref.image) +
        '"><span><input type="checkbox" name="reference" value="' + h(ref.id) + '"> ' + h(ref.title) +
        '</span></label>' + (ref.source ? '<a target="_blank" rel="noopener noreferrer" href="' + h(ref.source) +
        '">' + h(ref.credit) + ' ↗</a>' : '<small>' + h(ref.credit) + '</small>') + '</div>').join('') +
      '</div><div class="actions"><button class="primary" type="submit">分析所选图片</button>' + button('revise', '重新检索') + '</div></form>';
  } else if (s === 'direction') {
    title = '选择玩法方向';
    body =
      '<p>' +
      h(r.docs.research.summary) +
      '</p><form id="directions"><div class="directions">' +
      r.docs.research.directions
        .map(
          (x, i) =>
            '<label class="direction"><img alt="' +
            h(x.visual) +
            '" src="' +
            h(x.references?.[0]?.image || '/static/reference-' + x.mechanic + '.png') +
            '"><input required type="radio" name="choice" value="' +
            i +
            '"><strong>' +
            h(x.title) +
            '</strong><span>' +
            h(x.pitch) +
            '</span><span>' +
            h(x.interaction) +
            '</span></label>',
        )
        .join('') +
      '</div><div class="actions"><button type="submit" class="primary">确认方向</button>' +
      button('revise', '修改需求') +
      '</div></form>';
    const refs = r.docs.research.directions
      .map((x, i) =>
        x.references?.length
          ? button('refs', '参考图 · ' + h(x.title), 'small-btn', 'data-index="' + i + '"')
          : '',
      )
      .join('');
    if (refs) body += '<div class="actions refs">' + refs + '</div>';
  } else if (s === 'plan') {
    title = '审阅生产方案';
    body =
      '<p>' +
      h(r.docs.gdd.core_loop) +
      '</p>' +
      ['gdd', 'art', 'levels']
        .map(
          (k) =>
            '<details class="doc"><summary>' +
            h(d.artifacts[k]) +
            '</summary>' +
            artifact(k, r.docs[k]) +
            '</details>',
        )
        .join('') +
      '<div class="actions">' +
      button('approve', '确认方案并构建', 'primary') +
      button('art-media', '查看视听资产') +
      button('revise', '提出修改', 'ghost') +
      '</div>';
  } else if (s === 'quality') {
    title = '试玩验收';
    const plan = r.docs.levels;
    const startAt = plan?.chapters ? '<label>试玩起点 <select id="preview-level">' +
      Array.from({length: plan.count}, (_, i) => {
        const chapter = plan.chapters.findLast(c => c.start <= i + 1);
        return '<option value="' + (i + 1) + '">第 ' + (i + 1) + ' 关 · ' + h(chapter.title) + '</option>';
      }).join('') + '</select></label>' : '';
    body =
      '<p>已验证 ' +
      r.docs.validation.levels +
      ' 个关卡。' +
      h(r.docs.quality_report?.playtest_focus?.join(' ') || '完成一局试玩后，可以确认验收。') +
      '</p><div class="actions">' +
      startAt +
      button('preview', '▷ 试玩游戏', 'primary') +
      button('accept', '确认验收', 'secondary', d.tested ? '' : 'disabled') +
      button('revise', '退回修改', 'ghost') +
      '</div>';
  } else if (s === 'ready') {
    title = '版本等待发布';
    body =
      '<p>验收已通过。发布后，玩家可从独立链接进入' +
      (r.proposal && r.parent ? '，本次迭代将开启 A/B 分流' : '') +
      '。</p><div class="actions">' +
      button('publish-confirm', '确认发布', 'primary') +
      button('preview', '再次试玩') +
      button('revise', '退回修改', 'ghost') +
      '</div>';
  } else if (s === 'released') {
    title = '已发布的版本';
    body =
      '<p>正式对局将进入游戏与关卡报表。</p><div class="actions"><a target="_blank" rel="noopener" class="primary" href="' +
      h(new URL(endpoint('player_page', {gid: d.game.id}), state.overview.public_origin || location.origin).href) +
      '">打开玩家入口 ↗</a><a class="secondary" href="#ops/' +
      d.game.id +
      '">查看运营数据</a><a class="ghost" href="#ops/' +
      d.game.id +
      '/channels">管理活动入口</a></div>';
  } else {
    title = state.overview.stages[s] + '进行中';
    body =
      '<p id="research-progress">' + h(s === 'interpret' && r.docs.research_draft ? r.docs.research_draft : '后台正在生成本阶段的交付物。') + '</p><span class="pill">后台任务 · ' +
      h(d.job?.state === 'queued' ? '已排队' : '执行中') +
      '</span>';
  }
  return (
    '<section class="card gate"><div class="cap"><h2>' +
    h(title) +
    '</h2>' +
    pill(state.overview.stages[s], true) +
    '</div>' +
    body +
    '</section>'
  );
}

function workflow(d) {
  const r = d.revision,
    doc = r.docs;
  const nodes = [
    ['route_research', '制作人'],
    ['research', '玩法调研'],
    ['gdd', '策划'],
    ['art', '美术与音频'],
    ['levels', '关卡设计'],
    ...(doc.level_brief
      ? [['level_code', '关卡开发'], ['game_code', '游戏开发']]
      : [['game_code', '游戏开发'], ['level_code', '关卡开发']]),
    ['validation', '构建验收'],
  ];
  return (
    '<section class="flow-board"><h3>生产画布</h3><div class="workflow">' +
    nodes
      .map(
        ([k, t], i) =>
          (i ? '<i>→</i>' : '') +
          '<button class="' +
          (doc[k] ? 'complete' : '') +
          '" data-do="artifact" data-key="' +
          k +
          '" ' +
          (!doc[k] ? 'disabled' : '') +
          '>' +
          h(t) +
          '</button>',
      )
      .join('') +
    '</div><span class="muted">点击已完成节点查看对应产物</span></section>'
  );
}

function project(d) {
  const r = d.revision,
    g = d.game;
  const versions =
    '<select id="version" aria-label="查看版本">' +
    d.versions
      .map(
        (v) =>
          '<option value="' +
          v.id +
          '" ' +
          (v.id === r.id ? 'selected' : '') +
          '>V' +
          v.num +
          ' · ' +
          state.overview.stages[v.stage] +
          '</option>',
      )
      .join('') +
    '</select>';
  let html =
    back('projects', '游戏项目') +
    heading(g.title, '', '<div class="actions">' + versions + '</div>') +
    '<div class="section-head"><div class="tabs">' +
    button('classic', '会话视图', state.view === 'classic' ? 'on' : '') +
    button('canvas', '画布视图', state.view === 'canvas' ? 'on' : '') +
    '</div><span class="muted">北极星 · ' +
    h(state.overview.metrics[g.metric]) +
    '</span></div>';
  html +=
    '<div class="workgrid"><div class="col">' +
    (state.view === 'canvas' ? workflow(d) : '') +
    gate(d) +
    '<section class="card"><h3>制作会话</h3><p class="muted compact">当前版本的评审、产物和团队意见</p>' +
    historyHtml(d.history) +
    '<form class="note-form" id="note"><input aria-label="制作意见" required maxlength="1400" placeholder="记录给制作团队的意见"><button class="secondary">记录</button></form></section></div>';
  html +=
    '<aside class="col"><section class="card"><h3>创意与边界</h3><p class="compact">' +
    h(g.brief) +
    '</p><hr class="divider"><small>行动边界</small><p class="muted">' +
    h(g.bounds) +
    '</p></section><section class="card"><h3>版本产物</h3>' +
    Object.entries(r.docs)
      .map(
        ([k, v]) =>
          '<details class="doc"><summary>' +
          h(d.artifacts[k] || k) +
          '</summary>' +
          artifact(k, v) +
          '</details>',
      )
      .join('') +
    (r.bundle
      ? '<hr class="divider"><div class="actions">' +
        button('blueprints', '关卡蓝图', 'small-btn') +
        button('download', '下载版本包', 'small-btn') +
        '</div>'
      : '') +
    '</section></aside></div>';
  return html;
}

export { gameRows, home, project, projects };
