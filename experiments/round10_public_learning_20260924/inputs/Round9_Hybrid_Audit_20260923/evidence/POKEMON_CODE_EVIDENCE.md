# ポケモン提出物：コード根拠

添付tar.gzのソースを静的に読んだ。新規対戦や学習は行っていない。コメント中の成績はコード作者の報告であり、本監査で再検証した成績ではない。

## main.py: 20–45

```python
  20: 
  21: import fallback_policy
  22: from fallback_policy import agent as _fallback_agent
  23: from ml_runtime import Ranker
  24: 
  25: _RANKER: Ranker | None = None
  26: _LOAD_ERROR: str | None = None
  27: if os.environ.get("GRIMMSNARL_ML_DISABLE") != "1":
  28:     try:
  29:         _RANKER = Ranker()
  30:     except Exception as error:  # missing/corrupt model must not crash the game
  31:         _LOAD_ERROR = f"{type(error).__name__}: {error}"
  32: 
  33: # The planner is an override layer, not a dependency: if it cannot be imported
  34: # the agent must still play the ranker's answer rather than fail to load.
  35: try:
  36:     from ml_planner import Planner
  37: 
  38:     _PLANNER = Planner()
  39:     _PLANNER_ERROR: str | None = None
  40: except Exception as error:  # noqa: BLE001
  41:     _PLANNER = None
  42:     _PLANNER_ERROR = f"{type(error).__name__}: {error}"
  43: _PLANNER_DISABLED = (
  44:     _PLANNER is None or os.environ.get("GRIMMSNARL_PLANNER_DISABLE") == "1"
  45: )
```

## main.py: 89–154

```python
  89: def _choose(observation):
  90:     if not isinstance(observation, dict) or observation.get("select") is None:
  91:         return _fallback_agent(observation)
  92: 
  93:     # A committed line runs to the end of the turn before the ranker is
  94:     # consulted again.  Playing only a line's opening and then handing the turn
  95:     # back was measured to collect 19 of its 36 prizes and to cost 73 damage a
  96:     # turn against not overriding at all, so an opening is never played alone.
  97:     if _SEARCH is not None and not (
  98:         _RANKER is not None and _RANKER.teacher_forced
  99:     ):
 100:         planned = _SEARCH.planned(observation)
 101:         if planned is not None:
 102:             # Advance the histories exactly the way v22 does for an action it
 103:             # did not score itself: once, and only for a single-pick.
 104:             if len(planned) == 1:
 105:                 observe_external(observation, planned[0])
 106:             return planned
 107: 
 108:     rule_choice = _fallback_agent(observation)
 109:     if _RANKER is None:
 110:         return rule_choice
 111: 
 112:     select = observation.get("select") or {}
 113:     if not _RANKER.is_scorable(select):
 114:         chosen = (
 115:             rule_choice[0]
 116:             if isinstance(rule_choice, list) and len(rule_choice) == 1
 117:             else None
 118:         )
 119:         if chosen is not None and not _RANKER.teacher_forced:
 120:             _RANKER.observe_external(observation, chosen)
 121:             if _PLANNER is not None:
 122:                 _PLANNER.note(observation, select, chosen)
 123:         return rule_choice
 124: 
 125:     index = _RANKER.choose(observation)
 126:     if index is None:
 127:         # Feature or scoring failure: keep the rule answer, and keep the
 128:         # intra-turn history aligned with what was actually played.
 129:         chosen = (
 130:             rule_choice[0]
 131:             if isinstance(rule_choice, list) and rule_choice
 132:             else 0
 133:         )
 134:         if not _RANKER.teacher_forced:
 135:             _RANKER.observe_external(observation, chosen)
 136:             if _PLANNER is not None:
 137:                 _PLANNER.note(observation, select, chosen)
 138:         return rule_choice
 139:     if not _PLANNER_DISABLED:
 140:         index = _PLANNER.adjust(
 141:             observation, select, index, _RANKER.last_scores
 142:         )
 143:     if _SEARCH is not None and not _RANKER.teacher_forced:
 144:         _SEARCH.budget.note(observation)
 145:         try:
 146:             improved = _SEARCH.suggest(observation, index)
 147:         except Exception:  # noqa: BLE001
 148:             improved = None
 149:         if improved is not None:
 150:             index = improved
 151:     _RANKER.commit(index)
 152:     if _PLANNER is not None and not _RANKER.teacher_forced:
 153:         _PLANNER.note(observation, select, index)
 154:     return [index]
```

## main.py: 157–167

```python
 157: def observe_external(observation, chosen):
 158:     """Advance every history with an action we did not choose.
 159: 
 160:     Teacher-forced evaluation replays a stored game, so the ranker's intra-turn
 161:     columns and the planner's per-turn heal budget both have to follow the
 162:     teacher rather than our own suggestion.
 163:     """
 164:     if _RANKER is not None:
 165:         _RANKER.observe_external(observation, chosen)
 166:     if _PLANNER is not None and isinstance(observation, dict):
 167:         _PLANNER.note(observation, observation.get("select") or {}, chosen)
```

## ml_runtime.py: 182–211

```python
 182: class Ranker:
 183:     def __init__(self, model_path: str = "ranker_model.json"):
 184:         with open(_resolve(model_path), encoding="utf-8") as handle:
 185:             self.model = json.load(handle)
 186:         for tree in self.model["trees"]:
 187:             _prepare(tree)
 188:         self.names: list[str] = list(self.model["feature_names"])
 189:         # Contexts the export measured as worth routing. Without it every
 190:         # context in SCORABLE_CONTEXTS is scored, which shipped context 8 on
 191:         # 9 held-out decisions at 22% Top-1 - a rule replaced by noise.
 192:         routed = self.model.get("routed_contexts")
 193:         self.contexts = (
 194:             ml_features.SCORABLE_CONTEXTS
 195:             if routed is None
 196:             else frozenset(int(c) for c in routed)
 197:         )
 198:         self.teacher_code = self.model.get("teacher_team_code")
 199:         self.teacher_index = (
 200:             self.names.index("teacher_team_id")
 201:             if "teacher_team_id" in self.names else -1
 202:         )
 203:         if (self.teacher_index >= 0) != (self.teacher_code is not None):
 204:             raise ValueError(
 205:                 "model has teacher_team_id but no teacher_team_code (or "
 206:                 "vice versa); inference would score an unseen pilot"
 207:             )
 208:         self.escalation_mode = escalation_mode()
 209:         # A class whose column the model never saw cannot be detected, so it is
 210:         # dropped rather than left to read a missing feature as -1.
 211:         self.escalation_classes = tuple(
```

## ml_runtime.py: 265–298

```python
 265:     def is_main(select: dict[str, Any] | None) -> bool:
 266:         if not select:
 267:             return False
 268:         options = select.get("option") or []
 269:         return (
 270:             int(select.get("context", -1)) == MAIN_CONTEXT
 271:             and int(select.get("minCount") or 0) == 1
 272:             and int(select.get("maxCount") or 0) == 1
 273:             and len(options) >= 2
 274:         )
 275: 
 276:     def is_scorable(self, select: dict[str, Any] | None) -> bool:
 277:         """Every single-pick select this model was measured as fit to decide.
 278: 
 279:         v1 answered this for MAIN only and left deck search and damage
 280:         placement to the rule policy, which matched the pinned teacher 39.5%
 281:         and 50-65% of the time. Optional selects count: across 3,655 games the
 282:         teachers never declined one, so there is no decline branch.
 283: 
 284:         The context must also be in the export's routed list. Routing every
 285:         scorable context unconditionally shipped context 8 on 9 held-out
 286:         decisions at 22% Top-1; a context with no data behind it is better
 287:         left to the rule that already handles it.
 288:         """
 289:         if not select:
 290:             return False
 291:         options = select.get("option") or []
 292:         return (
 293:             int(select.get("context", -1)) in self.contexts
 294:             and int(select.get("minCount") or 0) <= 1
 295:             and int(select.get("maxCount") or 0) == 1
 296:             and len(options) >= 2
 297:         )
 298: 
```

## ml_runtime.py: 319–353

```python
 319:     def _rows(self, observation: dict[str, Any]) -> tuple[
 320:         list[dict[str, Any]], list[int]
 321:     ]:
 322:         current = observation.get("current") or {}
 323:         select = observation.get("select") or {}
 324:         options = list(select.get("option") or [])
 325:         base = ml_features.state_features(current)
 326:         base.update(ml_features.observation_features(observation))
 327:         action_map = {
 328:             name: index
 329:             for index, name in enumerate(ml_features.ACTION_TYPES)
 330:         }
 331:         features: list[dict[str, Any]] = []
 332:         for position, option in enumerate(options):
 333:             row = dict(ml_features.option_features(
 334:                 current, select, option,
 335:                 base_state=base, option_position=position,
 336:             ))
 337:             row["action_type_id"] = action_map.get(
 338:                 str(row.pop("action_type", "other")), action_map["other"]
 339:             )
 340:             features.append(row)
 341: 
 342:         # Same collapse rule as the corpus builder: interchangeable copies are
 343:         # one candidate, and the first occurrence represents the group.
 344:         representatives: list[int] = []
 345:         seen: set[tuple] = set()
 346:         for position, row in enumerate(features):
 347:             key = self._semantic(row)
 348:             if key in seen:
 349:                 continue
 350:             seen.add(key)
 351:             representatives.append(position)
 352:         return features, representatives
 353: 
```

## ml_runtime.py: 418–455

```python
 418:     def choose(self, observation: dict[str, Any]) -> int | None:
 419:         """Index into ``select.option``, or None to defer to the rule policy.
 420: 
 421:         Scoring and history are separate steps. ``commit`` must be called with
 422:         the action that was actually taken, which in live play is this one but
 423:         under teacher-forced evaluation is the teacher's, so the intra-turn
 424:         columns describe the same turn the offline corpus described.
 425:         """
 426:         select = observation.get("select") or {}
 427:         self._pending = None
 428:         self.last_scores = {}
 429:         if not self.is_scorable(select):
 430:             return None
 431:         self.stats["main_decisions"] += 1
 432:         if not self.is_main(select):
 433:             self.stats["non_main_decisions"] += 1
 434:         try:
 435:             features, representatives = self._rows(observation)
 436:             self._turn_state(observation, features)
 437:         except Exception:
 438:             self.stats["feature_errors"] += 1
 439:             return None
 440:         if len(representatives) < 2:
 441:             # The corpus builder drops these and never advances the intra-turn
 442:             # history for them, so neither can we or the offer/pass counts
 443:             # drift away from the columns the model was fitted on. Every
 444:             # option is interchangeable here anyway.
 445:             return None
 446:         self._pending = features
 447:         spec = self._escalated_class(select, features, representatives)
 448:         if spec is not None:
 449:             self.stats["escalation_offered"] += 1
 450:             self.stats[f"escalation_offered_{spec['name']}"] += 1
 451:         try:
 452:             if spec is not None and self.escalation_mode == "class":
 453:                 self.stats["escalation_scored"] += 1
 454:                 best_index, scores = self._score(
 455:                     features, representatives, self.escalation_code
```

## ml_runtime.py: 493–519

```python
 493:     def _score(
 494:         self,
 495:         features: list[dict[str, Any]],
 496:         representatives: list[int],
 497:         teacher_code: Any,
 498:     ) -> tuple[int, dict[int, float]]:
 499:         """Argmax and every score, all as the same pilot.
 500: 
 501:         One teacher code per argmax is the invariant: scores from two different
 502:         pilots are two different functions, and comparing them inside one
 503:         comparison would be comparing two scales.
 504:         """
 505:         best_index = representatives[0]
 506:         best_score = None
 507:         scores: dict[int, float] = {}
 508:         for position in representatives:
 509:             row = features[position]
 510:             vector = [float(row.get(name, -1)) for name in self.names]
 511:             if self.teacher_index >= 0:
 512:                 vector[self.teacher_index] = float(teacher_code)
 513:             score = tree_score(vector, self.model)
 514:             scores[position] = score
 515:             if best_score is None or score > best_score:
 516:                 best_score = score
 517:                 best_index = position
 518:         return best_index, scores
 519: 
```

## ml_runtime.py: 548–570

```python
 548:     def commit(self, chosen: int) -> None:
 549:         """Advance the intra-turn history with the action actually taken."""
 550:         features = self._pending
 551:         self._pending = None
 552:         if self.teacher_forced:
 553:             return  # observe_external will advance with the teacher's action
 554:         if features and 0 <= chosen < len(features):
 555:             self.note_decision(features, chosen)
 556: 
 557:     def observe_external(self, observation: dict[str, Any],
 558:                          chosen: int) -> None:
 559:         """Keep the turn history aligned when the rule policy decided."""
 560:         if not self.is_corpus_scorable(observation.get("select")):
 561:             return
 562:         try:
 563:             features, representatives = self._rows(observation)
 564:             if len(representatives) < 2:
 565:                 return
 566:             self._turn_state(observation, features)
 567:             if 0 <= chosen < len(features):
 568:                 self.note_decision(features, chosen)
 569:         except Exception:
 570:             self.stats["feature_errors"] += 1
```

## ml_planner.py: 40–62

```python
  40: class Planner:
  41:     def __init__(self) -> None:
  42:         self.reset()
  43: 
  44:     def reset(self) -> None:
  45:         self._turn: int | None = None
  46:         self._munkidori_uses = 0
  47:         self.stats: dict[str, int] = {
  48:             "considered": 0,
  49:             "boss_route_considered": 0,
  50:             "boss_route_overrides": 0,
  51:             "heal_considered": 0,
  52:             "heal_overrides": 0,
  53:             "froslass_considered": 0,
  54:             "froslass_overrides": 0,
  55:             "wall_unlock_considered": 0,
  56:             "wall_unlock_overrides": 0,
  57:             "punk_alloc_considered": 0,
  58:             "punk_alloc_trigger_overrides": 0,
  59:             "punk_alloc_stack_overrides": 0,
  60:             "errors": 0,
  61:         }
  62: 
```

## ml_planner.py: 116–143

```python
 116:     def adjust(
 117:         self,
 118:         observation: dict[str, Any],
 119:         select: dict[str, Any],
 120:         index: int,
 121:         scores: dict[int, float] | None = None,
 122:     ) -> int:
 123:         """The ranker's index, or a dominating one. Never raises."""
 124:         try:
 125:             self.stats["considered"] += 1
 126:             context = int(select.get("context", -1))
 127:             if context in BOSS_TARGET_CONTEXTS:
 128:                 return self._boss_route(observation, select, index, scores)
 129:             if context == mf.CTX_REMOVE_DAMAGE_COUNTER:
 130:                 return self._heal_source(observation, select, index, scores)
 131:             if context == mf.CTX_ATTACH_FROM:
 132:                 return self._punk_allocation(
 133:                     observation, select, index, scores
 134:                 )
 135:             if context == mf.MAIN_CONTEXT:
 136:                 moved = self._wall_unlock(observation, select, index, scores)
 137:                 if moved != index:
 138:                     return moved
 139:                 return self._froslass_guard(observation, select, index, scores)
 140:             return index
 141:         except Exception:
 142:             self.stats["errors"] += 1
 143:             return index
```

## ml_planner.py: 498–508

```python
 498: def _best_by_score(
 499:     candidates: list[int],
 500:     scores: dict[int, float] | None,
 501: ) -> int:
 502:     """Keep the ranker's preference inside the set the planner allows."""
 503:     if not scores:
 504:         return candidates[0]
 505:     scored = [slot for slot in candidates if slot in scores]
 506:     if not scored:
 507:         return candidates[0]
 508:     return max(scored, key=lambda slot: scores[slot])
```

## turn_search.py: 1–64

```python
   1: """Within-turn line search with prize authority.
   2: 
   3: Three previous versions shipped a search layer and none of them ever changed a
   4: played action: v7 overrode once in 1,706 decisions, v11 and v27 zero times.
   5: The reason each time was the same - they searched *past* the end of our own
   6: turn, so the leaf had to be scored by a value model over a believed opponent
   7: hand, and the gates needed to make that trustworthy were tight enough to make
   8: it inert.
   9: 
  10: This layer searches strictly to the end of our own turn and stops there.
  11: Inside our own turn the only hidden information that matters is the order of
  12: our own deck, and our 60-card list is known exactly, so the determinization is
  13: honest rather than believed.  The leaf is then scored on one thing the value
  14: model was never needed for: how many prizes the line takes.
  15: 
  16: Authority is correspondingly narrow.  The layer may only overrule the v22
  17: ranker when some line starting from a different action takes strictly more
  18: prizes this turn - or wins outright - than any line starting from the ranker's
  19: own action, and when that holds on every determinization sampled.  Anything
  20: else, any exception, any budget pressure, and the ranker's answer stands.
  21: """
  22: 
  23: from __future__ import annotations
  24: 
  25: import os
  26: import random
  27: import time
  28: from typing import Any, Callable
  29: 
  30: MAIN_CONTEXT = 0
  31: OPT_ATTACK = 13
  32: OPT_END = 14
  33: 
  34: # Basic {D} Energy.  Fills the opponent's hidden zones: they never draw, play
  35: # or attack inside our own turn, so the contents cannot change the line, and a
  36: # basic Energy has no copy limit to violate.
  37: FILLER_CARD = 7
  38: 
  39: # OFF, on measurement.  Paired 320-game local mirror arenas against v22, with
  40: # the arena calibrated on a null control (v22 against a byte-identical copy of
  41: # itself scored 0.4917 [0.429, 0.554] over 240 games with a 59/120-59/120 seat
  42: # split, so the instrument is unbiased):
  43: #
  44: #   override the opening only         0.478  [0.424, 0.533]
  45: #   commit the whole line             0.344  [0.294, 0.397]
  46: #
  47: # The layer finds real extra prizes - 4.7% of our turns have a line taking a
  48: # prize the ranker's action cannot, and committing collects 36 where the ranker
  49: # takes 10 - but converting them costs more than they are worth, and the more
  50: # faithfully the prize-maximal line is executed the worse the agent plays.
  51: # Prizes-taken-this-turn is not a sufficient objective for a turn.  The module
  52: # ships disabled so the result is reproducible, not so it can be switched on.
  53: ENABLED = False
  54: 
  55: DEFAULT_MAX_NODES = 6000
  56: DEFAULT_BEAM = 32
  57: DEFAULT_BRANCH = 30
  58: DEFAULT_DEPTH = 44
  59: DEFAULT_DETERMINIZATIONS = 2
  60: DEFAULT_PER_DECISION_SECONDS = 3.5
  61: MIN_TURN = 3
  62: 
  63: # The Kaggle bank is 600 s per episode and actTimeout is 0.  v22 itself spends
  64: # 5-20 s of it, so almost all of it is free; keep a wide reserve anyway.
```

## turn_search.py: 669–693

```python
 669:     def suggest(
 670:         self, observation: dict[str, Any], ranker_index: int
 671:     ) -> int | None:
 672:         """Return an index to play instead of ``ranker_index``, or None."""
 673:         self.last = {}
 674:         select = observation.get("select") or {}
 675:         current = observation.get("current") or {}
 676:         if int(select.get("context", -1)) != MAIN_CONTEXT:
 677:             return None
 678:         if int(select.get("maxCount") or 0) != 1:
 679:             return None
 680:         options = select.get("option") or []
 681:         if not 0 <= ranker_index < len(options):
 682:             return None
 683:         if int(current.get("turn", 0)) < MIN_TURN:
 684:             return None
 685:         if not observation.get("search_begin_input"):
 686:             return None
 687:         self.budget.considered += 1
 688:         allowance = min(self.per_decision_seconds, self.budget.available())
 689:         if allowance < 0.4:
 690:             self.budget.skipped_budget += 1
 691:             return None
 692: 
 693:         seat = int(current.get("yourIndex", 0))
```

## turn_search.py: 731–795

```python
 731:                 challengers: dict[tuple, tuple[int, int, int, int]] = {}
 732:                 best_line: dict[tuple, dict[str, Any]] = {}
 733:                 for line in complete:
 734:                     key = line["first_signature"]
 735:                     score = (
 736:                         1 if line["result"] == seat else 0,
 737:                         line["prizes"],
 738:                         line["threat"],
 739:                         line["damage"],
 740:                     )
 741:                     if key not in best_by_first or score > best_by_first[key]:
 742:                         best_by_first[key] = score
 743:                     if line.get("uses_deck"):
 744:                         continue
 745:                     if key not in challengers or score > challengers[key]:
 746:                         challengers[key] = score
 747:                         best_line[key] = line
 748:                 if chosen_signature not in best_by_first:
 749:                     self.budget.no_baseline += 1
 750:                     return None
 751:                 if not challengers:
 752:                     self.budget.no_committable += 1
 753:                     return None
 754:                 baseline = best_by_first[chosen_signature]
 755:                 best_key, best_score = max(
 756:                     challengers.items(), key=lambda item: item[1]
 757:                 )
 758:                 # Level 1: only a win or an extra prize may overrule a policy
 759:                 # that imitates a 1220-rated pilot.  Level 2 additionally
 760:                 # allows a line that leaves the opponent's Active inside
 761:                 # Shadow Bullet range when the ranker's line does not, which
 762:                 # is the one damage difference that is certain to be worth
 763:                 # something next turn.
 764:                 improvement = (
 765:                     best_score[0] > baseline[0]
 766:                     or best_score[1] > baseline[1]
 767:                     or (
 768:                         self.authority >= 2
 769:                         and best_score[:2] == baseline[:2]
 770:                         and best_score[2] > baseline[2]
 771:                     )
 772:                 )
 773:                 if not improvement:
 774:                     self.budget.no_improvement += 1
 775:                     return None
 776:                 if world == 0:
 777:                     self.budget.improved_first_world += 1
 778:                     plan_line = best_line[best_key]
 779:                 winners.append(best_key)
 780:                 margins.append(best_score[1] - baseline[1])
 781:         except SearchUnavailable:
 782:             return None
 783:         except Exception:  # noqa: BLE001
 784:             self.budget.errors += 1
 785:             return None
 786:         finally:
 787:             if self.state_guard is not None and saved is not None:
 788:                 try:
 789:                     self.state_guard[1](saved)
 790:                 except Exception:  # noqa: BLE001
 791:                     pass
 792:             self.budget.charge(time.monotonic() - started)
 793: 
 794:         if len(set(winners)) != 1:
 795:             self.budget.world_disagreement += 1
```

## turn_search.py: 832–881

```python
 832:     def planned(self, observation: dict[str, Any]) -> list[int] | None:
 833:         """The next selection of a committed line, or None to drop the plan."""
 834:         if not self.plan:
 835:             return None
 836:         current = observation.get("current") or {}
 837:         select = observation.get("select") or {}
 838:         if int(current.get("turn", -1)) != self.plan["turn"]:
 839:             self.plan = None
 840:             return None
 841:         cursor = self.plan["cursor"]
 842:         steps = self.plan["steps"]
 843:         if cursor >= len(steps):
 844:             self.plan = None
 845:             return None
 846:         wanted_context, wanted = steps[cursor]
 847:         live_context = int(select.get("context", -1))
 848:         if live_context != wanted_context:
 849:             # The live turn is being asked something the plan does not
 850:             # describe; the two have desynchronised.
 851:             self.plan = None
 852:             self.budget.plans_abandoned += 1
 853:             key = f"desync live{live_context}!=plan{wanted_context}@{cursor}"
 854:             self.budget.abandon_at[key] = self.budget.abandon_at.get(key, 0) + 1
 855:             return None
 856:         indices = resolve_selection(observation, wanted)
 857:         minimum = int(select.get("minCount") or 0)
 858:         maximum = int(select.get("maxCount") or 0)
 859:         if (
 860:             indices is None
 861:             or len(indices) < minimum
 862:             or (maximum and len(indices) > maximum)
 863:         ):
 864:             # The real deck order took the turn somewhere the plan does not
 865:             # describe.  Abandon rather than play a half-understood line.
 866:             self.plan = None
 867:             self.budget.plans_abandoned += 1
 868:             key = (
 869:                 f"ctx{live_context}/step{cursor}of{len(steps)}"
 870:                 f"/{'unresolved' if indices is None else 'count'}"
 871:             )
 872:             self.budget.abandon_at[key] = self.budget.abandon_at.get(key, 0) + 1
 873:             return None
 874:         self.plan["cursor"] = cursor + 1
 875:         self.budget.plan_steps += 1
 876:         return indices
 877: 
 878:     def drop_plan(self) -> None:
 879:         self.plan = None
 880: 
 881:     def reset(self) -> None:
```

## turn_search.py: 904–933

```python
 904: def build(deck_path: str, multi_pick=None, **kwargs) -> TurnSearch | None:
 905:     """Construct the layer, letting an A/B run retune it without a code edit.
 906: 
 907:     The environment overrides exist so the arena can measure one setting
 908:     against another; the shipped defaults are the constants at the top of this
 909:     module and no submission depends on the environment being set.
 910:     """
 911:     if not ENABLED or os.environ.get("GRIMMSNARL_TURN_SEARCH_DISABLE") == "1":
 912:         return None
 913:     here = os.path.dirname(os.path.abspath(__file__))
 914:     path = deck_path if os.path.isabs(deck_path) else os.path.join(here, deck_path)
 915:     with open(path, encoding="utf-8") as handle:
 916:         deck = [int(line) for line in handle.read().split() if line.strip()]
 917:     if len(deck) != 60:
 918:         return None
 919:     kwargs.setdefault("authority", _env_int("GRIMMSNARL_SEARCH_AUTHORITY", 1))
 920:     kwargs.setdefault(
 921:         "commit_plan", _env_int("GRIMMSNARL_SEARCH_COMMIT", 1) == 1
 922:     )
 923:     kwargs.setdefault(
 924:         "determinizations",
 925:         _env_int("GRIMMSNARL_SEARCH_WORLDS", DEFAULT_DETERMINIZATIONS),
 926:     )
 927:     kwargs.setdefault(
 928:         "per_decision_seconds",
 929:         _env_float("GRIMMSNARL_SEARCH_SECONDS", DEFAULT_PER_DECISION_SECONDS),
 930:     )
 931:     kwargs.setdefault("max_nodes", _env_int("GRIMMSNARL_SEARCH_NODES",
 932:                                             DEFAULT_MAX_NODES))
 933:     return TurnSearch(deck, multi_pick=multi_pick, **kwargs)
```

## モデル実体から確認した値

```json
{
  "format": "lightgbm_tree_v2",
  "kind": "grimmsnarl_ranker",
  "average_output": false,
  "routed_contexts": [
    0,
    1,
    3,
    4,
    5,
    7,
    13,
    15,
    16,
    21,
    37,
    38,
    40,
    41,
    43
  ],
  "routing_min_context_support": 400,
  "routing_min_context_top1": 0.6,
  "teacher_team_id": 16371703,
  "teacher_team_code": 0
}
```

Trees: 2000
Feature count: 823
