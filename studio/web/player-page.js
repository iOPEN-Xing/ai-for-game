import { mountPlayer } from '/static/play-host.js';
const root = document.querySelector('#player');
const isSample = location.pathname === '/sample';
const harbor = isSample && new URLSearchParams(location.search).get('game') === 'harbor';
if (isSample) {
  const other = document.querySelector('#other-sample');
  other.hidden = false;
  const link = other.querySelector('a');
  link.href = harbor ? '/sample' : '/sample?game=harbor';
  link.textContent = harbor ? '试玩《潮汐信标》' : '试玩《港湾引航》';
}
mountPlayer(root, location.pathname.split('/').pop(), {
  sample: isSample && (harbor ? 'harbor' : true),
  campaign: location.pathname.startsWith('/play/')
    ? new URLSearchParams(location.search).get('entry')
    : null,
}).catch((e) => (root.textContent = e.message));
