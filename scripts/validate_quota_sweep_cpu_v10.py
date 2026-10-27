#!/usr/bin/env python3
"""CPU-only static checks for the locked-frequency legal-quota sweep (v10).

No model, no GPU, no board write. Verifies the staged protocol, the new runtime
and model script, the frequency scope and the batch wrapper against the frozen
fixed-load and safety contract. Exit 0 only if every check passes.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
Q = ROOT / "reports/m1_acceptance/week1_closure_20261018/quota_sweep"
protocol = json.loads((Q / "PROTOCOL.json").read_text())
sweep = (Q / "pi05_quota_sweep_v10.py").read_text()
runtime = (Q / "quota_runtime_resource_v10.py").read_text()
batch = (Q / "run_batch.sh").read_text()
scope = (Q / "m1_clock_scope_v4.py").read_text()
manifest = (Q / "DEPLOY_SHA256.txt").read_text().splitlines()

checks = []
def check(name, ok, detail=""):
    checks.append(dict(name=name, pass_=bool(ok), detail=str(detail)))

# ---- protocol contract -------------------------------------------------
q = protocol["quota_points"]
check("quotas_ascending_unique", q == sorted(set(q)), q)
check("quotas_legal_even_2_16", all(2 <= x <= 16 and x % 2 == 0 for x in q), q)
check("quota_min_is_runtime_min", min(q) == 2, min(q))
check("fixed_bf16", protocol["dtype"] == "BF16")
check("fixed_views_2", protocol["views"] == 2)
check("fixed_prompt_49", protocol["prompt_tokens"] == 49)
check("fixed_encoder_561", protocol["encoder_seq"] == 561)
check("fixed_layers_18", protocol["encoder_layers"] == 18)
check("fixed_actions_50", protocol["action_chunk"] == 50)
check("fixed_denoise_10", protocol["denoise_steps"] == 10)
check("no_graph", protocol["graph"] is False)
check("no_concurrent", protocol["concurrent"] is False)
check("no_root", protocol["root"] is False)
check("no_collector", protocol["collector"] is False)
check("one_process", protocol["process_limit"] == 1)
check("zero_retries", protocol["retries"] == 0)
check("timeout_179", protocol["timeout_total_s"] == 179)
check("soft_165", protocol["soft_no_new_work_after_s"] == 165)
check("frequency_cpu_max", protocol["frequency"]["CPU_minmax_kHz"] == 2201600)
check("frequency_gpu_max", protocol["frequency"]["GPU_minmax_Hz"] == 1300500000)
check("frequency_emc_max", protocol["frequency"]["EMC_minmax_Hz"] == 3199000000)
check("only_five_min_nodes", protocol["frequency"]["only_five_min_nodes"] is True)

# ---- sample arithmetic -------------------------------------------------
per_quota = 10  # gate Context+Expert, warmup Context+Expert, formal 3+3
expected_records = 2 + len(q) * per_quota
check("sample_records_match", protocol["total_sample_records_upper_bound"] == expected_records,
      (protocol["total_sample_records_upper_bound"], expected_records))
measured = protocol["measured_ledger"]
check("formal_context_21", measured["Context_formal"] == 3 * len(q))
check("formal_expert_21", measured["Expert_formal"] == 3 * len(q))
check("gate_separate_7", protocol["separate_ledger"]["quota_gate_Context"] == len(q))
check("probe_count_8", protocol["separate_ledger"]["SM_probes"] == len(q) + 1)

# ---- model script ------------------------------------------------------
for token, name in [
    ("from quota_runtime_resource_v10 import QuotaRuntime", "imports_quota_runtime"),
    ("rt.create_green(q)", "calls_create_green"),
    ("rt.destroy_green()", "calls_destroy_green"),
    ("_full_context_byte_exact", "context_byte_exact"),
    ("_old_KV_unchanged", "old_kv_unchanged"),
    ("_18_layers", "encoder_18_layers"),
    ("_10_steps", "decoder_10_steps"),
    ("language_immutable", "language_immutable"),
    ("visible_addresses_stable", "addresses_stable"),
    ("memory_floor_after", "memory_floor"),
    ("COOVERLAP_PROTOCOL_SHA", "protocol_sha_env"),
    ("NOT_LEGAL", "non_legal_quota_handling"),
    ("soft_no_new_work_after_s", "soft_limit_from_protocol"),
    ("p._graph is None", "no_graph"),
    ("original_autotune_once", "autotune_once"),
]:
    check(name, token in sweep, token)
check("no_hardcoded_108", "108" not in sweep.replace("bee648c5b5a9821084a39bb88ed9cba9681503c1043f90a7c95ace0bb1048d78",""))
check("no_green8_hardcode", "green8" not in sweep)
check("event_count_enough", "n_measure = 2 + len(cfg['quota_points']) * 10 + 8" in sweep)
check("fixture_sha_fixed",
      "92f1a92b64352cc34010c81c1accd1cb00fcb227d0004f545b87549d5d6c544d" in sweep)
check("checkpoint_config_sha_fixed",
      "0458a362b574c2cb088ebf3767c9eacb1f040b9cb680a89b594379a4fe36e5f7" in sweep)
check("extension_sha_fixed",
      "bee648c5b5a9821084a39bb88ed9cba9681503c1043f90a7c95ace0bb1048d78" in sweep)

# ---- runtime -----------------------------------------------------------
for token, name in [
    ("class QuotaRuntime", "quota_runtime_class"),
    ("cudaDevSmResourceSplitByCount", "split_api"),
    ("cudaDevResourceGenerateDesc", "desc_api"),
    ("cudaGreenCtxCreate", "green_ctx_api"),
    ("cudaExecutionCtxStreamCreate", "green_stream_api"),
    ("cudaExecutionCtxDestroy", "ctx_destroy"),
    ("cudaStreamDestroy", "stream_destroy"),
    ("groups[0].data.sm.smCount != q", "exact_quota_group"),
    ("q % sm.smCoscheduledAlignment", "alignment_check"),
]:
    check(name, token in runtime, token)
check("runtime_same_abi_assert", "C.sizeof(Resource) == 144" in runtime)
check("runtime_no_reset", "cudaDeviceReset" not in runtime)
check("runtime_no_current_context_switch",
      "cudaSetDevice" not in runtime and "cuCtxSetCurrent" not in runtime)

# ---- batch wrapper -----------------------------------------------------
for token, name in [
    ("set -euo pipefail", "bash_strict"),
    ('test "$(id -un)" = nvidia', "runs_as_nvidia"),
    ('test "$(id -u)" -ne 0', "not_root"),
    ("sha256sum -c DEPLOY_SHA256.txt", "manifest_verify"),
    ("timeout --kill-after=1s 179s", "hard_timeout"),
    ("taskset -c 0-10", "cpu_affinity"),
    ("COOVERLAP_PROBE_CUBIN", "probe_cubin"),
    ("COOVERLAP_PROTOCOL_SHA=458bbeac6968b99c5dc0f03de475d4edaa9e354d265d44bcb49b381833f86329",
     "protocol_sha_literal"),
    ("PYTHONPATH=", "pythonpath"),
]:
    check(name, token in batch, token)
check("batch_no_sudo", "sudo" not in batch)
check("batch_no_root_launcher", "runuser" not in batch)

# ---- scope -------------------------------------------------------------
for token, name in [
    ("--scope", "scope_cli"),
    ("runuser", "drops_to_nvidia"),
    ("RESTORED_FIVE_MINIMA", "restore_marker"),
    ("SnapshotTransaction", "snapshot_transaction"),
    ("2201600", "cpu_max"),
    ("1300500000", "gpu_max"),
    ("3199000000", "emc_max"),
]:
    check(name, token in scope, token)
check("scope_five_nodes", len(re.findall(r"\('(?:cpu0|cpu4|cpu8|gpu|emc)'", scope)) >= 5)
check("scope_same_dir_batch_rule", "with_name('run_batch.sh')" in scope)

# ---- manifest ----------------------------------------------------------
manifest_map = {}
for line in manifest:
    h, name = line.split()
    manifest_map[name] = h
check("manifest_has_all_files",
      set(manifest_map) >= {"PROTOCOL.json", "pi05_quota_sweep_v10.py",
                            "quota_runtime_resource_v10.py", "run_batch.sh",
                            "m1_clock_scope_v4.py"}, set(manifest_map))
for name, h in manifest_map.items():
    p = Q / name
    check("manifest_hash_" + name, p.exists() and hashlib.sha256(p.read_bytes()).hexdigest() == h)
check("protocol_sha_matches_batch",
      manifest_map.get("PROTOCOL.json") == "458bbeac6968b99c5dc0f03de475d4edaa9e354d265d44bcb49b381833f86329")

# ---- report ------------------------------------------------------------
failed = [c for c in checks if not c["pass_"]]
out = dict(checks=len(checks), failed=len(failed),
           status="PASS" if not failed else "FAIL",
           failures=failed)
print(json.dumps(out, indent=1, ensure_ascii=False))
sys.exit(0 if not failed else 1)
