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
