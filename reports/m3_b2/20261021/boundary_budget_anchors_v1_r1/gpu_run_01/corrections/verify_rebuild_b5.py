"""Independently rebuild the B5 statistics from the raw maps and compare job by job.

The analysis module is imported from the explicit `--analysis` directory
(`../../plan_feasibility_v1_r1` when run from `gpu_run_01`).  The B5 result file
is given explicitly; the module's default result (B4) is never used.  Stored
statistics are outputs and are only read for comparison.  Nothing is written
unless `--json` is passed, and the input result is never modified.

Exit status: 0 = PASS, 1 = mismatch, 2 = usage/read error.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

DEFAULT_RESULT = "board/run_01/model/result.json"
DEFAULT_ANALYSIS = "../../plan_feasibility_v1_r1"
EXPECTED_CYCLES = 64
EXPECTED_REFRESHES = 32


def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--result", default=DEFAULT_RESULT,
                    help="B5 result.json (relative to the current directory)")
    ap.add_argument("--analysis", default=DEFAULT_ANALYSIS,
                    help="directory containing rebuild_stats.py")
    ap.add_argument("--json", default=None,
                    help="optional machine-readable output path")
    args = ap.parse_args(argv)

    result_path = Path(args.result).resolve()
    analysis_dir = Path(args.analysis).resolve()
    if not result_path.is_file():
        print("ERROR: result not found: %s" % result_path, file=sys.stderr)
        return 2
    if not (analysis_dir / "rebuild_stats.py").is_file():
        print("ERROR: rebuild_stats.py not found under %s" % analysis_dir, file=sys.stderr)
        return 2

    sys.path.insert(0, str(analysis_dir))
    import rebuild_stats  # noqa: E402  (path is explicit)

    doc = json.loads(result_path.read_text())

    issues = []
    segments = []
    total_cycles = total_refreshes = 0
    for seg in doc.get("segments", []):
        sid = seg.get("segment_id")
        ncycles = int(seg["manifest"]["cycles"])
        nrefreshes = ncycles // 2
        raw = rebuild_stats.raw_maps(seg)
        rebuilt = rebuild_stats.rebuild(raw)
        derived = rebuild_stats.derived_responses(raw, rebuilt)
        mismatch = rebuild_stats.compare_with_stored(seg, rebuilt, derived)
        operation_issues = rebuild_stats.cross_check_operations(seg)

        if len(rebuilt["cycles"]) != ncycles:
            mismatch.append("rebuilt cycle count %d != manifest %d"
                            % (len(rebuilt["cycles"]), ncycles))
        if len(rebuilt["refreshes"]) != nrefreshes:
            mismatch.append("rebuilt refresh count %d != manifest %d"
                            % (len(rebuilt["refreshes"]), nrefreshes))
        for row in rebuilt["cycles"]:
            if row["deadline_ns"] - row["release_ns"] != int(seg["manifest"]["period_ns"]):
                mismatch.append("cycle %d deadline-release != period"
                                % row["cycle"])

        total_cycles += len(rebuilt["cycles"])
        total_refreshes += len(rebuilt["refreshes"])
        segments.append(dict(
            segment_id=sid,
            cycles=len(rebuilt["cycles"]),
            refreshes=len(rebuilt["refreshes"]),
            stored_cycle_counts=seg.get("statistics", {}).get("cycle_counts"),
            rebuilt_cycle_counts=rebuilt["cycle_counts"],
            stored_refresh_counts=seg.get("statistics", {}).get("refresh_counts"),
            rebuilt_refresh_counts=rebuilt["refresh_counts"],
            mismatch_count=len(mismatch),
            operation_mismatch_count=len(operation_issues),
            mismatches=mismatch[:20],
            operation_mismatches=operation_issues[:20],
        ))
        for item in mismatch:
            issues.append("%s: %s" % (sid, item))
        for item in operation_issues:
            issues.append("%s: %s" % (sid, item))

    if len(doc.get("segments", [])) != 8:
        issues.append("expected 8 segments, got %d" % len(doc.get("segments", [])))
    if (total_cycles, total_refreshes) != (EXPECTED_CYCLES, EXPECTED_REFRESHES):
        issues.append("expected %d cycles/%d refreshes, got %d/%d"
                      % (EXPECTED_CYCLES, EXPECTED_REFRESHES, total_cycles, total_refreshes))

    status = "PASS" if not issues else "FAIL"
    out = dict(
        status=status,
        scope="CPU/offline only; raw maps -> frozen replay_stats; job-by-job compare; no stored statistic used as input",
        command=" ".join([sys.executable] + sys.argv),
        result_path=str(result_path),
        result_sha256=sha256_file(result_path),
        analysis_dir=str(analysis_dir),
        rebuild_stats_path=str(analysis_dir / "rebuild_stats.py"),
        rebuild_stats_sha256=sha256_file(analysis_dir / "rebuild_stats.py"),
        model_env_sha256=sha256_file(analysis_dir / "model_env.py"),
        stats_module=getattr(rebuild_stats, "m2_executor", None).__file__,
        stats_module_sha256=sha256_file(rebuild_stats.m2_executor.__file__),
        segments=segments,
        cycles=total_cycles,
        refreshes=total_refreshes,
        issues=len(issues),
        issue_detail=issues[:50],
    )
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: out[k] for k in
                      ("status", "cycles", "refreshes", "issues", "result_sha256")},
                     sort_keys=True))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
