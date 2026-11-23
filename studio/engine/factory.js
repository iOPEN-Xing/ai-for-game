// Both the blueprint builder and the live worker use this exact seed stream.
function rng(seed) {
  let state = seed >>> 0;
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 4294967296;
  };
}
function neighbors(i, size) {
  const x = i % size,
    y = Math.floor(i / size);
  return [
    [x - 1, y],
    [x + 1, y],
    [x, y - 1],
    [x, y + 1],
  ]
    .filter(([a, b]) => a >= 0 && b >= 0 && a < size && b < size)
    .map(([a, b]) => b * size + a);
}
function route(grid, size, from, to) {
  const queue = [from],
    previous = new Map([[from, -1]]);
  for (let head = 0; head < queue.length; head++) {
    const current = queue[head];
    if (current === to) {
      const path = [];
      for (let i = to; i !== from; i = previous.get(i)) path.push(i);
      return path.reverse();
    }
    for (const next of neighbors(current, size)) {
      if (grid[next] && !previous.has(next)) {
        previous.set(next, current);
        queue.push(next);
      }
    }
  }
  return [];
}
function maze(size, random) {
  const cells = Array(size * size).fill(0),
    stack = [size + 1];
  cells[size + 1] = 1;
  while (stack.length) {
    const at = stack[stack.length - 1],
      x = at % size,
      y = Math.floor(at / size);
    const choices = [
      [x + 2, y],
      [x - 2, y],
      [x, y + 2],
      [x, y - 2],
    ].filter(([a, b]) => a > 0 && b > 0 && a < size - 1 && b < size - 1 && !cells[b * size + a]);
    if (!choices.length) {
      stack.pop();
      continue;
    }
    const [nx, ny] = choices[Math.floor(random() * choices.length)],
      next = ny * size + nx;
    cells[(at + next) / 2] = cells[next] = 1;
    stack.push(next);
  }
  return cells;
}
function makeLevel(index, total, seed, family, parameters) {
  const p = parameters(index, total, seed),
    derived = (seed + Math.imul(index, 2654435761)) >>> 0;
  const random = rng(derived);
  const level = {
    index,
    total,
    seed: derived,
    family,
    quota: p.quota,
    seconds: p.seconds,
    radius: p.radius,
    size: p.size,
    pace: p.pace,
    points: [],
  };
  for (let i = 0; i < p.quota + 4; i++)
    level.points.push({
      x: 0.15 + random() * 0.7,
      y: 0.15 + random() * 0.68,
      lane: Math.floor(random() * 3),
    });
  if (family === 'trail') {
    if (p.grid !== undefined) {
      return { ...level, grid: p.grid, from: p.from, to: p.to };
    }
    level.from = p.size + 1;
    level.to = p.size * (p.size - 1) - 2;
    let bestLength = -1;
    for (let attempt = 0; attempt < 4; attempt++) {
      const grid = maze(p.size, random),
        length = route(grid, p.size, level.from, level.to).length;
      if (length > bestLength) {
        level.grid = grid;
        bestLength = length;
      }
    }
  }
  return level;
}
