"""Source-hashed descriptive curves from saved M2.5A journals; no physics."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def analyze(campaign, output):
    here = Path(__file__).resolve().parent
    manifest = json.loads((here / 'raw_manifest.json').read_text())
    audit = json.loads((here / 'audit.json').read_text())
    assert audit['status'] == 'AUDIT_PASS_RECORDED_RESULTS'
    assert audit['raw_artifact_sha256'] == {
        p: row['sha256'] for p, row in manifest['files'].items()
    }
    for name, row in manifest['files'].items():
        path = campaign / name
        assert path.stat().st_size == row['bytes'] and sha(path) == row['sha256'], name
    output.mkdir(parents=True, exist_ok=False)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    matplotlib.rcParams['svg.hashsalt'] = 'm25a-saved-hold-v1'
    series, cells = [], []
    for cell in audit['cells']:
        folder = campaign / cell['cell_id']
        entry = json.loads((folder / 'hold_entry.json').read_text())['pre_first_step']
        native = [json.loads(line) for line in (folder / 'native_incremental.jsonl').read_text().splitlines()]
        hold = [r for r in native if r['phase'] == 'hold']
        parent = [r for r in native if r['phase'] == 'parent']
        assert len(hold) == 1000
        seed = [math.hypot(*r['qvel'][:2]) for r in parent[-500:]]
        speed = [math.hypot(*r['qvel'][:2]) for r in hold]
        full = seed + speed
        rolling = [sum(full[i+1:i+501]) / 500 for i in range(1000)]
        path, prior, rows = 0.0, entry['qpos'][:2], []
        for i, r in enumerate(hold):
            xy = r['qpos'][:2]
            path += math.dist(prior, xy)
            prior = xy
            rows.append(((i+1)*0.002, speed[i], rolling[i], path))
        expected = cell['recomputed']
        assert abs(path-expected['xy_path_length_m']) < 1e-12
        assert abs(speed[-1]-expected['last_speed_mps']) < 1e-12
        assert all(abs(a-b) < 1e-12 for a,b in zip(rolling,expected['rolling_means']))
        series.append((cell['cell_id'], rows))
        cells.append({
            'cell_id': cell['cell_id'], 'scientific_status': cell['scientific_status'],
            'native_steps': cell['native_steps'], 'hold_steps': len(hold),
            'first_crossing': cell['first_crossing'],
            'max_rolling_mean_mps': max(rolling), 'rolling_margin_mps': 0.1-max(rolling),
            'final_speed_mps': speed[-1], 'max_instantaneous_speed_mps': max(speed),
            'xy_path_length_m': path, 'xy_net_displacement_m': math.dist(entry['qpos'][:2], prior),
            'disjoint_one_second_means_mps': expected['one_second_disjoint_means_mps'],
            'checks': expected['checks'],
        })
    with (output / 'hold_timeseries.csv').open('x', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream, lineterminator='\n')
        writer.writerow(['cell_id','hold_elapsed_s','instantaneous_speed_mps','rolling_mean_mps','xy_path_length_m'])
        for name, rows in series:
            for row in rows: writer.writerow([name, *row])
    fig, axes = plt.subplots(3,1,figsize=(9,9),sharex=True)
    labels = ['Seen failure/Halt','Turn45 failure/Halt','Normal Stop control']
    for (name, rows), label in zip(series, labels):
        for ax, col in zip(axes, [2,1,3]):
            ax.plot([r[0] for r in rows],[r[col] for r in rows],label=label,linewidth=1.3)
    axes[0].axhline(.1,color='black',linestyle='--',label='Frozen rolling-mean limit')
    axes[0].set_ylabel('1s rolling speed (m/s)')
    axes[0].set_ylim(0.045,0.105)
    axes[1].axhline(.1,color='black',linestyle=':',label='0.1 m/s: endpoint-only gate')
    axes[1].set_ylabel('Instantaneous speed (m/s)')
    axes[1].set_ylim(0,0.17)
    axes[2].axhline(.2,color='black',linestyle='--',label='Frozen path limit')
    axes[2].set_ylabel('Accumulated XY path (m)')
    axes[2].set_ylim(0,0.22)
    axes[2].set_xlabel('Time since first eligible Stop/Halt terminal state (s)')
    for ax in axes:
        ax.grid(alpha=.25)
        ax.legend(fontsize=8,loc='upper right')
        ax.set_xlim(0,2)
    fig.suptitle('M2.5A: continuous zero-command Hold, frozen 2s window\nSaved-data replay; transient speed peaks are not a rolling-mean failure')
    fig.tight_layout()
    fig.savefig(output/'hold_contract.png',dpi=150,metadata={'Software':'M2.5A saved-data analysis'})
    fig.savefig(output/'hold_contract.svg',metadata={'Date':None})
    plt.close(fig)
    summary = {
        'candidate_scientific_verdict':'PASS_BOUNDED_POST_HALT_HOLD_IN_TWO_SEEN_SEED0_STATES_WITH_NORMAL_STOP_CONTROL',
        'status':'DERIVED_FROM_FROZEN_AUDIT_AND_HASH_VERIFIED_RAW',
        'cells': cells, 'native_steps':audit['native_steps'],
        'source_raw_manifest_sha256':sha(here/'raw_manifest.json'),
        'frozen_audit_sha256':sha(here/'audit.json'),
        'analysis_script_sha256':sha(Path(__file__)), 'physics_policy_calls':0,
        'limitation':'Two seen seed-0 failure states, one unmatched Stop control, fixed 2s only; not immobility, reliability generalization or hardware safety.',
    }
    assert all(c['scientific_status']=='HOLD_SUCCEEDED_BOUNDED_IN_THIS_STATE' for c in cells)
    (output/'summary.json').write_bytes((json.dumps(summary,indent=2,sort_keys=True)+'\n').encode())
    hashes = {p.name:sha(p) for p in sorted(output.iterdir()) if p.is_file()}
    (output/'output_manifest.json').write_bytes((json.dumps({'sha256':hashes},indent=2,sort_keys=True)+'\n').encode())
    print(json.dumps({'status':summary['status'],'cells':len(cells),'native_steps':audit['native_steps']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    analyze(args.campaign.resolve(),args.output.resolve())
