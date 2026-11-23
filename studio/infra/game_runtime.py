"""Run deterministic level generation, playability checks and replays under QuickJS limits."""

import json

import quickjs

from studio.domain.levels import blueprint_path, check_curve
from studio.infra.bundles import folder, level_config
from studio.infra.store import encode
from studio.settings import ENGINE

GAME_ABI = """Complete four pure functions start(L), step(s,e,L), draw(s,L), witness(s,L).
The original scaffold, base helpers and factory are included. Reuse them and implement the design delta.
L.index (1-based), total, points, quota, seconds, radius, size, pace, seed, family; trail also has grid/from/to.
For trail, start at L.from, draw and move on L.grid with L.size, and finish at L.to. An independent player
will tap the centers of adjacent walkable cells from the published blueprint. Authored layouts belong in the level generator.
start returns JSON {score,hits,elapsed,done,won,...}. step must return state. e.type tap (x,y normalized),
press/move/release for drags; key/keyup (key ArrowLeft/ArrowRight/ArrowUp/ArrowDown/Space/Enter/KeyW/KeyA/KeyS/KeyD), tick (dt seconds <=0.1). Support touch.
draw returns <=500 normalized commands: rect x,y,w,h; circle/ring/sprite x,y,r; line x,y,x2,y2;
sprite commands can set asset to an id from art.sprites. Use those illustrations for the corresponding entities.
text x,y,text,size (normalized). color is ink/accent/soft/background or #RRGGBB.
witness returns ONE legal player/clock event per call to demonstrate a solution using the true rules.
Start unfinished, reach a genuine user-controlled win, allow timeout losses. No DOM, imports or asynchronous code.
Keep it compact, usually 12–45 lines. The base functions already implement the whole playable loop. Add the requested original scoring/goal and visuals on top; retain a winning witness. Do not reimplement template mechanics unnecessarily. Do not redefine helpers."""


CURVE_ABI = """Complete a pure JS function parameters(index,total,seed) with a return object:
quota integer 2..24, seconds integer 12..180, radius number 0.035..0.22, size ODD integer 5..15,
pace seconds 0.35..3.5. index is 1-based. Must give playable increasing difficulty.
For trail, optionally return grid (size * size row-major 0/1 cells), from and to (distinct walkable indices)
to author a specific map. With no grid, the factory generates a seeded maze.
Use the exact names, pure deterministic math. Include only the function, no export or Markdown."""


def source(name):
    code = (ENGINE / name).read_text()
    # Authoring and legacy callers consume a complete, standalone factory.
    return (
        (ENGINE / "level-helpers.js").read_text() + code
        if name == "factory.js"
        else code
    )


def js_context(*scripts):
    ctx = quickjs.Context()
    ctx.set_memory_limit(24 * 1024 * 1024)
    ctx.set_max_stack_size(512 * 1024)
    ctx.set_time_limit(0.9)
    for script in scripts:
        if len(script) > 64000:
            raise ValueError("代码超出单模块容量")
        ctx.eval(script)
    return ctx


def evaluate(ctx, expr):
    result = ctx.eval("JSON.stringify(" + expr + ")")
    if not isinstance(result, str) or len(result) > 400000:
        raise ValueError("模块必须返回有限的 JSON")
    return json.loads(result)


PROBE = """
(L => {
  let s=start(L), moves=0, inputs=0;
  if(s.done || !Number.isFinite(s.score)) throw Error('invalid initial state');
  const initial=JSON.stringify(s), picture=draw(s,L), inputsUsed=[];
  if(JSON.stringify(s)!==initial) throw Error('draw mutated game state');
  if(!Array.isArray(picture)||!picture.length||picture.length>500) throw Error('invalid scene');
  for(const c of picture){
    if(!c || !['rect','circle','ring','line','text','sprite'].includes(c.kind) ||
       !Number.isFinite(c.x) || !Number.isFinite(c.y)) throw Error('invalid drawing primitive');
  }
  while(!s.done && moves<2200){
    const e=witness(JSON.parse(JSON.stringify(s)),JSON.parse(JSON.stringify(L)));
    if(!e || !['tap','press','move','release','tick','key','keyup'].includes(e.type)) throw Error('invalid witness input');
    if(['tap','press','move','release'].includes(e.type) && !(e.x>=0 && e.x<=1 && e.y>=0 && e.y<=1)) throw Error('invalid tap');
    if(e.type==='tick' && !(e.dt>0 && e.dt<=0.101)) throw Error('invalid tick');
    if(e.type!=='tick') inputs++;
    inputsUsed.push({...e});s=step(s,e,L);moves++;
  }
  if(!s.done || !s.won || !Number.isFinite(s.score) || !inputs) {
    const trace={moves, inputs, quota:L.quota, elapsed:s.elapsed, hits:s.hits, mistakes:s.mistakes,
      score:s.score, done:s.done, won:s.won, last:inputsUsed.slice(-2)};
    throw Error('witness cannot win ' + JSON.stringify(trace).slice(0,450));
  }
  let second=start(L);
  for (const e of inputsUsed) second=step(second,e,L);
  if(JSON.stringify(second)!==JSON.stringify(s)) throw Error('input replay diverged');
  return {moves,score:s.score,commands:picture.length,playerInputs:inputs};

})
"""


BLUEPRINT_PLAY = """
((game, L, path) => {
  let s = game.start(L);
  const tick = () => { if (!s.done) s = game.step(s, {type:'tick', dt:0.1}, L); };
  for (const cell of path) {
    if (s.done || s.won) return false;
    s = game.step(s, {type:'tap', x:(cell % L.size + 0.5) / L.size,
                      y:(Math.floor(cell / L.size) + 0.5) / L.size}, L);
    tick(); tick();
  }
  for (let i=0; i<30 && !s.done; i++) tick();
  return Boolean(s.done && s.won);
})
"""


def verify_blueprint_play(ctx, level, module):
    path = blueprint_path(level)
    ok = evaluate(ctx, f"({BLUEPRINT_PLAY})({module},{encode(level)},{encode(path)})")
    if not ok:
        raise ValueError(
            f"第 {level['index']} 关按蓝图逐格点击无法在终点通关。"
            "请在游戏中统一使用 L.size、L.grid、L.from、L.to，自定义地图交由关卡生成器。"
        )
    return len(path)


def levels_for(design, seed, curve):
    ctx = js_context(source("factory.js"), curve)
    levels, params = [], []
    for index in range(1, design["count"] + 1):
        args = f"{index},{design['count']},{seed}"
        p = evaluate(ctx, f"parameters({args})")
        check_curve(p)
        expr = f"makeLevel({args},{encode(design['game_type'])},parameters)"
        level = evaluate(ctx, expr)
        if level != evaluate(ctx, expr):
            raise ValueError("同一 Seed 产生了不同的关卡")
        if level["family"] == "trail":
            blueprint_path(level)
        levels.append(level)
        params.append(p)
    return levels, params


def approved_levels(pack, baseline_curve, changes, factory=None):
    """Apply only the declared edits to the control generator, retaining derived layout changes."""
    context = js_context(factory or source("factory.js"), baseline_curve)
    result = []
    for before in pack["levels"]:
        edits = changes.get(before["index"])
        if not edits:
            result.append(before)
            continue
        args = f"{before['index']},{len(pack['levels'])},{pack['seed']}"
        family = encode(pack["family"])
        if evaluate(context, f"makeLevel({args},{family},parameters)") != before:
            raise ValueError("当前工厂不能复现对照版本的冻结蓝图")
        params = evaluate(context, f"parameters({args})")
        params.update(edits)
        context.set("approvedParams", context.parse_json(encode(params)))
        level = evaluate(context, f"makeLevel({args},{family},()=>approvedParams)")
        # The default maze factory derives its endpoints. Endpoint-only edits keep its grid.
        for field in ("from", "to"):
            if field in edits:
                level[field] = edits[field]
        result.append(level)
    return result


def verify_game(code, levels):
    ctx = js_context(source("factory.js"), source("base.js"), code)
    proofs = []
    for level in levels:
        try:
            proof = evaluate(ctx, f"({PROBE})({encode(level)})")
            if level["family"] == "trail":
                proof["blueprint_steps"] = verify_blueprint_play(
                    ctx, level, "{start,step}"
                )
        except (quickjs.JSException, ValueError) as exc:
            message = str(exc).splitlines()[0]
            raise ValueError(
                f"第 {level['index']} 关 {level['family']} Seed {level['seed']}，{message}"
            ) from None
        proofs.append(proof)
    return proofs


def remote_context(script):
    ctx = js_context(script)
    ctx.eval(
        "LoopCartridge.get('./game').then(factory=>{globalThis.loadedGame=factory()})"
    )
    for _ in range(8):
        if not ctx.execute_pending_job():
            break
    if ctx.eval("typeof loadedGame") != "object":
        raise ValueError("发布模块未暴露 ./game")
    return ctx


def replay(key, level_number, events):
    ctx = remote_context((folder(key) / "remoteEntry.js").read_text())
    config = level_config(key)
    entry = (
        encode(config["entries"][level_number - 1])
        if config is not None
        else "undefined"
    )
    ctx.set("recordedInputs", ctx.parse_json(encode(events)))
    return evaluate(
        ctx,
        "(() => {const L=loadedGame.level("
        + str(int(level_number))
        + ","
        + entry
        + ");let s=loadedGame.start(L);"
        """for (const record of recordedInputs) {
            if (s.done) break;
            const event = typeof record === 'number' ? {type:'tick',dt:record/1000}
              : !Array.isArray(record) ? record
              : record.length === 3 ? {type:record[0],x:record[1]/10000,y:record[2]/10000}
              : {type:record[0],key:record[1]};
            s=loadedGame.step(s,event,L);
        } """
        "return {done:s.done,won:s.won,score:Math.trunc(s.score),"
        "mistakes:Number.isSafeInteger(s.mistakes)&&s.mistakes>=0?s.mistakes:null,"
        "rescues:Number.isSafeInteger(s.rescues)&&s.rescues>=0?s.rescues:null,"
        "slow_round:Number.isFinite(s.elapsed)&&L.seconds>0?Number(s.elapsed/L.seconds>=0.5):null};})()",
    )
