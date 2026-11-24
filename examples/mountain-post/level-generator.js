// GLM-5.4's three-chapter dispatch schedule, serialized as [marked station, transfer].
function parameters(index, total, seed, chapter) {
  const quotas = [4,5,6,7,7,8,8,9,10,11,12,14];
  const paces = [1.9,1.75,1.6,1.5,1.4,1.25,1.55,1.15,1.05,.95,.85,.75];
  const quota = quotas[index - 1], pace = paces[index - 1];
  let state = (seed ^ Math.imul(index,2654435761) ^ Math.imul(chapter.number,40503)) | 0;
  function random() {
    state = (state + 0x6D2B79F5) | 0;
    let n = Math.imul(state ^ (state >>> 15), state | 1);
    n = (n + Math.imul(n ^ (n >>> 7), n | 61)) ^ n;
    return ((n ^ (n >>> 14)) >>> 0) / 4294967296;
  }
  // The third dispatch in chapter two gives players a breather after frequent transfers.
  const transfers = [
    [[0],[0],[0],[0]],
    [[0,0,1],[0,1],[0,0,0,1],[0,1]],
    [[0,-1,0],[0,-1,1],[1,0,-1,1,-1],[-1,0,1]],
  ];
  const pattern = transfers[chapter.number-1][chapter.level-1];
  const items = [];
  for (let i = 0; i < quota; i++) {
    const station = Math.floor(random()*3);
    const position = index === 12 ? Math.floor(random()*pattern.length) : i % pattern.length;
    items.push([station,pattern[position]]);
  }
  return {quota,pace,seconds:Math.max(12,Math.round(quota*pace*1.35 + 4)),
    size:5+2*Math.min(4,Math.floor(index/3)),radius:.15,content:{items}};
}
