#!/usr/bin/env python3
"""First opportunity figure v2: panel A = legal-SM quota curve when the v10
result exists, otherwise the old locked/unlocked 16/8 reference with a clear
"pending" note. Panels B-F are the frozen v7/v9/v4 observations.

Offline only; no inferred GPU service and no synthetic points.
"""
import csv
import html
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plot_quota_sweep_v10 import parse as parse_quota

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "reports/m1_acceptance/tegra_root_trace_20261017_v9"
V7 = SRC.parent / "scoped_equivalence_20261016_v7"
V4 = SRC.parent / "completion_20261016_v4/summary"
OUT = ROOT / "reports/m1_acceptance/week1_closure_20261018"
FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"


class Canvas:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.im = Image.new("RGB", (w, h), "#f5f7fb")
        self.d = ImageDraw.Draw(self.im)
        self.s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
                  f'viewBox="0 0 {w} {h}"><rect width="100%" height="100%" fill="#f5f7fb"/>']

    def rect(self, x, y, w, h, c):
        self.d.rectangle([x, y, x + w, y + h], fill=c)
        self.s.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{c}"/>')

    def text(self, x, y, t, size=20, c="#23324a"):
        self.d.text((x, y), str(t), font=ImageFont.truetype(FONT, size), fill=c)
        self.s.append(f'<text x="{x}" y="{y + size}" font-family="PingFang SC,Arial,sans-serif" '
                      f'font-size="{size}" fill="{c}">{html.escape(str(t))}</text>')

    def line(self, x, y, x2, y2, c="#aab5c4", w=1):
        self.d.line((x, y, x2, y2), fill=c, width=w)
        self.s.append(f'<line x1="{x}" y1="{y}" x2="{x2}" y2="{y2}" stroke="{c}" stroke-width="{w}"/>')

    def dot(self, x, y, r, c):
        self.d.ellipse([x - r, y - r, x + r, y + r], fill=c)
        self.s.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{c}"/>')

    def save(self, name):
        (OUT / (name + ".svg")).write_text("\n".join(self.s + ["</svg>"]))
        self.im.save(OUT / (name + ".png"))


def rows(p):
    return list(csv.DictReader(p.open()))


def quota_rows(path=None):
    if path is None:
        cands = sorted((OUT / "quota_sweep/board").glob("*/result.json"))
        if not cands:
            return None
        path = cands[-1]
    return parse_quota(json.loads(Path(path).read_text()))


def sub_panel(c, qrows, kind, x, y, w, h, title, color):
    sub = [r for r in qrows if r["kind"] == kind]
    if not sub:
        c.text(x, y + 20, f"{title}: 无样本", 13, "#9b3b3b")
        return
    full = next((r for r in sub if r.get("full_reference")), None)
    vals = [r["event_median_ms"] for r in sub if r["event_median_ms"] is not None]
    if full and full["event_median_ms"] is not None:
        vals.append(full["event_median_ms"])
    if not vals:
        c.text(x, y + 20, f"{title}: 无 formal 样本", 13, "#9b3b3b")
        return
    maxv = max(vals) * 1.28
    x0, x1 = x + 58, x + w - 18
    y0, y1 = y + h - 20, y + 28
    c.text(x, y, title, 13, "#23324a")
    c.line(x0, y0, x1, y0)
    c.line(x0, y0, x0, y1)
    for v in (0, maxv / 2, maxv):
        yy = y0 - (y0 - y1) * v / maxv
        c.line(x0 - 4, yy, x0, yy, "#8a99ab")
        c.text(x0 - 40, yy - 6, f"{v:.0f}", 10, "#5a6b80")

    def X(q):
        return x0 + (x1 - x0) * q / 16

    def Y(v):
        return y0 - (y0 - y1) * v / maxv

    for q in range(0, 17, 2):
        c.line(X(q), y0, X(q), y0 + 3, "#8a99ab")
        c.text(X(q) - 5, y0 + 5, str(q), 10, "#5a6b80")
    if full and full["event_median_ms"] is not None:
        yy = Y(full["event_median_ms"])
        c.line(x0, yy, x1, yy, "#999999", 1)
        c.text(x0 + 6, yy - 13, f"full {full['event_median_ms']:.1f}", 9, "#666666")
    pts = []
    for r in sub:
        if r.get("full_reference"):
            continue
        q = r["quota"]
        if r["status"] != "PASS":
            c.text(X(q) - 20, y0 - 18, "NOT_LEGAL", 8, "#b03a3a")
            continue
        if r["event_median_ms"] is None:
            continue
        yy = Y(r["event_median_ms"])
        pts.append((X(q), yy))
        c.line(X(q), Y(r["event_min_ms"]), X(q), Y(r["event_max_ms"]), color, 1)
        c.line(X(q) - 4, Y(r["event_min_ms"]), X(q) + 4, Y(r["event_min_ms"]), color, 1)
        c.line(X(q) - 4, Y(r["event_max_ms"]), X(q) + 4, Y(r["event_max_ms"]), color, 1)
        c.dot(X(q), yy, 3, color)
        c.text(X(q) - 10, yy - 14, f"{r['event_median_ms']:.0f}", 9, "#23324a")
    if len(pts) >= 2:
        pts.sort()
        for i in range(len(pts) - 1):
            c.line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], color, 2)


def old_a_panel(c):
    c.text(50, 125, "A  孤立限额响应｜旧10-15批次，同批各n=3（v10配额 sweep 未运行）", 20)
    for i, (title, a, b) in enumerate([("完整 Context", 122.790, 199.718),
                                      ("完整 Expert", 80.417, 81.892)]):
        y = 182 + i * 105
        c.text(50, y, title, 20)
        for j, (lbl, v, col) in enumerate([("16 SM", a, "#2585ba"), ("8 SM", b, "#e39537")]):
            yy = y + 35 + j * 29
            c.text(50, yy, lbl, 16)
            c.rect(140, yy + 3, v * 2.1, 17, col)
            c.text(590, yy, f"{v:.3f} ms", 18)
    c.text(50, 415, "CUDA Event包围区间；非Kernel服务时间；A面板待v10锁频配额曲线回填。", 15, "#7a4b1f")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--quota-result", default=None)
    ap.add_argument("--out-name", default="M1_OPPORTUNITY_OVERVIEW_V2")
    a = ap.parse_args()
    qrows = quota_rows(a.quota_result)

    normal = rows(V7 / "MODE_SUMMARY.csv")
    trace = rows(SRC / "KERNEL_SUMMARY.csv")
    cells = rows(V4 / "CELLS.csv")
    names = {"serial": "串行", "ordinary": "普通双流", "fixed": "固定 8+8", "return": "合法边界归还"}

    c = Canvas(1600, 1320)
    c.text(35, 20, "CoOverlap M1｜真实负载机会观察与负面结果", 32)
    c.text(35, 66, "固定 BF16 / 双视角 / 18层 Encoder / 10步 Expert；A=锁频配额曲线（若有），B–F=冻结批次；不混合估计收益。", 20)
    for y in (110, 490, 870):
        for x in (30, 815):
            c.rect(x, y, 755, 350, "#ffffff")

    if qrows:
        c.text(50, 125, "A  合法SM配额响应｜锁频隔离 Context/Expert（formal n=3；full参考n=1）", 19)
        sub_panel(c, qrows, "Context", 50, 158, 710, 140, "Context 18层 Encoder（ms）", "#2479b5")
        sub_panel(c, qrows, "Expert", 50, 306, 710, 110, "Expert 10×18 Decoder（ms）", "#d27a2c")
        notes = []
        for r in qrows:
            if r["sm_ids"] is not None:
                notes.append(f"q{r['quota']}:{r['observed_sm_count']}")
        c.text(50, 424, "探针观察SM数：" + "  ".join(dict.fromkeys(notes)) + "；完整SM ID见QUOTA_SWEEP.csv", 11, "#5a6b80")
    else:
        old_a_panel(c)

    c.text(835, 125, "B  四模式正常计时｜v7 普通用户，各 n=3", 23)
    for i, r in enumerate(normal):
        y = 183 + i * 51
        v = float(r["window_Host_ms_median"])
        lo = float(r["window_Host_ms_min"])
        hi = float(r["window_Host_ms_max"])
        c.text(835, y, names[r["mode"]], 19)
        c.rect(1015, y + 4, v * 1.65, 22, "#4187b4")
        c.text(1400, y, f"{v:.3f}", 19)
        c.line(1015 + lo * 1.65, y + 14, 1015 + hi * 1.65, y + 14, "#18364d", 2)
    c.text(835, 407, "Host窗口：Encoder+Expert及控制；Vision前缀另计。", 17)
    c.text(835, 434, "归还优于固定点，未优于串行；细线为样本 min–max。", 17)

    c.text(50, 505, "C  Expert后尾段｜v7 正常 Event 端点", 23)
    for i, r in enumerate([x for x in normal if x["mode"] in ("fixed", "return")]):
        y = 565 + i * 65
        v = float(r["Expert_to_Context_tail_ms_median"])
        c.text(50, y, names[r["mode"]], 20)
        c.rect(215, y + 4, v * 4.5, 24, "#59a591")
        c.text(580, y, f"{v:.3f} ms", 19)
    c.text(50, 719, "同轮固定-归还：28.212 / 28.352 / 28.421 ms", 18)
    c.text(50, 759, "窗口差：31.098 / 28.384 / 28.221 ms，成本已包含。", 17)
    c.text(50, 802, "同一剩余B2、状态逐位相同；不再次扣除控制开销。", 17)

    c.text(835, 505, "D  Kernel物理重叠｜v9 root诊断，各 n=1", 23)
    for i, r in enumerate(trace):
        y = 562 + i * 49
        v = float(r["overlap_ms"])
        c.text(835, y, names[r["mode"]], 19)
        c.rect(1015, y + 4, v * 7, 20, "#8b70bb")
        c.text(1400, y, f"{v:.3f} ms", 19)
    c.text(835, 780, "correlation归属 → 各任务区间并集 → 两者交集。", 17)
    c.text(835, 811, "每模式 108 + 99 + 2410 Kernel；丢失0，非性能统计。", 17)

    c.text(50, 885, "E  完整周期违约｜v4，每项三进程×64周期", 23)
    c.text(50, 930, "计划 / 固定干扰            180 ms：C；E             240 ms：C；E", 17)
    labels = [("whole_context", "none", "whole / 无"),
              ("whole_context", "memcpy32MiB", "whole / 访存"),
              ("two_blocks", "none", "双块 / 无"),
              ("two_blocks", "memcpy32MiB", "双块 / 访存")]
    for i, (plan, stress, lbl) in enumerate(labels):
        y = 973 + i * 42
        c.text(50, y, lbl, 18)
        for j, P in enumerate((180, 240)):
            rr = sorted([r for r in cells if r["plan"] == plan and r["interference"] == stress
                         and int(r["P_ms"]) == P], key=lambda r: int(r["repeat"]))
            vals = "/".join(r["cycle_miss"] for r in rr) + "；" + "/".join(r["Expert_miss"] for r in rr)
            c.text(285 + j * 225, y, vals, 18)
    c.text(50, 1163, "C=完整周期，E=Expert；各分母64；双块无稳定改善。", 16)

    c.text(835, 885, "F  边界与控制成本｜v7 正常测量", 23)
    for i, t in enumerate(["Expert→数学边界：0 ms（本次均已完成）",
                           "→D2D后可调度边界：0.297–0.405 ms",
                           "资源创建：11.625 ms（一次性）",
                           "归还判断→B2提交前：0.054–0.056 ms",
                           "归还判断→B2提交返回：6.313–6.460 ms",
                           "v9已关联首次B2 Kernel；未扩容运行中Kernel."]):
        c.text(835, 942 + i * 37, t, 18)

    c.text(35, 1251, "首周测量可提交验收；限定Encoder路径正确且有物理重叠，尚无相对串行净优势。B1/B2待用户选择。", 21)
    src = "quota sweep result.json" if qrows else "旧 isolated_limit_20261015（A面板待回填）"
    c.text(35, 1290, f"数据：{src}；v4 CELLS.csv；v7 MODE_SUMMARY.csv；v9 KERNEL_SUMMARY.csv。", 16)
    c.save(a.out_name)
    print(f"WROTE {OUT / (a.out_name + '.svg')} and .png; quota_rows={bool(qrows)}")


if __name__ == "__main__":
    main()
