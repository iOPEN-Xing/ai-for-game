import { endpoint } from '../routes.js';

// One subscription per project view. A full refresh is needed only when a
// checkpoint, stage or job changes. Token updates preserve the active form.
export function watchRevision(detail, changed, expired, fallback) {
  if (typeof EventSource === 'undefined') {
    fallback();
    return () => {};
  }
  const source = new EventSource(endpoint('revision_events', {rid: detail.revision.id}));
  let failures = 0;
  const close = () => source.close();
  source.addEventListener('progress', event => {
    failures = 0;
    const next = JSON.parse(event.data);
    const before = detail.progress;
    if (['stage', 'serial', 'history_id', 'job_state', 'attempts'].some(k => next[k] !== before[k]) || next.terminal) {
      close();
      changed();
      return;
    }
    if (next.stage === 'interpret' && next.summary !== before.summary) {
      const target = document.getElementById('research-progress');
      if (target) target.textContent = next.summary || '后台正在生成本阶段的交付物。';
      detail.revision.docs.research_draft = next.summary;
      before.summary = next.summary;
    }
  });
  source.addEventListener('session_closed', () => { close(); expired(); });
  source.onerror = () => {
    if (++failures >= 2 || source.readyState === EventSource.CLOSED) {
      close();
      fallback();
    }
  };
  return close;
}
