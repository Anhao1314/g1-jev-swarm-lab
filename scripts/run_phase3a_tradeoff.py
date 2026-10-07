"""Execute only the committed prospective Phase3A.4b schedule."""
import argparse
import json
from pathlib import Path
import sys

# The frozen Console observer is a repository module, not an installed package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from g1swarm.tradeoff_isolation.experiment import ARTIFACT, run_campaign

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=ARTIFACT)
    args = parser.parse_args()
    print(json.dumps(run_campaign(args.output_dir), indent=2))
