# Read-only evidence reproduction

From a review checkout, using Python3.12 standard library only:

```sh
python3 reports/g1_ppo_residual_t1_smoke/restore_and_audit.py /tmp/g1-t1-review
```

The destination must not exist. The helper verifies archive SHA256,guards extraction paths,verifies every restored raw file,then runs `experiments/rl/g1_ppo_yaw_smoke_001/audit_partial.py`. It performs zero physics or Torch imports. Retained verdict must remain T1_BLOCKED_WITH_EXACT_EVIDENCE even if integrity audit PASS.

Nonphysical failure check in the exact installed RL environment:

```sh
PYTHONPATH=src python -m pytest tests/test_residual_rl_failure_receipt.py -q
```

This only invokes SB3 metadata ingestion,not learn,policy inference or physics. The runtime entry must not be re-executed using this spent authorization. A future authorized attempt requires a new source/freeze and campaign identity after the proposed one-key metadata repair. The failed execution can be inspected by checking out0f41e0cd;no rebase or frozen-code rewrite is required.
