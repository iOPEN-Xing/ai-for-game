import { mountPlayer, sampleGames } from '/static/play-host.js';
const root = document.querySelector('#player');
const isSample = location.pathname === '/sample';
const selected = sampleGames.find(game => game.id === new URLSearchParams(location.search).get('game')) || sampleGames[0];
if (isSample) {
  const other = document.querySelector('#other-sample');
  other.hidden = false;
  for (const game of sampleGames.filter(game => game !== selected)) {
    const link = document.createElement('a');
    link.href = game.url;
    link.textContent = '试玩《' + game.title + '》';
    other.append(link);
  }
}
mountPlayer(root, location.pathname.split('/').pop(), {
  sample: isSample && selected.id,
  campaign: location.pathname.startsWith('/play/')
    ? new URLSearchParams(location.search).get('entry')
    : null,
}).catch((e) => (root.textContent = e.message));
