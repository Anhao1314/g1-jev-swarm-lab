# Read-only T1b evidence reproduction

```sh
python3 reports/g1_ppo_residual_t1b_optimization/restore_and_audit.py /tmp/g1-t1b-review
```

The destination must not exist. Standard library only: verify archive SHA256, member path boundaries and every file hash, then invoke the unchanged `experiments/rl/g1_ppo_yaw_smoke_001/audit.py`. No physics, Torch import, official policy inference or training. Checkpoint receipts bind all three snapshots and exact 128/256 tensor reloads; the archived read-only inspection script is available for review.

Targeted nonphysical regression:

```sh
PYTHONPATH=src python -m pytest tests/test_residual_rl_t1b.py tests/test_residual_rl_failure_receipt.py -q
```

Synthetic state sources only; no MuJoCo, official policy, learn or optimizer calls. No further training or physics is authorized. Inspect the executed HEAD `dfe8e13ba91483b8fe972b1fd323cad20d1bce6f`; the publication commit only adds report/evidence. Preserve the prior T1 technical BLOCKED result and `LEARNING_GAIN_NOT_PROVEN`.
