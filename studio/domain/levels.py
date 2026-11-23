"""Game parameter bounds and the playable path through a saved blueprint."""

import math
from collections import deque


def check_curve(p):
    bounds = {
        "quota": (2, 24),
        "seconds": (12, 180),
        "radius": (0.035, 0.22),
        "size": (5, 15),
        "pace": (0.35, 3.5),
    }
    for name, (lo, hi) in bounds.items():
        v = p.get(name)
        if type(v) not in (int, float) or not math.isfinite(v) or not lo <= v <= hi:
            raise ValueError(f"曲线参数 {name} 必须在 {lo}–{hi} 之间")
    if (
        any(type(p[k]) is not int for k in ("quota", "seconds", "size"))
        or p["size"] % 2 != 1
    ):
        raise ValueError("quota、seconds、size 须为整数，size 须为奇数")


def blueprint_path(level):
    size, grid = level["size"], level.get("grid")
    start, goal = level.get("from"), level.get("to")
    if (
        not isinstance(grid, list)
        or len(grid) != size * size
        or any(type(cell) is not int or cell not in (0, 1) for cell in grid)
    ):
        raise ValueError("路径蓝图的 grid 必须是 size × size 的 0/1 数组")
    if start == goal or any(
        type(cell) is not int or not 0 <= cell < len(grid) or not grid[cell]
        for cell in (start, goal)
    ):
        raise ValueError("路径蓝图的 from 和 to 必须是两个不同的可行走格")
    todo, previous = deque([start]), {start: None}
    while todo:
        cell = todo.popleft()
        if cell == goal:
            path = []
            while cell != start:
                path.append(cell)
                cell = previous[cell]
            return path[::-1]
        x, y = cell % size, cell // size
        for a, b in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            n = b * size + a
            if 0 <= a < size and 0 <= b < size and grid[n] and n not in previous:
                todo.append(n)
                previous[n] = cell
    raise ValueError("蓝图的起点与终点不连通")
