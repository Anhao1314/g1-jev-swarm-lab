"""Fixed fresh transition tuples; original training and regression objects stay intact.

Fresh cases are defined before any new physics replay. No outcomes select their
parameters. Existing primitive and sequence cases remain seen regression data.
"""
from __future__ import annotations

from ..transition_learning.cases import (
    TRAIN_CASES, EVAL_CASES, PRIMITIVE_CASES, SEQUENCE_CASES,
    _case, _walk, _turn, _stand, _stop,
)


HELDOUT_CASES = (
    _case("heldout-wt-01", "transition", [_walk(1.25), _turn(37.5)], "walk_to_turn"),
    _case("heldout-wt-02", "transition", [_walk(2.5), _turn(-37.5)], "walk_to_turn"),
    _case("heldout-wt-03", "transition", [_walk(1.25), _turn(67.5)], "walk_to_turn"),
    _case("heldout-wt-04", "transition", [_walk(2.5), _turn(-67.5)], "walk_to_turn"),
    _case("heldout-tw-01", "transition", [_turn(37.5), _walk(1.25)], "turn_to_walk"),
    _case("heldout-tw-02", "transition", [_turn(-37.5), _walk(2.5)], "turn_to_walk"),
    _case("heldout-tw-03", "transition", [_turn(67.5), _walk(1.25)], "turn_to_walk"),
    _case("heldout-tw-04", "transition", [_turn(-67.5), _walk(2.5)], "turn_to_walk"),
    _case("heldout-ws-01", "transition", [_walk(1.25), _stop()], "walk_to_stop"),
    _case("heldout-ws-02", "transition", [_walk(2.5), _stop()], "walk_to_stop"),
    _case("heldout-ws-03", "transition", [_walk(1.25), _stop()], "walk_to_stop", yaw=7.5),
    _case("heldout-ws-04", "transition", [_walk(2.5), _stop()], "walk_to_stop", yaw=-7.5),
    _case("heldout-sw-01", "transition", [_stand(1.5), _walk(1.25)], "stand_to_walk"),
    _case("heldout-sw-02", "transition", [_stand(2.5), _walk(2.5)], "stand_to_walk"),
    _case("heldout-sw-03", "transition", [_stand(4.5), _walk(1.25)], "stand_to_walk", yaw=7.5),
    _case("heldout-sw-04", "transition", [_stand(6.5), _walk(2.5)], "stand_to_walk", yaw=-7.5),
)

REGRESSION_CASES = (*EVAL_CASES, *PRIMITIVE_CASES, *SEQUENCE_CASES)

REPEAT_CASE_IDS = (
    "heldout-wt-01", "heldout-tw-01", "heldout-ws-01", "heldout-sw-01",
    "sequence-mixed-12m", "sequence-mixed-16m",
)
