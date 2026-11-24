function playtest(L) {
  const chapterGame = Boolean(L.chapter);
  const pointers = ['tap', 'press', 'move', 'release'];
  const keys = ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Space', 'Enter', 'KeyW', 'KeyA', 'KeyS', 'KeyD'];
  const kinds = ['rect', 'circle', 'ring', 'line', 'polygon', 'text', 'sprite'];
  const copy = value => JSON.parse(JSON.stringify(value));
  let checkedScenes = 0;

  function visible(c) {
    if (c.opacity !== undefined && (!Number.isFinite(c.opacity) || c.opacity < 0 || c.opacity > 1)) {
      throw Error('opacity must be between 0 and 1');
    }
    let left = c.x, right = c.x, top = c.y, bottom = c.y;
    if (c.kind === 'rect') {
      if (!Number.isFinite(c.w) || !Number.isFinite(c.h)) throw Error('rect needs finite w and h');
      if (!c.w || !c.h) return false;
      left = Math.min(c.x, c.x + c.w); right = Math.max(c.x, c.x + c.w);
      top = Math.min(c.y, c.y + c.h); bottom = Math.max(c.y, c.y + c.h);
    } else if (c.kind === 'line') {
      if (!Number.isFinite(c.x2) || !Number.isFinite(c.y2)) throw Error('invalid line');
      left = Math.min(c.x, c.x2);
      right = Math.max(c.x, c.x2);
      top = Math.min(c.y, c.y2);
      bottom = Math.max(c.y, c.y2);
    } else if (c.kind === 'polygon') {
      if (!Array.isArray(c.points) || c.points.length < 3 || c.points.length > 32 ||
          !c.points.every(p => Array.isArray(p) && p.length === 2 && p.every(Number.isFinite))) {
        throw Error('polygon needs 3..32 finite coordinate pairs');
      }
      const xs = c.points.map(p => c.x + p[0]), ys = c.points.map(p => c.y + p[1]);
      left = Math.min(...xs); right = Math.max(...xs);
      top = Math.min(...ys); bottom = Math.max(...ys);
      if (left === right || top === bottom) return false;
    } else if (c.kind === 'text') {
      if (!String(c.text ?? '').trim()) return false;
    } else {
      if (!Number.isFinite(c.r) || c.r < 0) throw Error('invalid radius');
      if (!c.r) return false;
      left -= c.r;
      right += c.r;
      top -= c.r;
      bottom += c.r;
    }
    return c.opacity !== 0 && left <= 1 && right >= 0 && top <= 1 && bottom >= 0;
  }

  function scene(state) {
    const before = JSON.stringify(state);
    const picture = draw(state, L);
    if (JSON.stringify(state) !== before) throw Error('draw mutated game state');
    if (!Array.isArray(picture) || !picture.length || picture.length > 500) throw Error('invalid scene');
    let onBoard = false;
    for (const [i, c] of picture.entries()) {
      if (!c || !kinds.includes(c.kind) || !Number.isFinite(c.x) || !Number.isFinite(c.y)) {
        throw Error('draw[' + i + '] needs kind (' + kinds.join('/') + ') and numeric x,y; got ' + JSON.stringify(c).slice(0,100));
      }
      if (chapterGame && visible(c)) onBoard = true;
    }
    if (chapterGame && !onBoard) throw Error('all drawing commands are outside the board');
    checkedScenes++;
    return picture;
  }

  function playerEvent(e) {
    if (!e || ![...pointers, 'tick', 'key', 'keyup'].includes(e.type)) throw Error('invalid witness input');
    if (pointers.includes(e.type)) {
      if (!(e.x >= 0 && e.x <= 1 && e.y >= 0 && e.y <= 1)) throw Error('invalid tap');
      const position = v => Math.min(0.9999, Math.round(v * 10000) / 10000);
      return chapterGame ? {type: e.type, x: position(e.x), y: position(e.y)} : e;
    }
    if (e.type === 'tick') {
      if (!(e.dt > 0 && e.dt <= 0.101)) throw Error('invalid tick');
      return chapterGame ? {type: 'tick', dt: Math.max(1, Math.min(100, Math.round(e.dt * 1000))) / 1000} : e;
    }
    if (chapterGame && !keys.includes(e.key)) throw Error('unsupported player key');
    return chapterGame ? {type: e.type, key: e.key} : e;
  }

  function mistakeReplay(trace) {
    if (!trace.some(e => e.type === 'tap' || e.type === 'key')) return 'not_observed';
    let before = start(L);
    let decisions = 0;
    for (const e of trace) {
      if (decisions >= 8 || before.done) break;
      let alternatives = [];
      if (e.type === 'tap') {
        alternatives = [[1-e.x,e.y],[e.x,1-e.y],[.05,e.y],[.5,e.y],[.95,e.y],[.5,.5]]
          .map(([x,y]) => playerEvent({type:'tap',x,y}));
      } else if (e.type === 'key') {
        alternatives = ['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].map(key => ({type:'key', key}));
      }
      if (alternatives.length) decisions++;
      for (const alternative of alternatives) {
        const after = step(copy(before), alternative, L);
        if (!(after.mistakes > (before.mistakes || 0))) continue;
        if (after.done) return after.won ? 'recovered' : 'immediate_loss';
        let state = after;
        for (let i = 0; i < 2200 && !state.done; i++) {
          let event;
          try { event = playerEvent(witness(copy(state), copy(L))); }
          catch { return 'no_recovery_input'; }
          const previous = JSON.stringify(state);
          state = step(state, event, L);
          if (JSON.stringify(state) === previous) return 'unfinished';
        }
        return state.won && state.done ? 'recovered' : state.done ? 'lost_on_replay' : 'unfinished';
      }
      before = step(before, e, L);
    }
    return 'not_observed';
  }

  let state = start(L);
  if (state.done || !Number.isFinite(state.score)) throw Error('invalid initial state');
  const opening = scene(state), firstScene = JSON.stringify(opening);
  let reference = chapterGame ? baseStart(L) : null;
  let distinct = chapterGame && JSON.stringify(baseDraw(reference, L)) !== firstScene;
  let changed = false, midChecked = false, inputs = 0;
  const trace = [];
  while (!state.done && trace.length < 2200) {
    const event = playerEvent(witness(copy(state), copy(L)));
    if (event.type !== 'tick') inputs++;
    trace.push({...event});
    state = step(state, event, L);
    if (chapterGame && !distinct) reference = baseStep(reference, event, L);
    if (chapterGame && (state.done || (inputs === 1 && event.type !== 'tick') || (!midChecked && inputs >= 3))) {
      const current = JSON.stringify(scene(state));
      if (current !== firstScene) changed = true;
      if (!distinct) distinct = reference.won !== state.won || reference.done !== state.done ||
        reference.hits !== state.hits || current !== JSON.stringify(baseDraw(reference, L));
      if (inputs >= 3) midChecked = true;
    }
  }
  if (!state.done || !state.won || !Number.isFinite(state.score) || !inputs) {
    const where = {moves:trace.length, inputs, quota:L.quota, elapsed:state.elapsed, hits:state.hits,
      mistakes:state.mistakes, score:state.score, done:state.done, won:state.won, last:trace.slice(-2)};
    throw Error('witness cannot win ' + JSON.stringify(where).slice(0,450));
  }
  let replay = start(L);
  for (const event of trace) replay = step(replay, event, L);
  if (JSON.stringify(replay) !== JSON.stringify(state)) throw Error('input replay diverged');
  const proof = {moves:trace.length, score:state.score, commands:opening.length, playerInputs:inputs};
  if (chapterGame) {
    if (!changed) throw Error('the board gives no visible response during play');
    const tapsOnly = trace.some(e => e.type === 'tap') && !trace.some(e => ['press','move','release'].includes(e.type));
    if (tapsOnly) {
      let touch = start(L);
      for (const e of trace) {
        const events = e.type === 'tap' ? [{...e,type:'press'}, e, {...e,type:'release'}] : [e];
        for (const input of events) if (!touch.done) touch = step(touch, input, L);
      }
      if (!touch.done || !touch.won || touch.score !== state.score) {
        throw Error('a real touch press/tap/release sequence diverged from the winning tap replay');
      }
    }
    let idle = start(L);
    for (let i = 0; i <= Math.ceil(L.seconds * 10) + 1 && !idle.done; i++) {
      idle = step(idle, {type:'tick', dt:0.1}, L);
    }
    if (!idle.done || idle.won) throw Error('no-input play must end in a timeout loss');
    scene(idle);
    // Keep the successful timing but always aim at one corner or press the same key.
    // A timing game may still win. The reviewer interprets this against the promised mechanic.
    let fixed = start(L);
    for (const e of trace) {
      if (fixed.done) break;
      const event = pointers.includes(e.type) ? {...e, x:0.03, y:0.03} :
        (e.type === 'key' || e.type === 'keyup') ? {...e, key:'Space'} : e;
      fixed = step(fixed, event, L);
    }
    Object.assign(proof, {checkedScenes, idleTimeout:true, differsFromStarter:distinct,
      fixedInputWon:Boolean(fixed.done && fixed.won), afterMistake:mistakeReplay(trace),
      touchTapReplay:tapsOnly});
  }
  return proof;
}
