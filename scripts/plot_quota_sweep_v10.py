#!/usr/bin/env python3
"""Parse a quota-sweep result.json and draw the legal-SM quota response curve.

Offline only: reads the board result copied back to the workspace. Never invents
points; a quota without formal samples is drawn as NOT_LEGAL/NOT_RUN, not as a
fabricated value. Event time is an execution envelope, not pure kernel time.
"""
import argparse
import csv
import json
import html
import statistics
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "reports/m1_acceptance/week1_closure_20261018"
FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"


def load_result(path):
    return json.loads(Path(path).read_text())


def formal_values(samples, quota, kind):
    vals, hosts, b1, b2 = [], [], [], []
    for s in samples:
        if s.get("quota") != quota or s.get("kind") != kind:
            continue
        if s.get("role") != "formal":
            continue
        vals.append(float(s["event_ms"]))
        hosts.append(float(s["host_response_ms"]))
        if kind == "Context":
            if "B1_event_ms" in s: b1.append(float(s["B1_event_ms"]))
            if "B2_event_ms" in s: b2.append(float(s["B2_event_ms"]))
    return vals, hosts, b1, b2


def full_reference(samples, kind):
    vals, hosts = [], []
    for s in samples:
        if s.get("config") == "full" and s.get("kind") == kind and s.get("role") == "reference":
            vals.append(float(s["event_ms"]))
            hosts.append(float(s["host_response_ms"]))
    return vals, hosts


def med(v):
    return statistics.median(v) if v else None


def parse(result):
    samples = result.get("samples", [])
    quota_status = result.get("quota_status", {})
    probe = result.get("probe", {})
    quotas = sorted({int(s["quota"]) for s in samples if s.get("quota") is not None} | {int(k) for k in quota_status})
    rows = []
    for q in quotas:
        sm_ids = probe.get(f"green{q}", {}).get("SM_ids")
        status = quota_status.get(str(q), {}).get("status", "PASS")
        for kind in ("Context", "Expert"):
            vals, hosts, b1, b2 = formal_values(samples, q, kind)
            if not vals:
                rows.append(dict(quota=q, kind=kind, status=status, sm_ids=sm_ids,
                                 observed_sm_count=len(sm_ids) if sm_ids else 0,
                                 n_formal=0, event_median_ms=None, event_min_ms=None,
                                 event_max_ms=None, host_median_ms=None,
                                 b1_median_ms=None, b2_median_ms=None,
                                 full_reference=False))
                continue
            rows.append(dict(
                quota=q, kind=kind, status=status, sm_ids=sm_ids,
                observed_sm_count=len(sm_ids) if sm_ids else 0,
                n_formal=len(vals),
                event_median_ms=med(vals), event_min_ms=min(vals), event_max_ms=max(vals),
                host_median_ms=med(hosts),
                b1_median_ms=med(b1) if kind == "Context" else None,
                b2_median_ms=med(b2) if kind == "Context" else None,
                full_reference=False,
            ))
    for kind in ("Context", "Expert"):
        vals, hosts = full_reference(samples, kind)
        if vals:
            rows.append(dict(
                quota=16, kind=kind, status="FULL_REFERENCE",
                sm_ids=probe.get("full", {}).get("SM_ids"),
                observed_sm_count=len(probe.get("full", {}).get("SM_ids", [])),
                n_formal=len(vals),
                event_median_ms=med(vals), event_min_ms=min(vals), event_max_ms=max(vals),
                host_median_ms=med(hosts),
                b1_median_ms=None, b2_median_ms=None, full_reference=True,
            ))
    return rows


class Canvas:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.im = Image.new("RGB", (w, h), "#f5f7fb")
        self.d = ImageDraw.Draw(self.im)
        self.svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
                    f'viewBox="0 0 {w} {h}"><rect width="100%" height="100%" fill="#f5f7fb"/>']

    def rect(self, x, y, w, h, c, stroke=None):
        self.d.rectangle([x, y, x + w, y + h], fill=c, outline=stroke)
        self.svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{c}"'
                        + (f' stroke="{stroke}"' if stroke else "") + "/>")

    def text(self, x, y, t, size=20, c="#23324a"):
        self.d.text((x, y), str(t), font=ImageFont.truetype(FONT, size), fill=c)
        self.svg.append(f'<text x="{x}" y="{y + size}" font-family="PingFang SC,Arial,sans-serif" '
                        f'font-size="{size}" fill="{c}">{html.escape(str(t))}</text>')

    def line(self, x, y, x2, y2, c="#aab5c4", w=1):
        self.d.line((x, y, x2, y2), fill=c, width=w)
        self.svg.append(f'<line x1="{x}" y1="{y}" x2="{x2}" y2="{y2}" stroke="{c}" stroke-width="{w}"/>')

    def dot(self, x, y, r, c):
        self.d.ellipse([x - r, y - r, x + r, y + r], fill=c)
        self.svg.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{c}"/>')

    def save(self, path):
        Path(path).with_suffix(".svg").write_text("\n".join(self.svg + ["</svg>"]))
        self.im.save(Path(path).with_suffix(".png"))


def draw(rows, out_path, result):
    W, H = 1500, 900
    c = Canvas(W, H)
    status = result.get("status", "UNKNOWN")
    c.text(35, 22, "CoOverlap M1｜合法 SM 配额响应（锁频，隔离 Context/Expert）", 30)
    c.text(35, 70, f"运行状态 {status}；formal 每配额 n=3，full 16SM 为参考 n=1；"
                   "Event 是执行包围区间，不是纯 Kernel 时间。", 18)
    colors = {"Context": "#2479b5", "Expert": "#d27a2c"}
    titles = {"Context": "A  完整 Context（18层 Encoder）", "Expert": "B  完整 Expert（10步×18层 Decoder）"}
    for pi, kind in enumerate(("Context", "Expert")):
        ox, oy, pw, ph = 60 + pi * 720, 130, 640, 560
        c.rect(ox - 10, oy - 15, pw + 20, ph + 95, "#ffffff")
        c.text(ox, oy - 5, titles[kind], 21)
        sub = [r for r in rows if r["kind"] == kind]
        if not sub:
            c.text(ox + 20, oy + 60, "没有该类型的样本", 18, "#9b3b3b")
            continue
        xs = sorted({r["quota"] for r in sub})
        vals = [r["event_median_ms"] for r in sub if r["event_median_ms"] is not None]
        if not vals:
            c.text(ox + 20, oy + 60, "没有 formal 样本（仅参考/NOT_LEGAL）", 18, "#9b3b3b")
            continue
        x0, y0 = ox + 80, oy + ph - 70
        x1, y1 = ox + pw - 30, oy + 70
        maxv = max(vals) * 1.18
        minv = 0
        c.line(x0, y0, x1, y0)
        c.line(x0, y0, x0, y1)
        for v in [0, maxv / 2, maxv]:
            yy = y0 - (y0 - y1) * v / maxv
            c.line(x0 - 5, yy, x0, yy, "#8a99ab")
            c.text(x0 - 62, yy - 8, f"{v:.0f}", 13, "#5a6b80")
        c.text(x0 - 62, y0 + 30, "ms", 13, "#5a6b80")
        # x scale: quotas 2..16, linear
        xmin, xmax = 0, 16
        def X(q): return x0 + (x1 - x0) * (q - xmin) / (xmax - xmin)
        def Y(v): return y0 - (y0 - y1) * (v - minv) / (maxv - minv)
        for q in range(0, 17, 2):
            xx = X(q)
            c.line(xx, y0, xx, y0 + 5, "#8a99ab")
            c.text(xx - 8, y0 + 10, str(q), 13, "#5a6b80")
        c.text(x1 - 20, y0 + 30, "SM", 13, "#5a6b80")
        # full reference line
        full = next((r for r in sub if r.get("full_reference")), None)
        if full and full["event_median_ms"] is not None:
            yy = Y(full["event_median_ms"])
            c.line(x0, yy, x1, yy, "#999999", 2)
            c.dot(X(16), yy, 5, "#999999")
            c.text(x0 + 10, yy - 22, f"full 16SM ref {full['event_median_ms']:.1f} ms", 13, "#666666")
        # points + min/max bars
        pts = []
        for r in sub:
            if r.get("full_reference"):
                continue
            q = r["quota"]; xx = X(q)
            if r["status"] != "PASS":
                c.text(xx - 32, y0 - 45, "NOT_LEGAL", 10, "#b03a3a")
                continue
            if r["event_median_ms"] is None:
                continue
            yy = Y(r["event_median_ms"]); pts.append((xx, yy))
            c.line(xx, Y(r["event_min_ms"]), xx, Y(r["event_max_ms"]), colors[kind], 2)
            c.line(xx - 6, Y(r["event_min_ms"]), xx + 6, Y(r["event_min_ms"]), colors[kind], 2)
            c.line(xx - 6, Y(r["event_max_ms"]), xx + 6, Y(r["event_max_ms"]), colors[kind], 2)
            c.dot(xx, yy, 5, colors[kind])
            c.text(xx - 22, yy - 30, f"{r['event_median_ms']:.1f}", 13, "#23324a")
            c.text(xx - 18, y0 + 28, f"q{ q }", 11, "#5a6b80")
        if len(pts) >= 2:
            pts.sort()
            for i in range(len(pts) - 1):
                c.line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], colors[kind], 3)
        # observed SM ids line
        notes = []
        for r in sub:
            if r["sm_ids"]:
                notes.append(f"q{r['quota']}:{r['observed_sm_count']}/{len(r['sm_ids'])}")
        if notes:
            c.text(ox + 10, oy + ph + 20, "探针观察 SM 数/集合大小：" + "  ".join(notes), 12, "#5a6b80")
    c.text(35, H - 105, "来源：quota sweep result.json；每配额 formal n=3；full 参考 n=1。"
                        "所有点必须同时通过逐字节/旧KV/18层/10步/语言/地址/内存闸门。", 14, "#5a6b80")
    c.text(35, H - 78, "Event 为执行包围区间，非纯 Kernel 服务时间；不与 v7 配对 Host 窗口或 v9 诊断 Kernel 重叠求速度比。", 14, "#5a6b80")
    c.text(35, H - 51, "若某配额 NOT_LEGAL，只表示驱动拒绝该 Green Context 配额，不是模型数值 FAIL；原始 result.json 保留。", 14, "#5a6b80")
    c.save(out_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--result", default=None)
    ap.add_argument("--out", default=str(DEFAULT_OUT / "QUOTA_SWEEP"))
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.result:
        path = Path(a.result)
    else:
        cands = sorted((DEFAULT_OUT / "quota_sweep/board").glob("*/result.json"))
        if not cands:
            print("NO_RESULT: copy the board run directory to "
                  "reports/m1_acceptance/week1_closure_20261018/quota_sweep/board/<run>/ first", file=sys.stderr)
            return 2
        path = cands[-1]
    result = load_result(path)
    rows = parse(result)
    print(json.dumps(dict(result=str(path), status=result.get("status"),
                          rows=rows), indent=1, ensure_ascii=False))
    if a.check:
        return 0
    out_csv = Path(str(a.out) + ".csv")
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    draw(rows, a.out, result)
    print(f"WROTE {out_csv} and {a.out}.svg/.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
