"""Check functional CLI compatibility and immutable experiment source pointers."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class EntryPoints(unittest.TestCase):
    def run_cli(self, args, cwd=ROOT):
        result = subprocess.run([sys.executable, '-B', *args], cwd=cwd,
                                env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'),
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_old_and_new_test_lists_agree(self):
        old = self.run_cli(['tools/check_cpu.py', '--list'])
        new = self.run_cli(['-m', 'tests', '--list'])
        self.assertEqual(json.loads(old), json.loads(new))

    def test_compatibility_wrapper_independent_of_working_directory(self):
        output = self.run_cli([str(ROOT/'tools/check_cpu.py'), '--list'], ROOT.parent)
        self.assertEqual(len(json.loads(output)), 4)

    def test_profiling_navigation_points_to_real_files(self):
        entries = json.loads(self.run_cli(['-m', 'profiling', '--list']))
        self.assertFalse(entries.pop('GPU_required'))
        self.assertTrue(all((ROOT/path).is_file() for path in entries.values()))

    def test_frozen_trace_sources_keep_original_hashes(self):
        manifest = json.loads((ROOT/'docs/PUBLICATION_SOURCE_INDEX.json').read_text())
        for item in manifest['files']:
            data = (ROOT/item['path']).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), item['sha256'])

    def test_public_cli_help_does_not_import_gpu_or_need_data(self):
        for target in [['-m', 'profiling', '--help'], ['-m', 'tests', '--help']]:
            self.assertIn('usage:', self.run_cli(target))


if __name__ == '__main__':
    unittest.main()
