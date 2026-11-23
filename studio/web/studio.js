import { api } from './api-client.js';
import { endpoint } from './routes.js';
import { $, button, close, dialog, heading, root, toast } from './modules/ui.js';
import { parts, state } from './modules/state.js';
import { names } from './modules/labels.js';
import { home, project, projects } from './modules/project-views.js';
import { memoryPage, operationsPage } from './modules/operations-views.js';
import { bindActions } from './modules/actions.js';

let routeVersion = 0, timer = null;

const tab = () => parts()[0] || 'home';

function login() {
  $('#logout').hidden = true;
  $('#model').textContent = '';
  root.innerHTML =
    heading('登录制作室', '输入团队口令，打开项目、审批和运营报表。') +
    '<form id="login" class="card fields" style="max-width:420px"><label>制作台口令<input type="password" required autocomplete="current-password"></label><button class="primary">进入工作室</button><span class="err" role="alert"></span></form>';
  $('#login').onsubmit = async (e) => {
    e.preventDefault();
    try {
      await api(endpoint('login'), { key: e.target.querySelector('input').value });
      await refresh();
    } catch (err) {
      e.target.querySelector('.err').textContent = err.message;
    }
  };
}

function listeners() {
  const period = $('#ops-days');
  if (period)
    period.onchange = () => {
      state.opsDays = period.value;
      refresh();
    };
  const f = $('#list-filter');
  if (f)
    f.onchange = () => {
      location.hash = f.value ? 'projects/' + f.value : 'projects';
    };
  const v = $('#version');
  if (v)
    v.onchange = () => {
      location.hash = 'project/' + state.current.game.id + '/' + v.value;
    };
  const of = $('#ops-filter');
  if (of)
    of.onchange = () => {
      location.hash = 'ops' + (of.value ? '/' + of.value : '');
    };
  const preferenceScope = $('#preference-scope');
  if (preferenceScope) preferenceScope.onchange = () => {
    location.hash = 'memory/preferences' + (preferenceScope.value ? '/' + preferenceScope.value : '');
  };
  const prefForm = $('#preferences');
  if (prefForm) prefForm.onsubmit = async e => {
    e.preventDefault();
    const save = prefForm.querySelector('button');
    save.disabled = true;
    try {
      const path = preferenceScope.value ? endpoint('edit_project_preferences', {gid: preferenceScope.value}) : endpoint('edit_personal_preferences');
      await api(path, {version: state.preferenceData.version, values: Object.fromEntries(new FormData(prefForm))}, 'PUT');
      await refresh();
      toast('偏好已保存');
    } catch (err) { toast(err.message); } finally { save.disabled = false; }
  };
  const referenceForm = $('#select-references');
  if (referenceForm) referenceForm.onsubmit = async (e) => {
    e.preventDefault();
    const ids = new FormData(referenceForm).getAll('reference');
    if (ids.length < 1 || ids.length > 4) return toast('请选择 1 至 4 张参考图');
    try { await decide('select_references', { reference_ids: ids }); } catch (err) { toast(err.message); }
  };
  const direction = $('#directions');
  if (direction)
    direction.onsubmit = async (e) => {
      e.preventDefault();
      try {
        await decide('choose', { choice: Number(new FormData(direction).get('choice')) });
      } catch (err) {
        toast(err.message);
      }
    };
  const note = $('#note');
  if (note)
    note.onsubmit = async (e) => {
      e.preventDefault();
      try {
        await api(endpoint('note', {rid: state.current.revision.id}), {
          note: note.querySelector('input').value,
        });
        await refresh();
      } catch (err) {
        toast(err.message);
      }
    };
}

async function refresh(poll = false) {
  const seq = ++routeVersion,
    route = parts(),
    page = route[0] || 'home';
  clearTimeout(timer);
  let again = false;
  try {
    const snapshot = await api(endpoint('overview'));
    if (seq !== routeVersion) return;
    state.overview = snapshot;
    $('#logout').hidden = !snapshot.can_sign_out;
    $('#model').textContent = 'AgentScope / ' + state.overview.model;
    document.title = (names[page] || names.home) + ' · 回路制作室';
    document.querySelectorAll('[data-nav]').forEach((a) => {
      const active = a.dataset.nav === (page === 'project' ? 'projects' : page);
      a.classList.toggle('active', active);
      if (active) a.setAttribute('aria-current', 'page');
      else a.removeAttribute('aria-current');
    });
    let html,
      skip = false;
    if (page === 'project') {
      const d = await api(endpoint('game', {gid: route[1]}, route[2] ? {rev: route[2]} : undefined));
      if (seq !== routeVersion) return;
      again = ['research', 'interpret', 'design', 'build'].includes(d.revision.stage) && d.job?.state !== 'failed';
      skip =
        poll &&
        state.current &&
        state.current.revision.id === d.revision.id &&
        state.current.revision.stage === d.revision.stage &&
        state.current.history.length === d.history.length &&
        state.current.job?.state === d.job?.state &&
        state.current.revision.docs.research_draft === d.revision.docs.research_draft;
      state.current = d;
      if (!skip) html = project(d);
    } else if (page === 'ops') {
      state.opsGame = route[1] && route[1] !== 'all' ? route[1] : '';
      const query = new URLSearchParams();
      if (state.opsGame) query.set('game', state.opsGame);
      if (state.opsDays) query.set('days', state.opsDays);
      const d = await api(endpoint('ops', {}, query));
      if (seq !== routeVersion) return;
      again = d.proposals.some((p) => p.status === 'analyzing');
      skip = poll && JSON.stringify(d) === JSON.stringify(state.opsData);
      state.opsData = d;
      if (!skip) html = operationsPage(d);
    } else if (page === 'memory') {
      const tabs = ['knowledge', 'rules', 'history', 'session', 'preferences', 'skills'];
      const selected = tabs.includes(route[1]) ? route[1] : 'knowledge';
      const preferencePath = route[2]
        ? endpoint('project_preferences', { gid: route[2] })
        : endpoint('personal_preferences');
      const [memory, skills, preferences] = await Promise.all([
        api(endpoint('memory')),
        api(endpoint('skills')),
        selected === 'preferences' ? api(preferencePath) : null,
      ]);
      if (seq !== routeVersion) return;
      state.memoryTab = selected;
      state.memoryData = memory;
      state.skillData = skills;
      state.preferenceData = preferences;
      html = memoryPage(memory, skills);
    } else {
      state.listFilter = page === 'projects' ? route[1] || '' : '';
      html = page === 'projects' ? projects() : home();
    }
    if (!skip) {
      root.innerHTML = html;
      listeners();
      if (!poll && page === 'ops' && ['proposals', 'experiments', 'channels'].includes(route[2]))
        document.getElementById('ops-' + route[2])?.scrollIntoView();
    }
  } catch (err) {
    if (seq !== routeVersion) return;
    if (err.status === 401) login();
    else {
      root.innerHTML = heading('暂时无法打开页面', err.message, button('refresh', '重试'));
      again = poll;
    }
  } finally {
    if (again && seq === routeVersion) {
      const whenIdle = () => {
        if (seq !== routeVersion) return;
        if (dialog.open || document.activeElement?.matches('input,textarea,select'))
          timer = setTimeout(whenIdle, 2500);
        else refresh(true);
      };
      timer = setTimeout(whenIdle, 2500);
    }
  }
}

async function decide(action, extra = {}) {
  const r = state.current.revision;
  await api(endpoint('decision', {rid: r.id}), { serial: r.serial, action, ...extra });
  await refresh();
}

$('#logout').onclick = async () => {
  try {
    await api(endpoint('logout'), {});
    location.reload();
  } catch (err) {
    toast(err.message);
  }
};

$('#menu').onclick = () => {
  const open = document.body.classList.toggle('nav-open');
  $('#menu').setAttribute('aria-expanded', String(open));
  $('#menu').setAttribute('aria-label', open ? '收起导航' : '展开导航');
};

document.querySelector('.skip-link').onclick = (event) => {
  event.preventDefault();
  root.focus();
};

window.addEventListener('hashchange', () => {
  document.body.classList.remove('nav-open');
  $('#menu').setAttribute('aria-expanded', 'false');
  $('#menu').setAttribute('aria-label', '展开导航');
  close();
  window.scrollTo(0, 0);
  refresh();
});

bindActions({ refresh, decide, listeners });

refresh();
