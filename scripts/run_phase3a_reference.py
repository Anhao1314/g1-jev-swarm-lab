"""Run only the frozen residual-off walking reference ablation."""
import argparse
import json
from g1swarm.reference_ablation.experiment import DIRECTORY, run_campaign

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default=DIRECTORY+"/protocol.json")
    parser.add_argument("--output-dir", default="artifacts/reference_frame_ablation_001")
    args = parser.parse_args()
    print(json.dumps(run_campaign(args.output_dir, args.protocol), indent=2))
