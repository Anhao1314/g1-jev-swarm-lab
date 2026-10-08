"""Read saved parent halt traces only; no simulator/controller imports or execution."""
import argparse
import hashlib
import json
from pathlib import Path


def analyze(root):
    results = []
    for family in ('seen_reference_walk6', 'transition_turn45_walk6'):
        for arm in ('authorized_new_mission', 'authorization_refusals'):
            path = root / (family + '--' + arm) / 'parent_result.json'
            raw = path.read_bytes()
            halt = json.loads(raw)['physical_halt']
            trace = halt['trace']
            # HaltMonitor includes the pre-step state; StopSkill's deque does not.
            rows = trace[1:]
            dt = rows[0]['time_s'] - trace[0]['time_s']
            n = round(halt['skill_metrics']['window_s'] / dt)
            speeds = [r['speed_mps'] for r in rows]
            means = [sum(speeds[i-n:i]) / n for i in range(n, len(rows)+1)]
            threshold = halt['skill_metrics']['speed_threshold_mps']
            first = next(i+n for i, v in enumerate(means) if v <= threshold)
            terminal = rows[-n:]
            previous = rows[-n-1:-1]
            assert first == len(rows)
            assert abs(means[-1] - halt['skill_metrics']['final_window_mean_speed_mps']) < 1e-14
            results.append(dict(case=family, arm=arm, source=str(path), sha256=hashlib.sha256(raw).hexdigest(),
                start_s=trace[0]['time_s'], end_s=trace[-1]['time_s'], duration_s=halt['simulated_halt_duration_s'],
                step_s=dt, samples=len(rows), window_samples=n, min_possible_duration_s=n*dt,
                terminal_window_start_s=terminal[0]['time_s'], terminal_window_end_s=terminal[-1]['time_s'],
                penultimate_window_start_s=previous[0]['time_s'], penultimate_window_end_s=previous[-1]['time_s'],
                terminal_mean_mps=means[-1], penultimate_mean_mps=means[-2], threshold_mps=threshold,
                terminal_entering_speed_mps=speeds[-1], terminal_removed_speed_mps=speeds[-n-1],
                mean_change_from_one_sample_replacement_mps=(speeds[-1]-speeds[-n-1])/n,
                margin_mps=threshold-means[-1], margin_percent_of_threshold=100*(threshold-means[-1])/threshold,
                first_qualifying_step=first, earlier_eligible_windows=len(means)-1,
                final_instantaneous_mps=speeds[-1], terminal_window_min_mps=min(r['speed_mps'] for r in terminal),
                terminal_window_max_mps=max(r['speed_mps'] for r in terminal),
                terminal_window_samples_above_threshold=sum(r['speed_mps'] > threshold for r in terminal),
                post_qualification_hold_steps=0))
    return {'scope':'Parent failure-halt traces only. New-mission trajectory excluded.', 'results':results,
            'limitations':'First qualifying sliding mean is a stopping endpoint, not independent sustained-hold evidence. No extrapolation, new acquisition, threshold change or reset intervention.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--rawroot', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path(__file__).with_suffix('.json'))
    args = parser.parse_args()
    output = analyze(args.rawroot)
    destination = args.output
    destination.write_text(json.dumps(output, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(output, indent=2))
