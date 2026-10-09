"""Read-only official-model compilation check; creates no MjData or physics step."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

from g1swarm.ros_observation import verify_joint_map_sources


STUDY = Path(__file__).resolve().parent
ROOT = STUDY.parents[1]
MAP = STUDY / "joint_map.json"
ASSET_RECEIPT = ROOT / "experiments/m2/cross_state_reliability_readiness_001/asset_restore.json"


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True, help="root of the already restored official asset tree")
    args = parser.parse_args(argv)
    assets = args.assets.resolve()
    relative = Path("third_party/unitree_rl_gym/resources/robots/g1_description")
    xml = assets / relative / "g1_12dof.xml"
    urdf = assets / relative / "g1_12dof.urdf"
    scene = assets / relative / "scene.xml"
    try:
        verify_joint_map_sources(MAP, xml, urdf, ASSET_RECEIPT)
        import mujoco
        mapping = json.loads(MAP.read_text(encoding="utf-8"))
        if digest(scene) != mapping["scene_xml_sha256"]:
            raise ValueError("scene XML hash differs from frozen joint map")
        model = mujoco.MjModel.from_xml_path(str(scene))
        if (model.nq, model.nv, model.nu) != (19, 18, 12):
            raise ValueError("compiled model dimensions differ from frozen 12-DOF variant")
        observed = []
        for row in mapping["joints"]:
            joint_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, row["name"])
            if joint_id < 0:
                raise ValueError(f"compiled model lacks {row['name']}")
            actual = (int(model.jnt_qposadr[joint_id]), int(model.jnt_dofadr[joint_id]))
            expected = (row["qpos_index"], row["qvel_index"])
            if actual != expected:
                raise ValueError(f"compiled joint address mismatch: {row['name']}")
            observed.append({"name": row["name"], "qpos_index": actual[0], "qvel_index": actual[1]})
        receipt = {
            "status": "COMPILED_MODEL_MAP_VERIFIED_NO_PHYSICS",
            "mujoco_version": mujoco.__version__,
            "joint_map_sha256": digest(MAP),
            "asset_receipt_sha256": digest(ASSET_RECEIPT),
            "scene_xml_sha256": digest(scene),
            "joint_xml_sha256": digest(xml),
            "urdf_sha256": digest(urdf),
            "nq": model.nq, "nv": model.nv, "nu": model.nu,
            "base_joint": mapping["base_free_joint"]["name"],
            "joints": observed,
            "mjdata_created": False, "physics_steps": 0, "policy_inferences": 0,
        }
        print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
        return 0
    except (OSError, ValueError, ImportError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
