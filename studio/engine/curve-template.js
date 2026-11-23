function parameters(index, total, seed) {
  return {
    quota: 3 + index,
    seconds: 60,
    radius: Math.max(0.052, 0.092 - index * 0.003),
    size: 7 + 2 * Math.min(3, Math.floor((index - 1) / 2)),
    pace: Math.max(0.55, 1.6 - index * 0.08),
  };
}
