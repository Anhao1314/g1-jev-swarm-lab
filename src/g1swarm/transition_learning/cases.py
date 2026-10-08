"""New Phase 3A cases, independent of the frozen Phase 2 language campaigns.

Skill parameters retain the original lifecycle and thresholds. Train/eval task
combinations differ in their parameters, rather than merely their random seeds.
"""

from __future__ import annotations


def _walk(distance: float) -> dict:
    return {"skill": "walk_forward", "parameters": {
        "target_distance_m": float(distance),
        "tolerance_m": max(0.2, 0.1 * distance),
        "speed_mps": 0.5,
        "max_duration_s": max(15.0, 6.0 * distance),
        "reset_memory": True,
    }}


def _turn(angle: float) -> dict:
    return {"skill": "turn", "parameters": {
        "target_angle_deg": float(angle), "yaw_rate_radps": 0.5,
        "tolerance_deg": 15.0, "max_duration_s": 10.0, "settle_s": 0.5,
    }}


def _stop() -> dict:
    return {"skill": "stop", "parameters": {
        "window_s": 1.0, "speed_threshold_mps": 0.10, "max_duration_s": 4.0,
    }}


def _stand(duration: float) -> dict:
    return {"skill": "stand", "parameters": {"duration_s": float(duration)}}


def _case(identifier: str, group: str, nodes: list[dict],
          transition: str | None = None, yaw: float = 0.0) -> dict:
    return {"id": identifier, "group": group, "transition": transition,
            "nodes": nodes, "initial_yaw_deg": float(yaw)}


TRAIN_CASES = (
    _case("train-wt-01", "transition", [_walk(1), _turn(30)], "walk_to_turn"),
    _case("train-wt-02", "transition", [_walk(2), _turn(-30)], "walk_to_turn"),
    _case("train-wt-03", "transition", [_walk(2), _turn(60)], "walk_to_turn"),
    _case("train-tw-01", "transition", [_turn(30), _walk(1)], "turn_to_walk"),
    _case("train-tw-02", "transition", [_turn(-30), _walk(2)], "turn_to_walk"),
    _case("train-tw-03", "transition", [_turn(-60), _walk(2)], "turn_to_walk"),
    _case("train-ws-01", "transition", [_walk(1), _stop()], "walk_to_stop"),
    _case("train-ws-02", "transition", [_walk(2), _stop()], "walk_to_stop"),
    _case("train-ws-03", "transition", [_walk(1), _stop()], "walk_to_stop", yaw=10),
    _case("train-sw-01", "transition", [_stand(1), _walk(1)], "stand_to_walk"),
    _case("train-sw-02", "transition", [_stand(2), _walk(2)], "stand_to_walk"),
    _case("train-sw-03", "transition", [_stand(3), _walk(1)], "stand_to_walk"),
)


EVAL_CASES = (
    _case("eval-wt-01", "transition", [_walk(1.5), _turn(45)], "walk_to_turn"),
    _case("eval-wt-02", "transition", [_walk(3), _turn(-45)], "walk_to_turn"),
    _case("eval-wt-03", "transition", [_walk(1.5), _turn(75)], "walk_to_turn"),
    _case("eval-wt-04", "transition", [_walk(3), _turn(-75)], "walk_to_turn"),
    _case("eval-tw-01", "transition", [_turn(45), _walk(1.5)], "turn_to_walk"),
    _case("eval-tw-02", "transition", [_turn(-45), _walk(3)], "turn_to_walk"),
    _case("eval-tw-03", "transition", [_turn(75), _walk(1.5)], "turn_to_walk"),
    _case("eval-tw-04", "transition", [_turn(-75), _walk(3)], "turn_to_walk"),
    _case("eval-ws-01", "transition", [_walk(1.5), _stop()], "walk_to_stop"),
    _case("eval-ws-02", "transition", [_walk(3), _stop()], "walk_to_stop"),
    _case("eval-ws-03", "transition", [_walk(1.5), _stop()], "walk_to_stop", yaw=10),
    _case("eval-ws-04", "transition", [_walk(3), _stop()], "walk_to_stop", yaw=-10),
    _case("eval-sw-01", "transition", [_stand(4), _walk(1.5)], "stand_to_walk"),
    _case("eval-sw-02", "transition", [_stand(5), _walk(3)], "stand_to_walk"),
    _case("eval-sw-03", "transition", [_stand(6), _walk(1.5)], "stand_to_walk", yaw=10),
    _case("eval-sw-04", "transition", [_stand(7), _walk(3)], "stand_to_walk", yaw=-10),
)


PRIMITIVE_CASES = (
    _case("primitive-stand-2", "primitive", [_stand(2)]),
    _case("primitive-walk-4", "primitive", [_walk(4)]),
    _case("primitive-walk-8", "primitive", [_walk(8)]),
    _case("primitive-turn-minus45", "primitive", [_turn(-45)]),
    _case("primitive-turn-plus45", "primitive", [_turn(45)]),
    _case("primitive-turn-minus90", "primitive", [_turn(-90)]),
    _case("primitive-turn-plus90", "primitive", [_turn(90)]),
    _case("primitive-stop-rest", "primitive", [_stop()]),
)


SEQUENCE_CASES = (
    _case("sequence-mixed-12m", "sequence", [
        _stand(2), _walk(4), _turn(45), _walk(4), _turn(-45), _walk(4), _stop(),
    ]),
    # The second sequence retains the additional 10-second stand exposure.
    _case("sequence-mixed-16m", "sequence", [
        _stand(10), _walk(8), _turn(-90), _walk(4), _turn(90), _walk(4), _stop(),
    ]),
)
