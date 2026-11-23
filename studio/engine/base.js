// Cartridge ABI. Coordinates are normalized. State and drawing commands are JSON.
function baseStart(L) {
  return {
    score: 0,
    hits: 0,
    elapsed: 0,
    done: false,
    won: false,
    cell: L.from || 0,
    lane: 1,
    mistakes: 0,
  };
}
function inCell(index, L) {
  return { x: ((index % L.size) + 0.5) / L.size, y: (Math.floor(index / L.size) + 0.5) / L.size };
}
function baseStep(s, e, L) {
  if (s.done) return s;
  if (e.type === 'tick') {
    s.elapsed += e.dt;
    if (s.elapsed >= L.seconds) {
      s.done = true;
      return s;
    }
  }
  const point = L.points[s.hits % L.points.length];
  if (L.family === 'trail' && (e.type === 'tap' || e.type === 'key')) {
    let next = s.cell;
    if (e.type === 'tap') next = Math.floor(e.y * L.size) * L.size + Math.floor(e.x * L.size);
    else next += { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -L.size, ArrowDown: L.size }[e.key] || 0;
    if (neighbors(s.cell, L.size).includes(next) && L.grid[next]) {
      s.cell = next;
      s.score++;
      s.hits++;
      if (next === L.to) s.won = s.done = true;
    }
  } else if (L.family === 'drift') {
    if (e.type === 'tap') s.lane = Math.min(2, Math.floor(e.x * 3));
    if (e.type === 'key')
      s.lane = Math.max(0, Math.min(2, s.lane + ({ ArrowLeft: -1, ArrowRight: 1 }[e.key] || 0)));
    if (e.type === 'tick' && Math.floor(s.elapsed / L.pace) > s.hits + s.mistakes) {
      if (s.lane === point.lane) {
        s.score += 10;
        s.hits++;
      } else s.mistakes++;
    }
    if (s.hits >= L.quota) s.won = s.done = true;
  } else if (L.family !== 'trail' && e.type === 'tap') {
    if (Math.hypot(e.x - point.x, e.y - point.y) <= L.radius) {
      s.hits++;
      s.score += 10;
    } else s.mistakes++;
    if (s.hits >= L.quota) s.won = s.done = true;
  }
  return s;
}
function baseDraw(s, L) {
  const commands = [],
    point = L.points[s.hits % L.points.length];
  if (L.family === 'trail') {
    const w = 1 / L.size;
    for (let i = 0; i < L.grid.length; i++)
      if (!L.grid[i]) {
        const p = inCell(i, L);
        commands.push({
          kind: 'rect',
          x: p.x - w * 0.46,
          y: p.y - w * 0.46,
          w: w * 0.92,
          h: w * 0.92,
          color: 'ink',
        });
      }
    commands.push({ kind: 'circle', ...inCell(L.to, L), r: w * 0.36, color: 'accent' });
    commands.push({ kind: 'sprite', ...inCell(s.cell, L), r: w * 0.46 });
  } else if (L.family === 'drift') {
    for (let i = 1; i < 3; i++)
      commands.push({ kind: 'line', x: i / 3, y: 0.02, x2: i / 3, y2: 0.98, color: 'soft' });
    const phase = (s.elapsed % L.pace) / L.pace;
    commands.push({
      kind: 'circle',
      x: (point.lane + 0.5) / 3,
      y: 0.09 + phase * 0.74,
      r: 0.045,
      color: 'accent',
    });
    commands.push({ kind: 'sprite', x: (s.lane + 0.5) / 3, y: 0.88, r: 0.07 });
  } else {
    for (let i = 1; i < 4; i++) {
      const upcoming = L.points[(s.hits + i) % L.points.length];
      commands.push({ kind: 'ring', x: upcoming.x, y: upcoming.y, r: 0.014, color: 'soft' });
    }
    commands.push({
      kind: 'ring',
      x: point.x,
      y: point.y,
      r: L.radius * (1.1 + 0.1 * Math.sin(s.elapsed * 4)),
      color: 'accent',
    });
    commands.push({ kind: 'sprite', x: point.x, y: point.y, r: L.radius * 0.8 });
  }
  return commands;
}
function baseWitness(s, L) {
  if (L.family === 'trail') {
    const next = route(L.grid, L.size, s.cell, L.to)[0];
    return { type: 'tap', ...inCell(next, L) };
  }
  const point = L.points[s.hits % L.points.length];
  if (L.family === 'drift') {
    if (s.lane !== point.lane) return { type: 'tap', x: (point.lane + 0.5) / 3, y: 0.8 };
    return { type: 'tick', dt: 0.1 };
  }
  return { type: 'tap', x: point.x, y: point.y };
}
