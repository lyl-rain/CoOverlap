#!/usr/bin/env python3
"""Read-only B7 stage-interval decomposition.

Usage:
    python3 corrections/analyze_b7_stage_intervals.py RESULT.json OUT_DIR

The script never writes to RESULT.json or the frozen deployment.  It validates
the 22 Host timestamps for every one of the 4 segments x 4 stages, computes the
fixed non-overlapping Host intervals, and reports the unclassified gaps.  Event
GPU envelopes are read from the frozen operation rows and are reported
separately; they are never added to Host intervals.
"""
import argparse
import csv
import hashlib
import json
import math
import sys
from pathlib import Path

PROTOCOL = 'm3_b7_stage_startup_v1'
REQUIRED = (
    'stage_enter', 'stage_exit',
    'event0_before', 'event0_after',
    'event1_before', 'event1_after',
    'event2_before', 'event2_after',
    'event7_before', 'event7_after',
    'restore_images_before', 'restore_images_after',
    'restore_noise_before', 'restore_noise_after',
    'capture_images_before', 'capture_images_after',
    'capture_noise_before', 'capture_noise_after',
    'event7_wait_before', 'event7_wait_after',
    'confirmation_before', 'confirmation_after',
)
# Fixed interval banks.  Each tuple is (name, start_tag, end_tag).
INTERVALS = (
    ('event0_record', 'event0_before', 'event0_after'),
    ('event1_record', 'event1_before', 'event1_after'),
    ('restore_images', 'restore_images_before', 'restore_images_after'),
    ('restore_noise', 'restore_noise_before', 'restore_noise_after'),
    ('capture_images', 'capture_images_before', 'capture_images_after'),
    ('capture_noise', 'capture_noise_before', 'capture_noise_after'),
    ('event2_record', 'event2_before', 'event2_after'),
    ('event7_record', 'event7_before', 'event7_after'),
    ('event7_wait', 'event7_wait_before', 'event7_wait_after'),
    ('completion_confirmation', 'confirmation_before', 'confirmation_after'),
)


class AnalysisError(ValueError):
    pass


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def ms(ns):
    return round(ns / 1_000_000.0, 6)


def intervals_for(stage, segment_id):
    stamps = stage.get('timestamps')
    if not isinstance(stamps, dict):
        raise AnalysisError('%s/%s missing timestamps object' % (segment_id, stage.get('stage_index')))
    missing = [name for name in REQUIRED if name not in stamps]
    if missing:
        raise AnalysisError('%s/%s missing timestamp(s): %s'
                            % (segment_id, stage.get('stage_index'), ','.join(missing)))
    for name in REQUIRED:
        value = stamps[name]
        if not isinstance(value, int) or isinstance(value, bool):
            raise AnalysisError('%s/%s timestamp %s is not int: %r'
                                % (segment_id, stage.get('stage_index'), name, value))
    if stamps['stage_exit'] <= stamps['stage_enter']:
        raise AnalysisError('%s/%s non-positive stage interval' % (segment_id, stage.get('stage_index')))
    rows = []
    for name, start, end in INTERVALS:
        a, b = stamps[start], stamps[end]
        if b < a:
            raise AnalysisError('%s/%s negative interval %s' % (segment_id, stage.get('stage_index'), name))
        rows.append(dict(name=name, start_tag=start, end_tag=end, start_ns=a, end_ns=b, ms=ms(b - a)))
    rows.sort(key=lambda r: (r['start_ns'], r['end_ns'], r['name']))
    if stamps['stage_enter'] > rows[0]['start_ns']:
        raise AnalysisError('%s/%s interval starts before stage_enter' % (segment_id, stage.get('stage_index')))
    for prev, cur in zip(rows, rows[1:]):
        if cur['start_ns'] < prev['end_ns']:
            raise AnalysisError('%s/%s overlapping intervals %s/%s' %
                                (segment_id, stage.get('stage_index'), prev['name'], cur['name']))
    if rows[-1]['end_ns'] > stamps['stage_exit']:
        raise AnalysisError('%s/%s interval ends after stage_exit' % (segment_id, stage.get('stage_index')))
    gaps = []
    cursor = stamps['stage_enter']
    for row in rows:
        if row['start_ns'] > cursor:
            gaps.append(dict(label='gap_%d_%s' % (len(gaps), row['name']),
                             start_ns=cursor, end_ns=row['start_ns'], ms=ms(row['start_ns'] - cursor)))
        cursor = max(cursor, row['end_ns'])
    if stamps['stage_exit'] > cursor:
        gaps.append(dict(label='gap_%d_stage_exit' % len(gaps),
                         start_ns=cursor, end_ns=stamps['stage_exit'],
                         ms=ms(stamps['stage_exit'] - cursor)))
    stage_ms = ms(stamps['stage_exit'] - stamps['stage_enter'])
    covered_ns = sum(r['end_ns'] - r['start_ns'] for r in rows)
    gap_ns = sum(g['end_ns'] - g['start_ns'] for g in gaps)
    if covered_ns + gap_ns != stamps['stage_exit'] - stamps['stage_enter']:
        raise AnalysisError('%s/%s decomposition does not close' % (segment_id, stage.get('stage_index')))
    return rows, gaps, stage_ms, covered_ns, gap_ns


def stage_event_gpu(segment, index):
    key = 'R%d/stage' % index
    row = next((o for o in (segment.get('operations') or []) if o.get('key') == key), None)
    if row is None:
        raise AnalysisError('%s missing operation %s' % (segment.get('segment_id'), key))
    value = row.get('GPU_total_envelope_ms')
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise AnalysisError('%s/%s missing finite GPU_total_envelope_ms' % (segment.get('segment_id'), key))
    return float(value)


def analyze(result_path):
    result_path = Path(result_path).resolve()
    data = json.loads(result_path.read_text())
    return analyze_obj(data)


def analyze_obj(data):
    protocol_value = data.get('protocol')
    protocol_id = protocol_value.get('id') if isinstance(protocol_value, dict) else protocol_value
    if protocol_id != PROTOCOL:
        raise AnalysisError('unexpected protocol: %r' % (protocol_value,))
    segments = data.get('segments')
    if not isinstance(segments, list) or len(segments) != 4:
        raise AnalysisError('expected exactly 4 segments, got %r'
                            % (len(segments) if isinstance(segments, list) else segments))
    seen_segments = set()
    seen_pairs = set()
    rows_out = []
    for segment in segments:
        sid = segment.get('segment_id')
        if not isinstance(sid, str) or not sid or sid in seen_segments:
            raise AnalysisError('duplicate/empty segment_id: %r' % (sid,))
        seen_segments.add(sid)
        obs = segment.get('stage_observation')
        if not isinstance(obs, dict) or obs.get('complete') is not True:
            raise AnalysisError('%s stage_observation incomplete' % sid)
        stages = obs.get('stages')
        if not isinstance(stages, list) or len(stages) != 4:
            raise AnalysisError('%s expected 4 stage observations, got %r'
                                % (sid, len(stages) if isinstance(stages, list) else stages))
        for stage in stages:
            index = stage.get('stage_index')
            if index not in (0, 1, 2, 3) or (sid, index) in seen_pairs:
                raise AnalysisError('duplicate/unreviewed stage id %r/%r' % (sid, index))
            seen_pairs.add((sid, index))
            rows, gaps, stage_ms, covered_ns, gap_ns = intervals_for(stage, sid)
            by_name = {r['name']: r['ms'] for r in rows}
            event0_share = round(100.0 * by_name['event0_record'] / stage_ms, 4) if stage_ms else None
            rows_out.append(dict(
                segment_id=sid, cell=segment.get('cell'), lead_ns=segment.get('lead_ns'),
                stage_index=index, stage_host_ms=stage_ms,
                event0_record_ms=by_name['event0_record'],
                event1_record_ms=by_name['event1_record'],
                event2_record_ms=by_name['event2_record'],
                event7_record_ms=by_name['event7_record'],
                restore_images_ms=by_name['restore_images'],
                restore_noise_ms=by_name['restore_noise'],
                capture_images_ms=by_name['capture_images'],
                capture_noise_ms=by_name['capture_noise'],
                event7_wait_ms=by_name['event7_wait'],
                completion_confirmation_ms=by_name['completion_confirmation'],
                classified_sum_ms=ms(covered_ns), unclassified_gap_ms=ms(gap_ns),
                closure_ms=ms(covered_ns + gap_ns), closure_delta_ms=ms(covered_ns + gap_ns - (stage['timestamps']['stage_exit'] - stage['timestamps']['stage_enter'])),
                event0_share_percent=event0_share,
                event_gpu_ms=stage_event_gpu(segment, index),
                intervals={r['name']: r['ms'] for r in rows}, gaps=gaps))
    if len(rows_out) != 16 or len(seen_pairs) != 16 or len(seen_segments) != 4:
        raise AnalysisError('coverage is not 4x4')
    return data, rows_out


def write_outputs(result_path, out_dir, source_path, script_path):
    result_path = Path(result_path).resolve(); out_dir = Path(out_dir).resolve()
    source_path = Path(source_path).resolve(); script_path = Path(script_path).resolve()
    out_dir.mkdir(parents=True, exist_ok=False)
    data, rows = analyze(result_path)
    fields = ['segment_id', 'cell', 'lead_ns', 'stage_index', 'stage_host_ms',
              'event0_record_ms', 'event1_record_ms', 'event2_record_ms', 'event7_record_ms',
              'restore_images_ms', 'restore_noise_ms', 'capture_images_ms', 'capture_noise_ms',
              'event7_wait_ms', 'completion_confirmation_ms', 'classified_sum_ms',
              'unclassified_gap_ms', 'closure_ms', 'closure_delta_ms',
              'event0_share_percent', 'event_gpu_ms']
    out_json = out_dir/'B7_STAGE_INTERVALS.json'
    out_csv = out_dir/'B7_STAGE_INTERVALS.csv'
    out_md = out_dir/'B7_STAGE_INTERVALS.md'
    payload = dict(
        schema='m3_b7_stage_interval_decomposition_v1', protocol=PROTOCOL,
        input=str(result_path), input_sha256=sha256(result_path),
        source=str(source_path), source_sha256=sha256(source_path),
        script=str(script_path), script_sha256=sha256(script_path),
        formula=dict(stage='(stage_exit - stage_enter)/1e6',
                     eventX='(eventX_after - eventX_before)/1e6 for X in 0,1,2,7',
                     restore='(restore_KIND_after - restore_KIND_before)/1e6',
                     capture='(capture_KIND_after - capture_KIND_before)/1e6',
                     event7_wait='(event7_wait_after - event7_wait_before)/1e6',
                     confirmation='(confirmation_after - confirmation_before)/1e6',
                     gap='uncovered Host intervals in [stage_enter,stage_exit]; not named overhead',
                     closure='sum(intervals)+sum(gaps)=stage', event_gpu='operation R{i}/stage GPU_total_envelope_ms; separate'),
        source_map={
            'stage_enter/exit': 'deployment/m3_b2_backend.py:32-43 (BoundaryBackend.stage try/finally)',
            'event0/1/2/7 record': 'deployment/m2_clean_cuda.py:155-164 (CudaDevice.mark; event_before at 160, clock/record at 161, event_after at 162)',
            'restore images/noise': 'deployment/m2_clean_cuda.py:123-130 (CudaDevice.restore; two copies)',
            'capture images/noise': 'deployment/m2_clean_backend.py:65-77 (CleanBackend.stage capture wraps)',
            'event7 wait': 'deployment/m2_clean_cuda.py:185-195 (CudaDevice.wait_event observer start/end)',
            'completion confirmation': 'deployment/m3_b2_backend.py:22-30 (BoundaryBackend.finish confirmation)',
            'event GPU': 'operation R{i}/stage GPU_total_envelope_ms; Event0->Event7 elapsed_time; separate from Host'},
        units='milliseconds; all interval formulas use integer nanoseconds then divide by 1e6',
        rows=rows, coverage=dict(segments=len({r['segment_id'] for r in rows}), stages=len(rows),
                                  unique_pairs=len({(r['segment_id'], r['stage_index']) for r in rows}),
                                  expected='4 segments x 4 stages = 16'),
        checks=dict(no_missing=True, no_negative=True, no_overlap=True, closure_exact=True,
                    all_event_gpu_finite=True),
    )
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True)+'\n')
    with out_csv.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in fields})
    lines = ['# B7 stage interval decomposition', '',
             'Input: `%s`  ' % result_path,
             'Source: `%s`  ' % source_path,
             'Host interval formulas: stage = `(stage_exit-stage_enter)/1e6`; EventX = `(EventX_after-EventX_before)/1e6`; restore/capture/wait/confirmation = same before/after formula. All values are Host nanoseconds, not GPU clocks.', '',
             'Unclassified gaps are the intervals inside `[stage_enter,stage_exit]` not covered by the named Host intervals. They are not named overhead. Event GPU is a separate Event0→Event7 envelope and is not added to Host.', '',
             '| segment | stage | stage Host | Event0 | Event0 share | E1 | E2 | E7 | restore img/noise | capture img/noise | E7 wait | confirm | gap | Event GPU |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        lines.append('| %s | %d | %.6f | %.6f | %.2f%% | %.6f | %.6f | %.6f | %.6f / %.6f | %.6f / %.6f | %.6f | %.6f | %.6f | %.6f |' % (
            r['segment_id'], r['stage_index'], r['stage_host_ms'], r['event0_record_ms'], r['event0_share_percent'],
            r['event1_record_ms'], r['event2_record_ms'], r['event7_record_ms'],
            r['restore_images_ms'], r['restore_noise_ms'], r['capture_images_ms'], r['capture_noise_ms'],
            r['event7_wait_ms'], r['completion_confirmation_ms'], r['unclassified_gap_ms'], r['event_gpu_ms']))
    lines += ['', 'Closure: classified + unclassified gap = stage Host; closure_delta = 0 for every row. CSV/JSON contain the full gap list and source SHA.', '']
    out_md.write_text('\n'.join(lines))
    manifest = dict(schema='m3_b7_stage_interval_manifest_v1', input=str(result_path),
                    input_sha256=payload['input_sha256'], source_sha256=payload['source_sha256'],
                    script_sha256=payload['script_sha256'], output_dir=str(out_dir),
                    files={p.name: sha256(p) for p in (out_json, out_csv, out_md)},
                    command='python3 %s %s %s' % (script_path, result_path, out_dir))
    (out_dir/'B7_ANALYSIS_MANIFEST.json').write_text(json.dumps(manifest, indent=2, sort_keys=True)+'\n')
    return payload, manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('result', type=Path)
    ap.add_argument('out_dir', type=Path)
    ap.add_argument('--source', type=Path,
                    default=Path(__file__).resolve().parent.parent/'deployment'/'m2_clean_cuda.py')
    args = ap.parse_args(argv)
    try:
        payload, manifest = write_outputs(args.result, args.out_dir, args.source, Path(__file__).resolve())
    except AnalysisError as exc:
        print('ANALYSIS_FAILED: %s' % exc, file=sys.stderr)
        return 2
    print(json.dumps({'status': 'PASS', 'rows': len(payload['rows']),
                      'input_sha256': manifest['input_sha256'],
                      'source_sha256': manifest['source_sha256'],
                      'script_sha256': manifest['script_sha256'],
                      'outputs': manifest['files']}, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
