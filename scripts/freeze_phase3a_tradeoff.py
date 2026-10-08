"""Freeze an independent mechanism experiment without running physics."""
import json
from g1swarm.tradeoff_isolation.experiment import freeze_experiment

if __name__ == "__main__":
    print(json.dumps(freeze_experiment(), indent=2))
