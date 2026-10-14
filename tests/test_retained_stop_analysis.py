"""Stdlib synthetic tests; no robot imports, model assets or physics."""
import copy
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.analyze_retained_stop import DT, read_samples, summarize_samples


def samples(speeds):
    return [{'time': (i+1)*DT, 'speed': v, 'xy': [i*0.001, 0.0]}
            for i, v in enumerate(speeds)]


def raw_rows(count=2):
    rows = []
    for i in range(1, count+1):
        p = {'time_s': i*DT, 'qpos': [i*0.001, 0.0, 0.8], 'qvel': [0.08, 0.06, 0.5]}
        s = {'simulation_time': p['time_s'], 'base_position': p['qpos'],
             'linear_velocity': p['qvel'], 'active_skill': 'stop', 'fallen': False}
        rows += [{'native_attempt': i}, {'native_completed': i, 'post': p},
                 {'native_observation': i, 'state': copy.deepcopy(s)},
                 {'native_completed': i, 'state': copy.deepcopy(s)}]
    return rows


def encode(rows):
    return '\n'.join(json.dumps(row) for row in rows).encode()


class RetainedStopTests(unittest.TestCase):
    def test_mean_success_does_not_mean_all_samples_slow(self):
        result = summarize_samples(samples([0.0, 0.19]*250))
        self.assertAlmostEqual(result['final_window_mean_mps'], 0.095)
        self.assertEqual(result['final_window_above_threshold_samples'], 250)
        self.assertEqual(result['first_passing_sample_1based'], 500)
        self.assertEqual(result['final_window_longest_at_or_below_samples'], 1)
        self.assertEqual(result['final_window_longest_at_or_below_sample_span_s'], 0)
        self.assertEqual(result['post_first_pass_observed_samples'], 0)
        self.assertEqual(result['final_instantaneous_speed_mps'], 0.19)

    def test_later_observations_are_not_assumed_zero(self):
        result = summarize_samples(samples([0.05]*510))
        self.assertEqual(result['passing_windows_observed'], 11)
        self.assertEqual(result['post_first_pass_observed_samples'], 10)
        self.assertAlmostEqual(result['post_first_pass_observed_span_s'], 0.02)
        self.assertAlmostEqual(result['final_window_longest_at_or_below_sample_span_s'], 0.998)
        self.assertAlmostEqual(result['final_window_between_samples_path_m'], 0.499)

    def test_no_passing_window_remains_unknown(self):
        result = summarize_samples(samples([0.2]*501))
        self.assertIsNone(result['first_passing_sample_1based'])
        self.assertIsNone(result['post_first_pass_observed_samples'])
        self.assertEqual(result['passing_windows_observed'], 0)

    def test_original_float_sum_order_is_preserved(self):
        data = [0.03, 0.11, 0.17, 0.09]*130
        result = summarize_samples(samples(data))
        self.assertEqual(result['final_window_mean_mps'], sum(data[-500:])/500)
        self.assertEqual(result['previous_window_mean_mps'], sum(data[-501:-1])/500)

    def test_incomplete_and_gapped_samples_reject(self):
        with self.assertRaisesRegex(ValueError, 'INCOMPLETE_STOP_WINDOW'):
            summarize_samples(samples([0]*499))
        data = samples([0]*501)
        data[200]['time'] += DT
        with self.assertRaisesRegex(ValueError, 'SAMPLE_GAP'):
            summarize_samples(data)

    def test_nonfinite_and_negative_samples_reject(self):
        for bad in (math.nan, math.inf, -0.1, True):
            with self.subTest(bad=bad):
                data = samples([0]*500)
                data[1]['speed'] = bad
                with self.assertRaisesRegex(ValueError, 'NONFINITE_OR_NEGATIVE_SAMPLE'):
                    summarize_samples(data)

    def test_native_observation_is_not_double_counted_and_speed_is_planar(self):
        actual, policies = read_samples(encode(raw_rows()))
        self.assertEqual(len(actual), 2)
        self.assertEqual(policies, 0)
        self.assertEqual(actual[0]['speed'], 0.1)

    def test_missing_and_duplicate_native_samples_reject(self):
        rows = raw_rows()
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_NATIVE_POST'):
            read_samples(encode(rows + [rows[1]]))
        with self.assertRaisesRegex(ValueError, 'NATIVE_SEQUENCE_MISMATCH'):
            read_samples(encode(rows[1:]))

    def test_state_disagreement_rejects(self):
        rows = raw_rows()
        rows[3]['state']['linear_velocity'][0] += 0.01
        with self.assertRaisesRegex(ValueError, 'RAW_STATE_MISMATCH'):
            read_samples(encode(rows))

    def test_policy_gap_and_state_time_drift_reject(self):
        with self.assertRaisesRegex(ValueError, 'POLICY_SEQUENCE_MISMATCH'):
            read_samples(encode(raw_rows()+[{'policy_attempt': 1}]))
        rows = raw_rows()
        rows[1]['post']['time_s'] = rows[3]['state']['simulation_time'] = 0.5
        with self.assertRaisesRegex(ValueError, 'NATIVE_TIME_MISMATCH'):
            read_samples(encode(rows))

    def test_cli_refuses_wrong_index_before_reading_arbitrary_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'index.json'
            path.write_text('{"files":{"does-not-exist":{}}}', encoding='utf-8')
            run = subprocess.run([sys.executable, '-B', 'scripts/analyze_retained_stop.py',
                                  '--index', str(path)], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 2)
            self.assertEqual(json.loads(run.stdout)['reason'], 'INDEX_PIN_MISMATCH')

    def test_fresh_process_import_guard(self):
        code = '''import sys
class Guard:
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'numpy','torch','mujoco','g1swarm'}:
            raise AssertionError('Forbidden import: '+fullname)
sys.meta_path.insert(0, Guard())
from scripts.analyze_retained_stop import summarize_samples
assert summarize_samples([{'time':(i+1)*.002,'speed':.05,'xy':[0,0]} for i in range(500)])['stop_samples']==500
'''
        run = subprocess.run([sys.executable, '-B', '-c', code], capture_output=True, text=True, timeout=10)
        self.assertEqual(run.returncode, 0, run.stderr)


if __name__ == '__main__':
    unittest.main()
