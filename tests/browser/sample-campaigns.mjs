// Independent players follow the game's published rules using real canvas input.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';

function shortestRoute(chart) {
  const {cols, rows, locked, link, lit} = chart;
  const dark = lit.reduce((mask, on, i) => on ? mask : mask | (1 << i), 0);
  const moves = [];
  for (let i = 0; i < lit.length; i++) {
    if (locked.includes(i)) continue;
    const x = i % cols, y = Math.floor(i / cols);
    let change = 1 << i;
    for (const [a,b] of [[x-1,y],[x+1,y],[x,y-1],[x,y+1]]) {
      if (a >= 0 && b >= 0 && a < cols && b < rows) change |= 1 << (b * cols + a);
    }
    if (link.includes(i)) change |= 1 << link[1 - link.indexOf(i)];
    moves.push([i,change]);
  }
  const queue = [dark], previous = new Map([[dark, null]]);
  for (const current of queue) {
    if (current === 0) break;
    for (const [cell, mask] of moves) {
      const next = current ^ mask;
      if (!previous.has(next)) { previous.set(next, [current, cell]); queue.push(next); }
    }
  }
  assert.ok(previous.has(0), 'Every published board must have a legal solution');
  const taps = [];
  for (let state = 0; state !== dark;) {
    const [prior, cell] = previous.get(state);
    taps.push(cell); state = prior;
  }
  return taps.reverse();
}

export async function playCampaign(page, site, postal) {
  const filename = postal ? 'sample-post.json' : 'sample-game.json';
  const project = postal ? 'mountain-post' : 'tidal-beacon';
  const sample = await (await page.request.get(new URL('/static/'+filename,site).href)).json();
  const generator = await readFile(new URL('../../examples/'+project+'/level-generator.js',import.meta.url),'utf8');
  const parameters = runInNewContext(generator + '\nparameters', Object.create(null));
  const canvas = page.frameLocator('iframe').locator('canvas');
  for (let i = 1; i <= sample.count; i++) {
    await page.getByText('画面就绪', {exact:true}).waitFor();
    assert.equal(await page.locator('.pill').textContent(), '第 ' + i + ' / ' + sample.count + ' 关');
    const number = sample.chapters.findLastIndex(c => c.start <= i) + 1;
    const start = sample.chapters[number-1].start, next = sample.chapters[number]?.start || sample.count+1;
    assert.equal(await page.locator('.chapter-heading strong').textContent(), sample.chapters[number-1].title);
    await page.getByRole('button',{name:'开始游戏'}).click();
    await page.getByText('游戏中', {exact:true}).waitFor();
    const box = await canvas.boundingBox();
    assert.ok(Math.abs(box.width / box.height - (postal ? 1.5 : 0.8)) < 0.015, 'The board must retain its designed proportions');
    const chart = parameters(i, sample.count, sample.origin.seed, {number,level:i-start+1,length:next-start}).content;
    if (postal) {
      const lanes = chart.items.map(([mark,transfer]) => (mark+transfer+3)%3);
      // Miss once deliberately on every level, then re-deliver the same letter.
      for (const lane of [(lanes[0]+1)%3, ...lanes]) {
        await canvas.click({position:{x:box.width*(lane+.5)/3,y:box.height*.76}});
      }
    } else {
      const solution = shortestRoute(chart);
      assert.equal(solution.length, chart.par, 'Published par must be the actual shortest solution');
      for (const cell of solution) {
        const position = {
          x: box.width * (0.16 + 0.68 * (cell % chart.cols) / (chart.cols - 1)),
          y: box.height * (0.29 + 0.40 * Math.floor(cell/chart.cols) / (chart.rows - 1)),
        };
        await canvas.tap({position});
      }
    }
    const advance = page.getByRole('button', {name: i === sample.count ? '重玩首关' : '下一关'});
    await advance.click();
  }
  await page.getByText('第 1 / 12 关', {exact:true}).waitFor();
}
