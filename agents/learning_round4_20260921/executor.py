"""State-based common executor for the Round4 rule and learned policies."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

try:
    from .contracts import (
        TypedPlan,
        actor_identity_matches,
        actor_inventory,
        actor_positions,
        attribute_primitive,
        canonical_step,
        make_feed_plan,
        make_harvest_plan,
        observation_digest,
        service_reservations,
        tile_at,
    )
except ImportError:
    from contracts import (  # type: ignore
        TypedPlan,
        actor_identity_matches,
        actor_inventory,
        actor_positions,
        attribute_primitive,
        canonical_step,
        make_feed_plan,
        make_harvest_plan,
        observation_digest,
        service_reservations,
        tile_at,
    )


MOVES = frozenset({"NORTH", "SOUTH", "EAST", "WEST"})
TRACKED = frozenset({"PICKUP", "HARVEST", "FEED", "WATER", "CARE", "DROP", "PLACE", *MOVES})
SHED_TILES = ((4, 4), (5, 4), (4, 5), (5, 5))


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _distance(left: tuple[int, int], right: tuple[int, int]) -> int:
    return abs(left[0] - right[0]) + abs(left[1] - right[1])


def _move_toward(left: tuple[int, int], right: tuple[int, int]) -> list[str]:
    if left[0] < right[0]:
        return ["EAST"]
    if left[0] > right[0]:
        return ["WEST"]
    if left[1] < right[1]:
        return ["SOUTH"]
    if left[1] > right[1]:
        return ["NORTH"]
    return ["PASS"]


def _shape(action: Mapping[str, Any], hands: int) -> dict[str, Any]:
    values = {
        "farmer": list(action.get("farmer") or ["PASS"]),
        "hands": [list(value or ["PASS"]) for value in action.get("hands") or []],
        "market": [list(value) for value in action.get("market") or [] if isinstance(value, Sequence)][:10],
    }
    values["hands"] = (values["hands"] + [["PASS"]] * hands)[:hands]
    return values


def _units(action: Mapping[str, Any]) -> list[list[Any]]:
    return [list(action.get("farmer") or ["PASS"]), *[list(value or ["PASS"]) for value in action.get("hands") or []]]


def _set_unit(action: dict[str, Any], actor: int, value: Sequence[Any]) -> None:
    if actor == 0:
        action["farmer"] = list(value)
    else:
        action["hands"][actor - 1] = list(value)


def _animals(observation: Mapping[str, Any], *, unfed_only: bool = True) -> list[tuple[int, int]]:
    farm = observation["farms"][_integer(observation.get("player"))]
    result = []
    for y, row in enumerate(farm.get("tiles") or []):
        for x, tile in enumerate(row):
            if not isinstance(tile, Mapping) or not tile.get("animal"):
                continue
            if unfed_only and bool(tile.get("fed_today")):
                continue
            result.append((x, y))
    return result


class ExecutionCoordinator:
    """Repairs a proposed joint action and verifies its next-observation effects.

    The coordinator never resumes a hidden source-policy pointer.  A continuation
    is recomputed from the current observation on every call.
    """

    def __init__(self, label: str) -> None:
        self.label = label
        self.reset()

    def reset(self) -> None:
        self.jobs: dict[tuple[int, int], TypedPlan] = {}
        self.pending: dict[int, list[dict[str, Any]]] = {}
        self.last_step: dict[int, int] = {}
        self.trace: list[dict[str, Any]] = []
        self.stats: dict[str, int] = {
            "triggered": 0,
            "candidate_generated": 0,
            "applicable": 0,
            "scheduled": 0,
            "started": 0,
            "primitive_issued": 0,
            "primitive_effect_observed": 0,
            "primitive_failed": 0,
            "primitive_unknown": 0,
            "job_completed": 0,
            "jobs_replanned": 0,
            "jobs_expired": 0,
            "action_changes": 0,
            "duplicate_services_blocked": 0,
            "immature_harvests_blocked": 0,
            "pickup_quantities_increased": 0,
            "economic_evaluated": 0,
        }

    def _event(self, observation: Mapping[str, Any], event: str, **fields: Any) -> None:
        if len(self.trace) >= 5000:
            return
        self.trace.append(
            {"step": canonical_step(observation), "seat": _integer(observation.get("player")), "event": event, **fields}
        )

    def _verify_pending(self, observation: Mapping[str, Any]) -> None:
        seat = _integer(observation.get("player"))
        rows = self.pending.pop(seat, [])
        for row in rows:
            status, reason = attribute_primitive(
                row["before"], observation, row["actor"], row["action"], row.get("target")
            )
            if status == "ESTABLISHED":
                self.stats["primitive_effect_observed"] += 1
                self.stats["job_completed"] += int(row.get("terminal", True))
            elif status == "FAILED":
                self.stats["primitive_failed"] += 1
            elif status == "UNKNOWN":
                self.stats["primitive_unknown"] += 1
            self._event(
                observation,
                "primitive_result",
                actor=row["actor"],
                action=row["action"],
                status=status,
                reason=reason,
                plan_id=row.get("plan_id"),
            )

    def _expire(self, observation: Mapping[str, Any]) -> None:
        seat = _integer(observation.get("player"))
        step = canonical_step(observation)
        if step == 0 or step < self.last_step.get(seat, -1):
            for key in [key for key in self.jobs if key[0] == seat]:
                self.jobs.pop(key, None)
        self.last_step[seat] = step
        for key, plan in list(self.jobs.items()):
            if key[0] != seat:
                continue
            identity = {"seat": plan.seat, "actor_index": plan.actor_index, "day_epoch": plan.day_epoch}
            if step > plan.deadline_step or not actor_identity_matches(observation, identity):
                self.jobs.pop(key, None)
                self.stats["jobs_expired"] += 1
                self._event(observation, "job_expired", actor=plan.actor_index, plan_id=plan.plan_id)

    def _remaining_wheat(self, observation: Mapping[str, Any], actor: int) -> int:
        """Observable per-actor continuation budget, independent of a source pointer."""
        positions = actor_positions(observation)
        unfed = len(_animals(observation))
        remaining_turns = max(0, 23 - _integer(observation.get("hour")))
        if not positions or unfed <= 0 or remaining_turns <= 0:
            return 0
        # One service plus an average movement step costs about two turns.  The
        # fair share prevents PICKUP(1) from silently deleting a second duty.
        active = max(1, len(positions))
        fair_share = math.ceil(unfed / active)
        time_capacity = max(1, remaining_turns // 2)
        return min(unfed, max(1, fair_share), time_capacity)

    def _nearest_unfed(
        self,
        observation: Mapping[str, Any],
        actor: int,
        excluded: set[tuple[int, int]],
    ) -> tuple[int, int] | None:
        positions = actor_positions(observation)
        if not 0 <= actor < len(positions):
            return None
        candidates = [value for value in _animals(observation) if value not in excluded]
        return min(candidates, key=lambda value: (_distance(positions[actor], value), value)) if candidates else None

    def _run_job(
        self,
        observation: Mapping[str, Any],
        actor: int,
        excluded: set[tuple[int, int]],
    ) -> list[Any] | None:
        seat = _integer(observation.get("player"))
        plan = self.jobs.get((seat, actor))
        if plan is None:
            return None
        positions = actor_positions(observation)
        if actor >= len(positions):
            return ["PASS"]
        position = positions[actor]
        target_tile = tile_at(observation, plan.target)
        if not isinstance(target_tile, Mapping) or not target_tile.get("animal") or bool(target_tile.get("fed_today")):
            target = self._nearest_unfed(observation, actor, excluded)
            if target is None:
                self.jobs.pop((seat, actor), None)
                return ["PASS"]
            required = self._remaining_wheat(observation, actor)
            plan = make_feed_plan(
                observation,
                actor,
                target,
                required,
                policy_state_digest=observation_digest(observation, actor),
            )
            self.jobs[(seat, actor)] = plan
            self.stats["jobs_replanned"] += 1
            self._event(observation, "job_replanned", actor=actor, target=list(target), plan_id=plan.plan_id)
        excluded.add(plan.target)
        inventory = actor_inventory(observation, actor)
        wheat = _integer(inventory.get("WHEAT"))
        required = max(1, _integer(plan.required_resources.get("WHEAT"), 1))
        if wheat <= 0:
            shed = min(SHED_TILES, key=lambda value: (_distance(position, value), value))
            if position != shed:
                return _move_toward(position, shed)
            available = _integer((observation.get("private") or {}).get("shed", {}).get("WHEAT"))
            return ["PICKUP", "WHEAT", min(available, required)] if available > 0 else ["PASS"]
        if position != plan.target:
            return _move_toward(position, plan.target)
        return ["FEED"]

    def _schedule_feed_replan(
        self,
        observation: Mapping[str, Any],
        actor: int,
        excluded: set[tuple[int, int]],
        reason: str,
    ) -> list[Any]:
        target = self._nearest_unfed(observation, actor, excluded)
        if target is None:
            return ["PASS"]
        required = self._remaining_wheat(observation, actor)
        plan = make_feed_plan(
            observation,
            actor,
            target,
            max(1, required),
            policy_state_digest=observation_digest(observation, actor),
        )
        seat = _integer(observation.get("player"))
        self.jobs[(seat, actor)] = plan
        self.stats["candidate_generated"] += 1
        self.stats["applicable"] += 1
        self.stats["scheduled"] += 1
        self.stats["started"] += 1
        self.stats["jobs_replanned"] += 1
        self._event(
            observation,
            "state_based_replan",
            actor=actor,
            target=list(target),
            reason=reason,
            plan=plan.contract(),
        )
        return self._run_job(observation, actor, excluded) or ["PASS"]

    def repair(
        self,
        observation: Mapping[str, Any],
        proposal: Mapping[str, Any],
        skill_scores: Mapping[str, float] | None = None,
    ) -> dict[str, Any]:
        self._verify_pending(observation)
        self._expire(observation)
        seat = _integer(observation.get("player"))
        positions = actor_positions(observation)
        result = _shape(proposal, max(0, len(positions) - 1))
        original = deepcopy(result)
        scores = skill_scores or {}
        excluded: set[tuple[int, int]] = {
            plan.target for (job_seat, _actor), plan in self.jobs.items() if job_seat == seat
        }

        # Active continuations own their actor slot.  Every action is derived
        # from the current observation, not a stale route cursor.
        for actor in range(len(positions)):
            job_action = self._run_job(observation, actor, excluded)
            if job_action is not None:
                _set_unit(result, actor, job_action)

        # Preserve observable remaining duties when the source proposes a too-
        # small wheat pickup at the shed.
        for actor, unit in enumerate(_units(result)):
            if unit[:2] != ["PICKUP", "WHEAT"]:
                continue
            required = self._remaining_wheat(observation, actor)
            requested = _integer(unit[2], 1) if len(unit) >= 3 else 1
            available = _integer((observation.get("private") or {}).get("shed", {}).get("WHEAT"))
            quantity = min(available, max(requested, required))
            if quantity > requested:
                _set_unit(result, actor, ["PICKUP", "WHEAT", quantity])
                self.stats["pickup_quantities_increased"] += 1
                self._event(
                    observation,
                    "pickup_obligation_preserved",
                    actor=actor,
                    requested=requested,
                    required=required,
                    emitted=quantity,
                )

        # HARVEST candidates are created from the same typed plan that supplies
        # the executable primitive.  yield_units alone can never trigger it.
        for actor, unit in enumerate(_units(result)):
            if not unit or unit[0] != "HARVEST":
                continue
            self.stats["triggered"] += 1
            self.stats["candidate_generated"] += 1
            plan, precondition = make_harvest_plan(observation, actor)
            if plan is None:
                _set_unit(result, actor, ["PASS"])
                self.stats["immature_harvests_blocked"] += 1
                self._event(
                    observation,
                    "harvest_blocked",
                    actor=actor,
                    reason=precondition.reason,
                    audit_addendum=["HARVEST_PRECONDITION_FAILED", "ECONOMIC_HYPOTHESIS_UNTESTED"],
                )
            else:
                self.stats["applicable"] += 1
                self.stats["scheduled"] += 1
                self.stats["started"] += 1
                self._event(observation, "harvest_plan", actor=actor, plan=plan.contract())

        # A learned selector may activate an applicable skill on an otherwise
        # idle actor.  The deterministic executor still owns legality.
        for actor, unit in enumerate(_units(result)):
            if unit != ["PASS"]:
                continue
            if float(scores.get("HARVEST_AND_LAND_CONVERSION", 0.0)) >= 0.45:
                plan, precondition = make_harvest_plan(observation, actor)
                if plan is not None:
                    _set_unit(result, actor, plan.primitives[0])
                    self.stats["triggered"] += 1
                    self.stats["candidate_generated"] += 1
                    self.stats["applicable"] += 1
                    self.stats["scheduled"] += 1
                    self.stats["started"] += 1
                    continue
            if float(scores.get("ANIMAL_SERVICE_WITH_CONTINUATION", 0.0)) >= 0.45:
                position = positions[actor]
                tile = tile_at(observation, position)
                if (
                    isinstance(tile, Mapping)
                    and tile.get("animal")
                    and not bool(tile.get("fed_today"))
                    and _integer(actor_inventory(observation, actor).get("WHEAT")) > 0
                    and position not in excluded
                ):
                    _set_unit(result, actor, ["FEED"])

        # Engine-order reservations make only the first effective service own a
        # target.  Later duplicates are immediately replanned to another target.
        _reserved, rejected = service_reservations(observation, result)
        accepted_targets: set[tuple[int, int]] = set()
        for actor, unit in enumerate(_units(result)):
            if unit and unit[0] in {"FEED", "WATER", "CARE"} and actor not in rejected:
                accepted_targets.add(positions[actor])
        for actor, reason in sorted(rejected.items()):
            unit = _units(result)[actor]
            if not unit or unit[0] != "FEED":
                if reason.startswith("DUPLICATE_SERVICE"):
                    _set_unit(result, actor, ["PASS"])
                continue
            self.stats["triggered"] += 1
            if reason.startswith("DUPLICATE_SERVICE"):
                self.stats["duplicate_services_blocked"] += 1
            replacement = self._schedule_feed_replan(observation, actor, accepted_targets | excluded, reason)
            _set_unit(result, actor, replacement)
            plan = self.jobs.get((seat, actor))
            if plan is not None:
                accepted_targets.add(plan.target)

        final_units = _units(result)
        original_units = _units(original)
        changes = sum(left != right for left, right in zip(original_units, final_units, strict=True))
        changes += int(original.get("market") != result.get("market"))
        self.stats["action_changes"] += changes

        pending = []
        before_snapshot = deepcopy(dict(observation))
        for actor, unit in enumerate(final_units):
            op = str(unit[0]) if unit else "PASS"
            if op not in TRACKED:
                continue
            target = positions[actor] if actor < len(positions) else None
            plan = self.jobs.get((seat, actor))
            pending.append(
                {
                    # One immutable snapshot is shared by every actor probe for
                    # this turn; copying it per actor is quadratic in workers.
                    "before": before_snapshot,
                    "actor": actor,
                    "action": list(unit),
                    "target": target,
                    "plan_id": plan.plan_id if plan else None,
                    "terminal": op in {"HARVEST", "FEED", "WATER", "CARE", "DROP", "PLACE"},
                }
            )
            self.stats["primitive_issued"] += 1
        self.pending[seat] = pending
        return result

    def diagnostics(self) -> dict[str, Any]:
        return {"executor": "round4-state-based-v1", "policy": self.label, **self.stats}

    def policy_trace(self) -> list[dict[str, Any]]:
        return deepcopy(self.trace)


__all__ = ["ExecutionCoordinator"]
