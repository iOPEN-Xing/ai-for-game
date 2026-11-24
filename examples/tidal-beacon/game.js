// The harbor's switch rules and shortest-solution search were authored with GLM-5.4.
function start(L) {
  return {
    lit: L.content.lit.slice(), moves: 0, hits: 0, mistakes: 0, score: 0, elapsed: 0,
    done: false, won: false, lastSwitch: -1, lastAt: -2, blocked: false,
  };
}

function station(cell, L) {
  const {cols, rows} = L.content;
  return {x: 0.16 + 0.68 * (cell % cols) / (cols - 1),
          y: 0.29 + 0.40 * Math.floor(cell / cols) / (rows - 1)};
}

function switches(cell, chart) {
  const x = cell % chart.cols, y = Math.floor(cell / chart.cols);
  const cells = new Set([cell]);
  if (x > 0) cells.add(cell - 1);
  if (x + 1 < chart.cols) cells.add(cell + 1);
  if (y > 0) cells.add(cell - chart.cols);
  if (y + 1 < chart.rows) cells.add(cell + chart.cols);
  if (chart.link.includes(cell)) cells.add(chart.link[1 - chart.link.indexOf(cell)]);
  return [...cells];
}

function step(s, e, L) {
  if (s.done) return s;
  if (e.type === 'tick') {
    s.elapsed += e.dt;
    if (s.elapsed >= L.seconds) s.done = true;
    return s;
  }
  if (e.type !== 'tap') return s;
  const chart = L.content;
  const cell = s.lit.findIndex((_, i) => {
    const p = station(i, L);
    return Math.hypot(e.x - p.x, (e.y - p.y) * 1.25) <= 0.081;
  });
  if (cell < 0) return s;
  s.lastSwitch = cell;
  s.lastAt = s.elapsed;
  s.blocked = chart.locked.includes(cell);
  if (s.blocked) { s.mistakes++; return s; }
  for (const other of switches(cell, chart)) s.lit[other] = !s.lit[other];
  s.moves++;
  s.hits++;
  s.won = s.lit.every(Boolean);
  s.done = s.won || s.moves >= chart.limit;
  s.score = s.won ? 1000 + (chart.limit - s.moves) * 100 : s.lit.filter(Boolean).length * 10;
  return s;
}

function witness(s, L) {
  // Adjacent Gray-code subsets differ by one switch, so each new board costs one XOR.
  const chart = L.content;
  const target = s.lit.reduce((mask, lit, i) => lit ? mask : mask | (1 << i), 0);
  const legal = s.lit.map((_, i) => i).filter(i => !chart.locked.includes(i));
  const toggles = legal.map(i => switches(i, chart).reduce((mask, j) => mask | (1 << j), 0));
  let board = 0, subset = 0, count = 0, best = chart.limit - s.moves + 1, answer = -1;
  for (let n = 1; n < (1 << legal.length); n++) {
    const bit = n & -n, i = 31 - Math.clz32(bit);
    subset ^= bit;
    board ^= toggles[i];
    count += (subset & bit) ? 1 : -1;
    if (board === target && count < best) {
      best = count;
      answer = legal[31 - Math.clz32(subset & -subset)];
      if (best === 1) break;
    }
  }
  return answer < 0 ? {type: 'tick', dt: 0.1} : {type: 'tap', ...station(answer, L)};
}

function draw(s, L) {
  const shapes = [];
  const line = (x, y, x2, y2, color) => shapes.push({kind:'line', x, y, x2, y2, color});
  const rect = (x, y, w, h, color) => shapes.push({kind:'rect', x, y, w, h, color});
  const mark = (kind, x, y, r, color) => shapes.push({kind, x, y, r, color});
  const polygon = (x, y, points, color, opacity = 1) => shapes.push({kind:'polygon', x, y, points, color, opacity});
  const text = (x, y, value, size, color) => shapes.push({kind:'text', x, y, text:value, size, color});
  const water = '#112F40', contour = '#305364', cable = '#88D5C6', lit = '#FFD478', pale = '#D6E8E3';
  const chart = L.content, off = s.lit.filter(value => !value).length;
  rect(0, 0, 1, 1, water);

  // Draw the three harbors as distinct nautical charts, with a common navigational legend.
  const shores = [
    [[0,.31],[.045,.26],[.030,.19],[.084,.13],[.075,.092],[.145,.063],[.159,0]],
    [[0,.20],[.047,.167],[.085,.166],[.121,.143],[.095,.09],[.146,.055],[.21,0]],
    [[0,.3],[.032,.285],[.063,.213],[.041,.166],[.08,.15],[.102,.077],[.17,0]],
  ];
  const shore = shores[L.chapter.number - 1];
  for (const corner of [0,1]) {
    for (const [scale, tone] of [[1.16,'#1A4352'],[1,'#38605F'],[0.94,'#2B4C4F']]) {
      const edge = [[0,0], ...shore].map(([x,y]) => corner ? [1-x*scale,1-y*scale] : [x*scale,y*scale]);
      polygon(0,0,edge,tone);
    }
  }
  const shoals = [[.084,.885],[.118,.901],[.89,.073]];
  for (const [x,y] of shoals) {
    polygon(x,y,[[-.024,0],[-.011,-.009],[.004,-.011],[.019,-.002],[.012,.006],[-.009,.007]],'#406461');
  }
  for (let i = 0; i < 11; i++) {
    const x = .07 + i * .086, h = i % 5 === 0 ? .012 : .006;
    line(x,.955,x,.955-h,contour);
  }
  text(0.25, 0.115, '待亮信标', 0.032, pale);
  text(0.75, 0.115, '剩余步数', 0.032, pale);
  text(0.25, 0.174, String(off).padStart(2, '0'), 0.071, lit);
  text(0.75, 0.174, String(chart.limit - s.moves).padStart(2, '0'), 0.071, pale);
  line(0.5, 0.105, 0.5, 0.175, contour);

  for (let i = 0; i < s.lit.length; i++) {
    const p = station(i, L);
    if (i % chart.cols + 1 < chart.cols) { const q = station(i+1,L); line(p.x,p.y,q.x,q.y,contour); }
    if (Math.floor(i / chart.cols) + 1 < chart.rows) { const q = station(i+chart.cols,L); line(p.x,p.y,q.x,q.y,contour); }
  }
  if (chart.link.length) {
    const a = station(chart.link[0],L), b = station(chart.link[1],L);
    // Offset the cable from the grid. The terminal rings identify its exact endpoints.
    line(a.x,a.y,a.x+0.05,a.y-0.052,cable);
    line(a.x+0.05,a.y-0.052,b.x+0.05,b.y-0.052,cable);
    line(b.x+0.05,b.y-0.052,b.x,b.y,cable);
  }
  const age = s.elapsed - s.lastAt;
  const affected = age < 0.48 && s.lastSwitch >= 0 ? switches(s.lastSwitch, chart) : [];
  for (let i = 0; i < s.lit.length; i++) {
    if (!s.lit[i]) continue;
    const {x,y} = station(i,L), dir = i % 2 ? -1 : 1;
    polygon(x,y-.03,[[0,0],[dir*.128,-.040],[dir*.14,-.010]],lit,.15);
  }
  for (let i = 0; i < s.lit.length; i++) {
    const {x, y} = station(i,L);
    const r = chart.cols === 4 ? 0.044 : 0.052;
    mark('circle',x,y,r+.009,water);
    if (s.lit[i]) {
      mark('circle',x,y,r,'#384B47');
      mark('ring',x,y,r,'#D4AA68');
      shapes.push({kind:'sprite', asset:'harbor-light', x, y:y-r*.28, r:r*1.32});
    } else {
      mark('circle',x,y,r,'#183C4C');
      mark('ring',x,y,r,'#96B5B9');
      line(x-r*.42,y,x+r*.42,y,'#AAC4C5');
    }
    if (chart.link.includes(i)) mark('ring',x,y,r+.013,cable);
    if (chart.locked.includes(i)) {
      const w = r + 0.016, h = w / 1.25;
      line(x-w,y-h,x+w,y-h,cable); line(x+w,y-h,x+w,y+h,cable);
      line(x+w,y+h,x-w,y+h,cable); line(x-w,y+h,x-w,y-h,cable);
    }
    if (affected.includes(i) && (!s.blocked || s.lastSwitch === i)) {
      mark('ring',x,y,r+0.012+age*0.065,s.blocked?'#F59E83':'#F7DEAB');
    }
  }
  const t = s.blocked && age < 1 ? '锁站需由邻灯或缆线点亮' :
    L.chapter.number === 1 ? '点灯会翻转本灯和上下左右四邻' :
    L.chapter.number === 2 ? '双环灯塔由同一条缆线连接' : '方框内的灯塔不能直接操作';
  text(0.5,0.812,t,0.038,pale);
  text(.5,.893,'最短航线  ·  '+chart.par+' 步',.031,'#9BB8BA');
  if (s.done) {
    rect(0.1,0.405,0.8,0.18,water); line(0.15,0.423,0.85,0.423,lit);
    text(0.5,0.488,s.won?'全港点亮':s.moves >= chart.limit?'步数用尽':'潮汐已退',0.069,lit);
    text(0.5,0.546,s.won?'已用 '+s.moves+' 步 · 最短 '+chart.par+' 步':'再试一次，留意连锁变化',0.036,pale);
  }
  return shapes;
}
