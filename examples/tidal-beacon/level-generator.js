// Twelve solvable light boards; par is the independently checked minimum number of taps.
const harborCharts = [
  {"cols": 3, "rows": 3, "dark": [1, 4, 5, 6], "link": [], "locked": [], "par": 2},
  {"cols": 3, "rows": 3, "dark": [0, 1, 2, 3, 4, 5, 8], "link": [], "locked": [], "par": 2},
  {"cols": 3, "rows": 3, "dark": [0, 4, 5, 8], "link": [], "locked": [], "par": 3},
  {"cols": 3, "rows": 3, "dark": [3, 5, 6], "link": [], "locked": [], "par": 3},
  {"cols": 3, "rows": 4, "dark": [0, 4, 6, 7, 10], "link": [0, 11], "locked": [], "par": 3},
  {"cols": 3, "rows": 4, "dark": [0, 2, 3, 4, 8, 9, 11], "link": [2, 9], "locked": [], "par": 3},
  {"cols": 3, "rows": 4, "dark": [2, 4, 7, 10, 11], "link": [0, 11], "locked": [], "par": 4},
  {"cols": 3, "rows": 4, "dark": [0, 2, 3, 4, 5, 6, 7, 8, 9, 11], "link": [2, 9], "locked": [], "par": 4},
  {"cols": 4, "rows": 4, "dark": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15], "link": [0, 15], "locked": [5], "par": 4},
  {"cols": 4, "rows": 4, "dark": [0, 4, 5, 6, 8, 9], "link": [3, 12], "locked": [5], "par": 5},
  {"cols": 4, "rows": 4, "dark": [1, 3, 4, 8, 11, 13, 14], "link": [0, 15], "locked": [5, 10], "par": 5},
  {"cols": 4, "rows": 4, "dark": [1, 8, 9, 10], "link": [3, 12], "locked": [5, 10], "par": 6},
];

function parameters(index, total, seed) {
  const chart = harborCharts[index - 1];
  const {cols, rows} = chart;
  function mirror(cell) {
    const x = cell % cols, y = Math.floor(cell / cols);
    return ((seed & 1) ? rows - 1 - y : y) * cols + ((seed & 2) ? cols - 1 - x : x);
  }
  const dark = chart.dark.map(mirror);
  return {
    quota: chart.par, seconds: 85 + 5 * chart.par, radius: 0.085, size: 7, pace: 1.2,
    content: {
      cols, rows, lit: Array.from({length: cols * rows}, (_, i) => !dark.includes(i)),
      link: chart.link.map(mirror), locked: chart.locked.map(mirror),
      par: chart.par, limit: chart.par + (index < 5 ? 4 : 3),
    },
  };
}
