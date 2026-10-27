"""Consistency check for the corrected B5 report record.

Checks, without model/SSH/hardware access:
  * REPORT_CORRECTIONS.json `after.sha256` equals the actual RUN_REPORT.md SHA;
  * the saved `before` copy still hashes to its recorded SHA;
  * the report size/line count recorded in the JSON agree with the file;
  * REBUILD_CHECK.json has a complete, runnable command (no ellipsis), imports
    `../../plan_feasibility_v1_r1`, names the B5 result explicitly, and the
    verifier can be executed with a zero exit code;
  * the saved rebuild output hash agrees with the recorded one;
  * every entry in FINGERPRINTS.json matches the file on disk.

Exit status: 0 = PASS, 1 = mismatch/read error.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUN = HERE.parent
REPORT = RUN / "RUN_REPORT.md"
CORRECTIONS = HERE / "REPORT_CORRECTIONS.json"
REBUILD = HERE / "REBUILD_CHECK.json"
FINGERPRINTS = HERE / "FINGERPRINTS.json"
REBUILD_OUTPUT = HERE / "REBUILD_CHECK_OUTPUT.json"


def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def check(condition, name, detail, checks):
    checks.append(dict(name=name, pass_=bool(condition), detail=detail))
    return bool(condition)


def main():
    checks = []
    failures = []
    corrections = json.loads(CORRECTIONS.read_text())
    rebuild = json.loads(REBUILD.read_text())
    fingerprints = json.loads(FINGERPRINTS.read_text()) if FINGERPRINTS.is_file() else {}

    actual_report_sha = sha256_file(REPORT)
    after = corrections.get("after", {})
    if not check(after.get("sha256") == actual_report_sha, "after_sha_equals_report",
                 dict(recorded=after.get("sha256"), actual=actual_report_sha), checks):
        failures.append("after.sha256 != RUN_REPORT.md sha256")
    if not check(after.get("bytes") in (None, REPORT.stat().st_size), "after_bytes",
                 dict(recorded=after.get("bytes"), actual=REPORT.stat().st_size), checks):
        failures.append("after.bytes mismatch")
    lines = len(REPORT.read_text().splitlines())
    if not check(after.get("lines") in (None, lines), "after_lines",
                 dict(recorded=after.get("lines"), actual=lines), checks):
        failures.append("after.lines mismatch")

    before = corrections.get("before", {})
    before_path = RUN / before.get("path", "")
    if not check(before_path.is_file(), "before_copy_exists", str(before_path), checks):
        failures.append("before copy missing")
    elif not check(sha256_file(before_path) == before.get("sha256"), "before_sha",
                   dict(recorded=before.get("sha256"), actual=sha256_file(before_path)), checks):
        failures.append("before copy sha mismatch")

    if not check(len(corrections.get("corrections", [])) >= 7, "correction_items",
                 len(corrections.get("corrections", [])), checks):
        failures.append("too few correction items")

    consistency = corrections.get("consistency", {})
    if not check(consistency.get("recomputed_sha256") == actual_report_sha, "recorded_recomputed_sha",
                 dict(recorded=consistency.get("recomputed_sha256"), actual=actual_report_sha), checks):
        failures.append("consistency.recomputed_sha256 mismatch")
    if not check(consistency.get("match") is True, "recorded_match", consistency.get("match"), checks):
        failures.append("consistency.match is not true")

    command = rebuild.get("command", "")
    if not check("..." not in command and "…" not in command, "rebuild_command_no_ellipsis",
                 command, checks):
        failures.append("rebuild command contains an ellipsis")
    if not check("../../plan_feasibility_v1_r1" in command, "rebuild_analysis_path",
                 command, checks):
        failures.append("rebuild command does not use ../../plan_feasibility_v1_r1")
    if not check("board/run_01/model/result.json" in command, "rebuild_b5_result_explicit",
                 command, checks):
        failures.append("rebuild command does not name the B5 result explicitly")
    if not check("corrections/verify_rebuild_b5.py" in command, "rebuild_command_runnable",
                 command, checks):
        failures.append("rebuild command does not invoke the checked verifier")

    executed = rebuild.get("executed", {})
    if not check(executed.get("exit_code") == 0, "rebuild_recorded_exit",
                 executed.get("exit_code"), checks):
        failures.append("recorded rebuild exit is not 0")
    if not check(REBUILD_OUTPUT.is_file(), "rebuild_output_exists", str(REBUILD_OUTPUT), checks):
        failures.append("rebuild output missing")
    elif not check(sha256_file(REBUILD_OUTPUT) == executed.get("output_sha256"), "rebuild_output_sha",
                   dict(recorded=executed.get("output_sha256"), actual=sha256_file(REBUILD_OUTPUT)),
                   checks):
        failures.append("rebuild output sha mismatch")

    # Execute the recorded command's verifier (without writing a new output).
    run_cwd = RUN
    verifier = ["python3", "corrections/verify_rebuild_b5.py",
                "--result", "board/run_01/model/result.json",
                "--analysis", "../../plan_feasibility_v1_r1"]
    proc = subprocess.run(verifier, cwd=run_cwd, text=True, capture_output=True)
    executed_ok = proc.returncode == 0
    if not check(executed_ok, "rebuild_executes_zero_exit",
                 dict(returncode=proc.returncode, stdout=proc.stdout.strip(),
                      stderr=proc.stderr.strip()[-1000:]), checks):
        failures.append("recorded rebuild command returned non-zero")
    if executed_ok:
        try:
            live = json.loads(proc.stdout.strip().splitlines()[-1])
        except Exception as exc:  # pragma: no cover - diagnostic path
            live = {}
            failures.append("cannot parse live rebuild output: %s" % exc)
        if not check(live.get("status") == "PASS" and live.get("issues") == 0
                     and live.get("cycles") == 64 and live.get("refreshes") == 32,
                     "rebuild_live_result", live, checks):
            failures.append("live rebuild did not report PASS 64/32/0")
        if not check(live.get("result_sha256") == rebuild.get("input", {}).get("sha256"),
                     "rebuild_live_input_sha", live.get("result_sha256"), checks):
            failures.append("live rebuild input sha differs")
        if "issue_detail" in live:
            if not check(live.get("issue_detail") == [], "rebuild_live_issue_detail",
                         live.get("issue_detail"), checks):
                failures.append("live rebuild reports issue detail")

    for name, expected in sorted(fingerprints.items()):
        path = RUN / name
        ok = path.is_file() and sha256_file(path) == expected
        if not check(ok, "fingerprint:%s" % name,
                     dict(path=str(path), expected=expected,
                          actual=sha256_file(path) if path.is_file() else None), checks):
            failures.append("fingerprint mismatch: %s" % name)

    status = "PASS" if not failures else "FAIL"
    summary = dict(
        status=status,
        scope="CPU/offline consistency check; no model, SSH, scope, hardware write",
        checks=checks,
        failures=failures,
        report=dict(path=str(REPORT.relative_to(RUN)), sha256=actual_report_sha,
                    bytes=REPORT.stat().st_size, lines=lines),
        rebuild=dict(command=command, exit_code=proc.returncode,
                     stdout=proc.stdout.strip()),
    )
    print(json.dumps({k: summary[k] for k in ("status", "failures", "report", "rebuild")},
                     ensure_ascii=False))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
