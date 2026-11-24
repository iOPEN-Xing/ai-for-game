"""Run deterministic level generation, playability checks and replays under QuickJS limits."""

import json

import quickjs

from studio.domain.levels import blueprint_path, chapter_position, check_curve
from studio.infra.bundles import folder, level_config
from studio.infra.store import encode
from studio.settings import ENGINE

GAME_ABI = """Complete four pure functions start(L), step(s,e,L), draw(s,L), witness(s,L).
Build the approved game from its player decisions and layout. Base helpers are optional.
For chapter games L.chapter={number,level,length} (all 1-based counts), L.content is the level coder's authored JSON object. Read the supplied real chapter_samples.
L.index (1-based), total, points, quota, seconds, radius, size, pace, seed, family; trail also has grid/from/to.
For trail, start at L.from, draw and move on L.grid with L.size, and finish at L.to. An independent player
will tap the centers of adjacent walkable cells from the published blueprint. Authored layouts belong in the level generator.
start returns JSON {score,hits,elapsed,done,won,...}. step must return state. e.type tap (x,y normalized),
press/move/release for drags; key/keyup (key ArrowLeft/ArrowRight/ArrowUp/ArrowDown/Space/Enter/KeyW/KeyA/KeyS/KeyD), tick (dt seconds <=0.1). Support touch.
Touch down sends press and tap at the same location; touch up sends release. Score a single gesture once.
draw returns <=500 normalized commands. Use {kind:"circle",x:0.5,y:0.5,r:0.08,color:"accent"}, never type for a drawing command. Allowed shapes: rect x,y,w,h; circle/ring/sprite x,y,r; line x,y,x2,y2; polygon x,y,points (3..32 pairs of normalized [dx,dy] relative to x,y). All commands allow opacity from 0 to 1.
sprite commands can set asset to an id from art.sprites. Use those illustrations for the corresponding entities.
text x,y,text,size (normalized). color is ink/accent/soft/background or #RRGGBB.
witness returns ONE legal player/clock event per call to demonstrate a solution using the true rules.
Start unfinished, reach a genuine user-controlled win, allow timeout losses. No DOM, imports or asynchronous code.
Use as much code as the rules need. Implement state transitions, meaningful alternatives, recovery and visible feedback. Render the approved spatial composition at its viewport aspect; coordinates scale independently, radii and text by the shorter side. Keep helpers from the host in their own namespace by avoiding redefinitions."""


CURVE_ABI = """Complete a pure JS function parameters(index,total,seed,chapter) with a return object:
quota integer 2..24, seconds integer 12..180, radius number 0.035..0.22, size ODD integer 5..15,
pace seconds 0.35..3.5. index is 1-based. For chapter games, chapter={number,level,length}. Return optional content (a JSON object up to 2048 UTF-8 bytes) with authored pieces, objectives, obstacles or rule switches used directly by the game. Introduce one challenge at a time, combine it later; allow recovery levels. Keep tutorial targets reachable and later levels solvable.
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


def js_context(*scripts, max_script_chars=64_000):
    ctx = quickjs.Context()
    ctx.set_memory_limit(24 * 1024 * 1024)
    ctx.set_max_stack_size(512 * 1024)
    ctx.set_time_limit(0.9)
    for script in scripts:
        if len(script) > max_script_chars:
            raise ValueError("代码超出单模块容量")
        ctx.eval(script)
    return ctx


def evaluate(ctx, expr):
    result = ctx.eval("JSON.stringify(" + expr + ")")
    if not isinstance(result, str) or len(result) > 400000:
        raise ValueError("模块必须返回有限的 JSON")
    return json.loads(result)


PROBE = source("playtest.js")


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
        chapters = design.get("chapters")
        chapter = (
            chapter_position(chapters, index, design["count"]) if chapters else None
        )
        extra = "," + encode(chapter) if chapter else ""
        p = evaluate(ctx, f"parameters({args}{extra})")
        check_curve(p)
        if chapter:
            content = p.get("content", {})
            if not isinstance(content, dict) or len(encode(content).encode()) > 2048:
                raise ValueError(
                    f"第 {index} 关 content 需要是 2048 字节以内的 JSON 对象"
                )
            p["chapter"] = chapter
        expr = f"makeLevel({args},{encode(design['game_type'])},parameters{extra})"
        level = evaluate(ctx, expr)
        if level != evaluate(ctx, expr):
            raise ValueError("同一 Seed 产生了不同的关卡")
        if level["family"] == "trail":
            blueprint_path(level)
        levels.append(level)
        params.append(p)
    if design.get("chapters"):
        # Ignore automatic seed/point variation and chapter labels. Compare authored settings.
        fields = (
            "seconds",
            "quota",
            "pace",
            "size",
            "radius",
            "content",
            "grid",
            "from",
            "to",
        )
        patterns = {
            json.dumps({k: p[k] for k in fields if k in p}, sort_keys=True)
            for p in params
        }
        if len(patterns) < 3:
            raise ValueError(
                "章节至少需要三种实际关卡配置。通过机关、布局、操作窗口或目标改变玩法。"
            )
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
        extra = "," + encode(before["chapter"]) if "chapter" in before else ""
        if evaluate(context, f"makeLevel({args},{family},parameters{extra})") != before:
            raise ValueError("当前工厂不能复现对照版本的冻结蓝图")
        params = evaluate(context, f"parameters({args}{extra})")
        params.update(edits)
        context.set("approvedParams", context.parse_json(encode(params)))
        level = evaluate(
            context, f"makeLevel({args},{family},()=>approvedParams{extra})"
        )
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
    if levels and "chapter" in levels[0] and len(levels) == levels[0]["total"]:
        if not any(item["differsFromStarter"] for item in proofs):
            raise ValueError(
                "整套关卡在真实回放中的玩法与画面都沿用了默认样板。请实现 GDD 的核心决策和可见反馈"
            )
    return proofs


def remote_context(script):
    ctx = js_context(script, max_script_chars=512_000)
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
