"""Run the prospectively frozen independent frame/residual experiment."""
import argparse
import json
from g1swarm.frame_learning.campaign import run_campaign, ARTIFACT

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=ARTIFACT)
    args = parser.parse_args()
    print(json.dumps(run_campaign(args.output_dir), indent=2))
