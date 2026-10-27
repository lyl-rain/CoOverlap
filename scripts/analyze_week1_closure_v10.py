#!/usr/bin/env python3
"""Offline week-1 closure analysis (no model, no GPU, no board writes).

Reads the frozen v4 periodic raw CSVs, the v7 normal-pair CSV and the v9
diagnostic endpoints, and produces:
  CYCLES_PER_CELL.csv, CYCLES_POOLED.csv
  REFRESH_PER_CELL.csv, REFRESH_POOLED.csv
  W_D_PER_CELL.csv, W_D_POOLED.csv
  COST_LEDGER.csv
  WEEK1_CLOSURE_SUMMARY.json
  CYCLE_DISTRIBUTION.svg/.png

Definitions:
  - p99/p99.9 use numpy.percentile (linear interpolation); a nearest-rank value
    is also written because the sample size is small (n=64 per cell, n=192 pooled).
  - A miss is cycle_status != PASS (the same rule as the frozen v4 CELLS.csv).
  - W(D) is the number of definite VLM units completed inside the fixed cycle
    window (one B1 or B2 per unit), from PER_CYCLE_PROGRESS.csv; the assigned
    unit is the unit the cycle was required to advance.
No numbers are fabricated: every row carries its source file.
"""
import ast
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
V4 = ROOT / "reports/m1_acceptance/completion_20261016_v4"
BOARD = V4 / "board/archive/results_20261016T054314Z_770131"
V7 = ROOT / "reports/m1_acceptance/scoped_equivalence_20261016_v7"
V9 = ROOT / "reports/m1_acceptance/tegra_root_trace_20261017_v9"
OUT = ROOT / "reports/m1_acceptance/week1_closure_20261018"
OUT.mkdir(parents=True, exist_ok=True)

ROLES = ["tight_repeat1", "tight_repeat2", "tight_repeat3",
         "loose_repeat1", "loose_repeat2", "loose_repeat3"]
PLANS = ["whole_context", "two_blocks"]
STRESSES = ["none", "memcpy32MiB"]
BUDGETS = [180, 240]


def load_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def longest_miss_run(rows):
    """rows must be the same cell, sorted by cycle index."""
    best = run = 0
    for r in rows:
        if r["cycle_status"] != "PASS":
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def pctl(values, q):
    if not values:
        return None
    return float(np.percentile(np.asarray(values, dtype=float), q))


def nearest_rank(values, q):
    v = sorted(values)
    if not v:
        return None
    idx = max(0, min(len(v) - 1, math.ceil(q / 100.0 * len(v)) - 1))
    return float(v[idx])


def cell_stats(values, miss_count):
    n = len(values)
    return dict(
        n=n,
        median_ms=pctl(values, 50),
        p90_ms=pctl(values, 90),
        p99_ms=pctl(values, 99),
        p99_9_ms=pctl(values, 99.9),
        p99_nearest_ms=nearest_rank(values, 99),
        p99_9_nearest_ms=nearest_rank(values, 99.9),
        max_ms=max(values) if values else None,
        miss=miss_count,
        miss_rate=miss_count / n if n else None,
    )


# ---------------------------------------------------------------- cycles
def analyze_cycles():
    per_cell = []
    pooled = []
    cells_official = {(r["role"], int(r["P_ms"]), r["plan"], r["interference"]): r
                      for r in load_csv(V4 / "summary/CELLS.csv")}
    for role in ROLES:
        path = BOARD / role / "offline_analysis/cycles.csv"
        all_rows = load_csv(path)
        for plan in PLANS:
            for stress in STRESSES:
                rows = [r for r in all_rows
                        if r["plan"] == plan and r["interference"] == stress]
                rows.sort(key=lambda r: int(r["cycle"]))
                vals = [float(r["response_upper_ms"]) for r in rows]
                miss = sum(1 for r in rows if r["cycle_status"] != "PASS")
                stats = cell_stats(vals, miss)
                off = cells_official.get((role, int(rows[0]["P_ms"]), plan, stress))
                stats.update(
                    source=str(path.relative_to(ROOT)),
                    role=role, P_ms=int(rows[0]["P_ms"]), plan=plan,
                    interference=stress,
                    longest_cycle_miss=longest_miss_run(rows),
                    cells_cycle_miss=int(off["cycle_miss"]) if off else None,
                    cells_longest=int(off["longest_cycle_miss"]) if off else None,
                )
                stats["miss_matches_cells"] = (stats["miss"] == stats["cells_cycle_miss"])
                stats["longest_matches_cells"] = (stats["longest_cycle_miss"] == stats["cells_longest"])
                per_cell.append(stats)

    for P in BUDGETS:
        for plan in PLANS:
            for stress in STRESSES:
                vals = []
                miss = 0
                for role in ROLES:
                    if not role.startswith("tight" if P == 180 else "loose"):
                        continue
                    path = BOARD / role / "offline_analysis/cycles.csv"
                    rows = [r for r in load_csv(path)
                            if r["plan"] == plan and r["interference"] == stress]
                    vals += [float(r["response_upper_ms"]) for r in rows]
                    miss += sum(1 for r in rows if r["cycle_status"] != "PASS")
                stats = cell_stats(vals, miss)
                stats.update(P_ms=P, plan=plan, interference=stress,
                             source="3 independent repeats, concatenated (not pooled for speed ratio)")
                pooled.append(stats)
    return per_cell, pooled


# ---------------------------------------------------------------- refresh
def analyze_refresh():
    per_cell = []
    pooled = []
    for role in ROLES:
        path = BOARD / role / "offline_analysis/refreshes.csv"
        all_rows = load_csv(path)
        for plan in PLANS:
            for stress in STRESSES:
                rows = [r for r in all_rows
                        if r["plan"] == plan and r["interference"] == stress]
                # one process file contains all four cells; 32 refreshes per cell
                rows = list({r["id"]: r for r in rows}.values())
                rows.sort(key=lambda r: int(r["id"]))
                vals = [float(r["response_upper_ms"]) for r in rows]
                ks = [int(r["k_observed_upper"]) for r in rows]
                target_miss = sum(1 for r in rows if r["target_status"] != "PASS")
                stats = cell_stats(vals, target_miss)
                stats.update(
                    source=str(path.relative_to(ROOT)),
                    role=role, P_ms=int(rows[0]["P_ms"]), plan=plan,
                    interference=stress,
                    k_min_observed=min(ks) if ks else None,
                    k_max_observed=max(ks) if ks else None,
                    k_distribution=dict(sorted(Counter(ks).items())),
                    target_refresh_periods=int(rows[0]["target_refresh_periods"]),
                    target_miss_denominator=len(rows),
                )
                per_cell.append(stats)

    for P in BUDGETS:
        for plan in PLANS:
            for stress in STRESSES:
                vals, ks, miss = [], [], 0
                for role in ROLES:
                    if not role.startswith("tight" if P == 180 else "loose"):
                        continue
                    path = BOARD / role / "offline_analysis/refreshes.csv"
                    rows = [r for r in load_csv(path)
                            if r["plan"] == plan and r["interference"] == stress]
                    rows = list({r["id"]: r for r in rows}.values())
                    vals += [float(r["response_upper_ms"]) for r in rows]
                    ks += [int(r["k_observed_upper"]) for r in rows]
                    miss += sum(1 for r in rows if r["target_status"] != "PASS")
                stats = cell_stats(vals, miss)
                stats.update(P_ms=P, plan=plan, interference=stress,
                             k_min_observed=min(ks) if ks else None,
                             k_max_observed=max(ks) if ks else None,
                             k_distribution=dict(sorted(Counter(ks).items())),
                             target_miss_denominator=len(vals))
                pooled.append(stats)
    return per_cell, pooled


# ---------------------------------------------------------------- W(D)
def analyze_wd():
    progress = load_csv(V4 / "summary/PER_CYCLE_PROGRESS.csv")
    per_cell = []
    pooled = []
    for role in ROLES:
        for plan in PLANS:
            for stress in STRESSES:
                rows = [r for r in progress if r["role"] == role
                        and r["plan"] == plan and r["interference"] == stress]
                rows.sort(key=lambda r: int(r["cycle"]))
                P = int(rows[0]["P_ms"])
                w = []
                ontime = 0
                uncertain = 0
                for r in rows:
                    units = ast.literal_eval(r["definite_units"])
                    units = list(dict.fromkeys(units))
                    w.append(len(units))
                    uncertain += len(ast.literal_eval(r["completion_window_uncertain_units"]))
                    if r["assigned_unit"] in units:
                        ontime += 1
                required = len(rows)
                per_cell.append(dict(
                    role=role, P_ms=P, plan=plan, interference=stress,
                    cycles=len(rows), W_total=sum(w),
                    W_per_cycle=sum(w) / len(rows),
                    W_backlog=max(0, required - sum(w)),
                    W_uncertain_units=uncertain,
                    assigned_in_own_window=ontime,
                    assigned_in_own_window_rate=ontime / len(rows),
                    assigned_in_own_window_note=(
                        "informational only: a B2 completed early in the preceding B1 "
                        "window lowers this rate although it is not late"),
                    cycles_zero=w.count(0), cycles_one=w.count(1),
                    cycles_two=w.count(2),
                    denominator_assigned_units=len(rows),
                    source=str((V4 / "summary/PER_CYCLE_PROGRESS.csv").relative_to(ROOT)),
                ))

    for P in BUDGETS:
        for plan in PLANS:
            for stress in STRESSES:
                w, cycles, ontime, uncertain = [], 0, 0, 0
                for role in ROLES:
                    if not role.startswith("tight" if P == 180 else "loose"):
                        continue
                    rows = [r for r in progress if r["role"] == role
                            and r["plan"] == plan and r["interference"] == stress]
                    for r in rows:
                        units = ast.literal_eval(r["definite_units"])
                        units = list(dict.fromkeys(units))
                        w.append(len(units))
                        uncertain += len(ast.literal_eval(r["completion_window_uncertain_units"]))
                        cycles += 1
                        if r["assigned_unit"] in units:
                            ontime += 1
                pooled.append(dict(
                    P_ms=P, plan=plan, interference=stress,
                    cycles=cycles, W_total=sum(w),
                    W_per_cycle=sum(w) / cycles,
                    W_backlog=max(0, cycles - sum(w)),
                    W_uncertain_units=uncertain,
                    assigned_in_own_window=ontime,
                    assigned_in_own_window_rate=ontime / cycles,
                    cycles_zero=w.count(0), cycles_one=w.count(1),
                    cycles_two=w.count(2),
                    denominator_assigned_units=cycles,
                ))
    return per_cell, pooled


# ---------------------------------------------------------------- cost ledger
COST_ITEMS = [
    # (component, source, value/range, unit, in_end_to_end_window, note)
    ("Expert→数学边界等待", "v7 FINAL_REPORT.md:62", "0", "ms", True,
     "全部正常样本为0；Event显示数学边界早于Expert完成"),
    ("Expert→D2D后可调度边界等待", "v7 FINAL_REPORT.md:63", "0.296936–0.405472", "ms", True,
     "Event量；归还模式0.391327–0.403656"),
    ("首次Expert完成检测（Host API）", "v7 FINAL_REPORT.md:64", "0.008896–0.009120", "ms", True,
     "检测API成本，不是完整边界等待"),
    ("D2D留存提交（Host）", "v7 FINAL_REPORT.md:65", "0.272959–0.289022", "ms", True,
     "GPU完成另由可调度边界Event记录"),
    ("归还判断前→B2提交前（Host）", "v7 FINAL_REPORT.md:66", "0.054335–0.056192", "ms", True,
     "含判断、路径选择、依赖建立；不是全部设置成本"),
    ("归还判断前→B2提交返回（Host）", "v7 FINAL_REPORT.md:66", "6.313098–6.459784", "ms", True,
     "含9层CPU提交；与上一项是包含关系，不能相加"),
    ("资源一次性准备", "v7 FINAL_REPORT.md:66", "11.625078", "ms", False,
     "查询/拆分、两个GreenContext、流创建/Torch包装；探针/初始化/Autotune另账"),
    ("留存→B2首个Kernel（GPU公共时间线）", "v9 KERNEL_SUMMARY.csv", "0.192448–0.219296", "ms", True,
     "诊断n=1；证明真实生效，不进入正常统计"),
    ("B2首launch API起→Kernel起", "v9 KERNEL_SUMMARY.csv", "0.020367–0.022269", "ms", True,
     "诊断n=1；API→Kernel局部延迟，不是资源生效延迟本身"),
    ("图启动成本", "本路径为Eager，无CUDA Graph捕获/回放", "N/A", "ms", False,
     "任务书§3.3要求记录；该路径无Graph，不能虚构一项"),
]


def write_cost_ledger():
    rows = []
    for item in COST_ITEMS:
        rows.append(dict(zip(
            ["component", "source", "value_or_range", "unit",
             "included_in_end_to_end_window", "note"], item)))
    path = OUT / "COST_LEDGER.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return rows


# ---------------------------------------------------------------- SVG
def fmt(v, nd=1):
    return "NA" if v is None else f"{v:.{nd}f}"


def make_svg(cycles_pooled, refresh_pooled, wd_pooled):
    W, H = 1500, 1020
    bg = "#f5f7fb"
    ink = "#20324b"
    grid = "#d9e1ec"
    cols = {"180": "#1a77bd", "240": "#d2691e"}
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
           f'viewBox="0 0 {W} {H}"><rect width="100%" height="100%" fill="{bg}"/>']
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(im)
    font_path = "/System/Library/Fonts/Hiragino Sans GB.ttc"
    try:
        f32 = ImageFont.truetype(font_path, 32)
        f20 = ImageFont.truetype(font_path, 20)
        f16 = ImageFont.truetype(font_path, 16)
        f13 = ImageFont.truetype(font_path, 13)
    except Exception:
        f32 = f20 = f16 = f13 = ImageFont.load_default()

    def text(x, y, t, size=20, color=ink, font=None):
        d.text((x, y), t, font=font or ImageFont.truetype(font_path, size), fill=color)
        svg.append(f'<text x="{x}" y="{y + size}" font-family="PingFang SC,Arial,sans-serif" '
                   f'font-size="{size}" fill="{color}">{t}</text>')

    def rect(x, y, w, h, fill, stroke=None):
        d.rectangle([x, y, x + w, y + h], fill=fill, outline=stroke)
        svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}"'
                   + (f' stroke="{stroke}"' if stroke else "") + "/>")

    def line(x1, y1, x2, y2, color=grid):
        d.line([x1, y1, x2, y2], fill=color)
        svg.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}"/>')

    text(30, 18, "CoOverlap M1 收口增补｜周期/刷新分布与 W(D)（离线重算，无新模型）", 30, ink, f32)
    text(30, 62, "数据：v4 24格×64周期（3独立重复）；v7/v9 仅作端点与成本；p99为小样本估计，不称可靠p99.9。", 17, "#4a5d75", f16)

    # Panel A: ECDF of cycle response (two budgets, whole none / two mem)
    ox, oy, pw, ph = 45, 120, 690, 360
    rect(ox - 10, oy - 10, pw + 20, ph + 55, "#ffffff")
    text(ox, oy - 3, "A  周期响应 ECDF（三次独立重复合并；whole无干扰 / 双块访存）", 18, ink, f16)
    # axes
    x0, y0 = ox + 60, oy + ph - 40
    x1, y1 = ox + pw - 20, oy + 30
    line(x0, y0, x1, y0)
    line(x0, y0, x0, y1)
    maxv = 380
    for v in range(0, 381, 90):
        xx = x0 + (x1 - x0) * v / maxv
        line(xx, y0, xx, y0 + 4, "#8a99ab")
        text(xx - 10, y0 + 8, str(v), 13, "#5a6b80", f13)
    for q in [0, 25, 50, 75, 100]:
        yy = y0 - (y0 - y1) * q / 100
        line(x0 - 4, yy, x0, yy, "#8a99ab")
        text(x0 - 40, yy - 7, f"{q}%", 13, "#5a6b80", f13)
    text(x0 - 45, y0 + 26, "ms", 13, "#5a6b80", f13)
    series = []
    for P, plan, stress, label, dash in [
        (180, "whole_context", "none", "180 whole/无", cols["180"]),
        (180, "two_blocks", "memcpy32MiB", "180 双块/访存", "#5b9bd5"),
        (240, "whole_context", "none", "240 whole/无", cols["240"]),
        (240, "two_blocks", "memcpy32MiB", "240 双块/访存", "#e0a060"),
    ]:
        p = next(r for r in cycles_pooled
                 if r["P_ms"] == P and r["plan"] == plan and r["interference"] == stress)
        # reconstruct values by reading raw again (pooled CSV has stats only)
        vals = []
        for role in ROLES:
            if not role.startswith("tight" if P == 180 else "loose"):
                continue
            rows = [r for r in load_csv(BOARD / role / "offline_analysis/cycles.csv")
                    if r["plan"] == plan and r["interference"] == stress]
            vals += [float(r["response_upper_ms"]) for r in rows]
        series.append((label, vals, dash))
    # legend
    for i, (label, vals, color) in enumerate(series):
        lx = ox + 70 + i * 155
        line(lx, oy + 22, lx + 26, oy + 22, color)
        text(lx + 32, oy + 12, label, 13, "#33475f", f13)
    for label, vals, color in series:
        vals = sorted(vals)
        n = len(vals)
        pts = []
        for i, v in enumerate(vals):
            xx = x0 + (x1 - x0) * min(v, maxv) / maxv
            yy = y0 - (y0 - y1) * (i + 1) / n
            pts.append(f"{xx:.1f},{yy:.1f}")
        d.line([(float(a.split(",")[0]), float(a.split(",")[1])) for a in pts], fill=color, width=2)
        svg.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" stroke-width="2"/>')
    # budget lines
    for P, color in [(180, "#1a77bd"), (240, "#d2691e")]:
        xx = x0 + (x1 - x0) * P / maxv
        d.line([xx, y1, xx, y0], fill=color)
        svg.append(f'<line x1="{xx}" y1="{y1}" x2="{xx}" y2="{y0}" stroke="{color}" stroke-dasharray="4,4"/>')

    # Panel B: p99 bars per pooled combination
    ox, oy, pw, ph = 800, 120, 650, 360
    rect(ox - 10, oy - 10, pw + 20, ph + 55, "#ffffff")
    text(ox, oy - 3, "B  周期 p99（每组合192周期，虚线=对应预算）", 18, ink, f16)
    x0, y0 = ox + 110, oy + ph - 45
    x1, y1 = ox + pw - 20, oy + 40
    line(x0, y0, x1, y0)
    line(x0, y0, x0, y1)
    bars = []
    for P in BUDGETS:
        for plan in PLANS:
            for stress in STRESSES:
                r = next(x for x in cycles_pooled
                         if x["P_ms"] == P and x["plan"] == plan and x["interference"] == stress)
                bars.append((P, plan, stress, r["p99_ms"]))
    maxv = 400
    for i, (P, plan, stress, v) in enumerate(bars):
        yy = y0 - i * 36
        label = f"{P} {'W' if plan=='whole_context' else 'B'} {'no' if stress=='none' else 'mem'}"
        text(x0 - 95, yy - 16, label, 13, "#33475f", f13)
        w = (x1 - x0) * min(v, maxv) / maxv
        color = cols["180"] if P == 180 else cols["240"]
        rect(x0, yy - 22, w, 22, color)
        text(x0 + w + 6, yy - 18, f"{v:.0f}", 13, "#33475f", f13)
        xx = x0 + (x1 - x0) * P / maxv
        line(xx, yy - 26, xx, yy, "#000000")
    text(x0 - 100, y0 + 12, "ms", 13, "#5a6b80", f13)

    # Panel C: refresh p99 / target miss
    ox, oy, pw, ph = 45, 560, 690, 380
    rect(ox - 10, oy - 10, pw + 20, ph + 55, "#ffffff")
    text(ox, oy - 3, "C  完整刷新响应 p99 与 2P 目标未达（每组合96刷新）", 18, ink, f16)
    x0, y0 = ox + 120, oy + ph - 45
    x1, y1 = ox + pw - 20, oy + 45
    line(x0, y0, x1, y0)
    line(x0, y0, x0, y1)
    bars = []
    for P in BUDGETS:
        for plan in PLANS:
            for stress in STRESSES:
                r = next(x for x in refresh_pooled
                         if x["P_ms"] == P and x["plan"] == plan and x["interference"] == stress)
                bars.append((P, plan, stress, r["p99_ms"], r["miss"], r["target_miss_denominator"]))
    maxv = 520
    for i, (P, plan, stress, v, miss, den) in enumerate(bars):
        yy = y0 - i * 38
        label = f"{P} {'W' if plan=='whole_context' else 'B'} {'no' if stress=='none' else 'mem'}"
        text(x0 - 108, yy - 17, label, 13, "#33475f", f13)
        w = (x1 - x0) * min(v, maxv) / maxv
        color = "#2e8b57" if P == 180 else "#8a6d3b"
        rect(x0, yy - 23, w, 23, color)
        tag = f"{v:.0f} | {miss}/{den}"
        if w > 330:
            text(x0 + w - 105, yy - 19, tag, 12, "#ffffff", f13)
        else:
            text(x0 + w + 6, yy - 19, tag, 12, "#33475f", f13)
        xx = x0 + (x1 - x0) * (2 * P) / maxv
        line(xx, yy - 27, xx, yy, "#000000")
    text(x0 - 108, y0 + 12, "ms；黑线=2P目标", 13, "#5a6b80", f13)

    # Panel D: W(D)
    ox, oy, pw, ph = 800, 560, 650, 380
    rect(ox - 10, oy - 10, pw + 20, ph + 55, "#ffffff")
    text(ox, oy - 3, "D  W(D)：每周期完成 VLM 单元（whole/无 与 双块/访存）", 18, ink, f16)
    x0, y0 = ox + 150, oy + ph - 45
    x1, y1 = ox + pw - 20, oy + 50
    line(x0, y0, x1, y0)
    line(x0, y0, x0, y1)
    maxv = 2.0
    for i, (P, plan, stress) in enumerate([(180, "whole_context", "none"),
                                           (180, "two_blocks", "memcpy32MiB"),
                                           (240, "whole_context", "none"),
                                           (240, "two_blocks", "memcpy32MiB")]):
        r = next(x for x in wd_pooled
                 if x["P_ms"] == P and x["plan"] == plan and x["interference"] == stress)
        yy = y0 - i * 70
        label = f"{P} {'whole' if plan=='whole_context' else '双块'}{'' if stress=='none' else '/访存'}"
        text(x0 - 135, yy - 25, label, 14, "#33475f", f13)
        w = (x1 - x0) * r["W_per_cycle"] / maxv
        color = cols["180"] if P == 180 else cols["240"]
        rect(x0, yy - 34, w, 34, color)
        text(x0 + w + 8, yy - 27, f"{r['W_per_cycle']:.3f} /cycle；backlog "
             f"{r['W_backlog']}；uncertain {r['W_uncertain_units']}", 13, "#33475f", f13)
    text(x0 - 145, y0 + 12, "单元/周期；上限2（一次B1+一次B2）", 13, "#5a6b80", f13)

    text(45, 970, "来源：reports/m1_acceptance/completion_20261016_v4/board/archive/.../offline_analysis/{cycles,refreshes}.csv；"
                  "PER_CYCLE_PROGRESS.csv。p99 为 numpy 线性插值；n=64/192 与 n=32/96 均属小样本，仅作有限分布描述。",
         13, "#5a6b80", f13)
    svg.append("</svg>")
    (OUT / "CYCLE_DISTRIBUTION.svg").write_text("".join(svg))
    im.save(OUT / "CYCLE_DISTRIBUTION.png")


def main():
    cycles_cell, cycles_pooled = analyze_cycles()
    refresh_cell, refresh_pooled = analyze_refresh()
    wd_cell, wd_pooled = analyze_wd()
    cost = write_cost_ledger()

    def dump(name, rows):
        with open(OUT / name, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    dump("CYCLES_PER_CELL.csv", cycles_cell)
    dump("CYCLES_POOLED.csv", cycles_pooled)
    dump("REFRESH_PER_CELL.csv", refresh_cell)
    dump("REFRESH_POOLED.csv", refresh_pooled)
    dump("W_D_PER_CELL.csv", wd_cell)
    dump("W_D_POOLED.csv", wd_pooled)

    summary = dict(
        generated_from="existing v4/v7/v9 frozen CSVs; no model/GPU/board writes",
        cycle_cells=len(cycles_cell), cycle_pooled=len(cycles_pooled),
        refresh_cells=len(refresh_cell), refresh_pooled=len(refresh_pooled),
        wd_cells=len(wd_cell), wd_pooled=len(wd_pooled),
        cycle_miss_matches_cells=all(r["miss_matches_cells"] for r in cycles_cell),
        cycle_longest_matches_cells=all(r["longest_matches_cells"] for r in cycles_cell),
        p99_method="numpy.percentile linear; nearest-rank also written",
        cycles=[{k: r[k] for k in ("P_ms", "plan", "interference", "n", "median_ms",
                                   "p99_ms", "p99_9_ms", "max_ms", "miss", "miss_rate")}
                for r in cycles_pooled],
        refreshes=[{k: r[k] for k in ("P_ms", "plan", "interference", "n", "median_ms",
                                      "p99_ms", "max_ms", "miss", "miss_rate",
                                      "k_min_observed", "k_max_observed")}
                   for r in refresh_pooled],
        wd=[{k: r[k] for k in ("P_ms", "plan", "interference", "cycles", "W_total",
                               "W_per_cycle", "W_backlog", "W_uncertain_units",
                               "assigned_in_own_window_rate")}
            for r in wd_pooled],
        cost_items=len(cost),
    )
    (OUT / "WEEK1_CLOSURE_SUMMARY.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False))
    make_svg(cycles_pooled, refresh_pooled, wd_pooled)
    print(json.dumps(summary, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
