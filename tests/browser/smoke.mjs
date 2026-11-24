import assert from 'node:assert/strict';
import { chromium } from 'playwright-core';
import { playCampaign } from './sample-campaigns.mjs';

const team = new URL(process.env.TEAM_URL || 'http://127.0.0.1:7860/');
const playerSite = new URL(process.env.PLAYER_URL || 'https://localhost/');
const key = process.env.STUDIO_TEST_KEY;
assert.ok(key, 'Set STUDIO_TEST_KEY for a disposable studio');
assert.ok(['127.0.0.1', 'localhost', '[::1]'].includes(team.hostname), 'Use a local test studio');
const browser = await chromium.launch({ executablePath: process.env.CHROME_BIN || undefined });
function pathToGoal(level) {
  const queue = [level.from], parent = new Map([[level.from, null]]);
  for (const cell of queue) {
    if (cell === level.to) break;
    const x = cell % level.size, y = Math.floor(cell / level.size);
    for (const [a, b] of [[x-1,y], [x+1,y], [x,y-1], [x,y+1]]) {
      const next = b * level.size + a;
      if (a >= 0 && a < level.size && b >= 0 && b < level.size && level.grid[next] && !parent.has(next)) {
        parent.set(next, cell);
        queue.push(next);
      }
    }
  }
  assert.ok(parent.has(level.to), 'The delivered board must have a path to its goal');
  const path = [];
  for (let cell = level.to; cell !== level.from; cell = parent.get(cell)) path.push(cell);
  return path.reverse();
}

const errors = [];
try {
  const teamPage = await browser.newPage();
  teamPage.on('pageerror', error => errors.push(error.message));
  await teamPage.goto(team.href);
  await teamPage.locator('#login input').fill(key);
  await teamPage.locator('#login button').click();
  await teamPage.locator('.front-desk').waitFor();
  for (const [hash, selector] of [
    ['projects', '#list-filter'], ['ops', '#ops-days'],
    ['memory/preferences', '#preferences'], ['memory/skills', '#app details'],
  ]) {
    await teamPage.evaluate(hash => { location.hash = hash; }, hash);
    await teamPage.locator(selector).first().waitFor();
  }
  if (process.env.STUDIO_TEST_GAME) {
    const gid = process.env.STUDIO_TEST_GAME;
    const gamePath = '/api/games/' + gid;
    const fixture = await (await teamPage.request.get(new URL(gamePath, team).href)).json();
    const streamPath = '/api/revisions/' + fixture.revision.id + '/events';
    const last = await teamPage.evaluate(path => new Promise((resolve, reject) => {
      const events = new EventSource(path);
      events.addEventListener('progress', event => {
        events.close(); resolve({id: event.lastEventId, value: JSON.parse(event.data)});
      });
      events.onerror = () => { events.close(); reject(Error('Private revision stream unavailable')); };
    }), streamPath);
    assert.equal(last.value.terminal, true);
    assert.equal(last.value.stage, 'released');
    assert.match(last.id, /^[a-f0-9]{64}$/);
    assert.equal((await teamPage.request.get(new URL(streamPath, playerSite).href, {ignoreHTTPSErrors:true})).status(), 404);

    // Serve a held intermediate snapshot to exercise the real project subscriber
    // without scheduling any paid jobs in CI.
    const active = {...fixture.progress, stage:'interpret', serial:fixture.revision.serial + 1, job_state:'running', attempts:1, summary:null};
    const draft = {...fixture, progress:active, job:{state:'running', attempts:1}, revision:{...fixture.revision, stage:'interpret', serial:active.serial}};
    let fullRequests = 0, streamRequests = 0;
    await teamPage.route('**' + gamePath, route => {
      fullRequests++;
      return route.fulfill({json:draft});
    });
    await teamPage.route('**' + streamPath, route => {
      streamRequests++;
      const event = { ...active, summary:'一条来自调研流的独立观察', terminal:false };
      return route.fulfill({contentType:'text/event-stream', body:'retry: 60000\nid: fixture\nevent: progress\ndata: ' + JSON.stringify(event) + '\n\n'});
    });
    await teamPage.evaluate(id => {location.hash = 'project/' + id;}, gid);
    await teamPage.getByText('一条来自调研流的独立观察', {exact:true}).waitFor();
    assert.equal(fullRequests,1);
    assert.equal(streamRequests,1);
    await teamPage.evaluate(() => {location.hash = 'projects';});
    await teamPage.locator('#list-filter').waitFor();
    await teamPage.unroute('**' + streamPath);
    await teamPage.unroute('**' + gamePath);
  }
  await teamPage.getByRole('button', { name: '退出制作台' }).click();
  await teamPage.locator('#login input').waitFor();
  assert.equal((await teamPage.request.get(new URL('/api/studio', team).href)).status(), 401);
  for (const [path, title, width, height] of [
    ['/sample?game=harbor', '港湾引航', 1280, 860],
    ['/sample?game=post', '山间邮局', 1100, 750],
    ['/sample', '潮汐信标', 390, 844],
  ]) {
    const context = await browser.newContext({
      viewport: { width, height }, hasTouch: width < 500, locale: 'zh-CN',
      ignoreHTTPSErrors: playerSite.hostname === 'localhost',
    });
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    const outer = await page.goto(new URL(path, playerSite).href);
    assert.match(outer.headers()['strict-transport-security'], /max-age=31536000/);
    assert.match(outer.headers()['content-security-policy'], /frame-ancestors 'none'/);
    await page.getByText('画面就绪', { exact: true }).waitFor();
    assert.equal(await page.locator('h1').textContent(), title);
    const fits = await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth &&
      document.querySelector('.act').getBoundingClientRect().bottom <= innerHeight);
    assert.ok(fits, 'The game and start button must fit the viewport');
    if (path !== '/sample?game=harbor') {
      await playCampaign(page, playerSite, path === '/sample?game=post');
      await context.close();
      continue;
    }
    await page.getByRole('button', { name: '开始游戏' }).click();
    await page.getByText('游戏中', { exact: true }).waitFor();
    await page.getByRole('button', { name: '结束本局' }).click();
    await page.getByRole('button', { name: '再玩一局' }).waitFor();
    await context.close();
  }
  if (process.env.STUDIO_TEST_GAME) {
    const context = await browser.newContext({ignoreHTTPSErrors: playerSite.hostname === 'localhost'});
    await context.route('https://v1-fixture.invalid/**', route => route.fulfill({body:'活动已打开'}));
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    const url = new URL('/play/' + process.env.STUDIO_TEST_GAME, playerSite);
    url.searchParams.set('entry', process.env.STUDIO_TEST_CAMPAIGN);
    const opened = page.waitForResponse(r => r.url().endsWith('/open') && r.request().method() === 'POST');
    await page.goto(url.href);
    const round = await (await opened).json();
    const level = round.game_info.level_entry;
    await page.getByRole('button', {name:'开始游戏'}).click();
    await page.getByText('游戏中', {exact:true}).waitFor();
    const canvas = page.frameLocator('iframe').locator('canvas');
    const box = await canvas.boundingBox();
    const finished = page.waitForResponse(r => r.url().endsWith('/event') && r.request().postDataJSON()?.event === 'end');
    for (const cell of pathToGoal(level)) {
      await canvas.click({position:{
        x: (cell % level.size + .5) * box.width / level.size,
        y: (Math.floor(cell / level.size) + .5) * box.height / level.size,
      }});
    }
    assert.ok((await finished).ok(), 'Server replay must accept the browser score');
    await page.locator('input[name="comment"]').fill('浏览器试玩验收');
    await page.getByRole('button', {name:'提交反馈'}).click();
    await page.getByText('已记录本局反馈').waitFor();
    const action = context.waitForEvent('response', r => r.url().includes('/go/') && r.request().method() === 'POST');
    const popup = context.waitForEvent('page');
    await page.getByRole('button', {name:'查看试玩活动'}).click();
    const redirected = await action;
    assert.equal(redirected.status(), 303, 'A completed campaign round must record the click and redirect');
    await (await popup).waitForURL('https://v1-fixture.invalid/offer');
    await context.close();
    console.log('Published game, verified natural finish, player feedback and campaign redirect passed.');
  }
  assert.deepEqual(errors, []);
  console.log('Team screens and desktop/mobile play flows passed.');
} finally {
  await browser.close();
}
