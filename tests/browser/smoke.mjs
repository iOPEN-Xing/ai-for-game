import assert from 'node:assert/strict';
import { chromium } from 'playwright-core';

const team = new URL(process.env.TEAM_URL || 'http://127.0.0.1:7860/');
const playerSite = new URL(process.env.PLAYER_URL || 'https://localhost/');
const key = process.env.STUDIO_TEST_KEY;
assert.ok(key, 'Set STUDIO_TEST_KEY for a disposable studio');
assert.ok(['127.0.0.1', 'localhost', '[::1]'].includes(team.hostname), 'Use a local test studio');
const browser = await chromium.launch({ executablePath: process.env.CHROME_BIN || undefined });
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
  for (const [path, title, width, height] of [
    ['/sample?game=harbor', '港湾引航', 1280, 860],
    ['/sample', '潮汐信标', 390, 844],
  ]) {
    const context = await browser.newContext({
      viewport: { width, height }, locale: 'zh-CN',
      ignoreHTTPSErrors: playerSite.hostname === 'localhost',
    });
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(new URL(path, playerSite).href);
    await page.getByText('画面就绪', { exact: true }).waitFor();
    assert.equal(await page.locator('h1').textContent(), title);
    const fits = await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth &&
      document.querySelector('.act').getBoundingClientRect().bottom <= innerHeight);
    assert.ok(fits, 'The game and start button must fit the viewport');
    await page.getByRole('button', { name: '开始游戏' }).click();
    await page.getByText('游戏中', { exact: true }).waitFor();
    await page.getByRole('button', { name: '结束本局' }).click();
    await page.getByRole('button', { name: '再玩一局' }).waitFor();
    await context.close();
  }
  assert.deepEqual(errors, []);
  console.log('Team screens and desktop/mobile play flows passed.');
} finally {
  await browser.close();
}
