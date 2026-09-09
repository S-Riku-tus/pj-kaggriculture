# Kaggriculture V110

V110 keeps V109's complete sparse-shop trajectory family and deterministic
executor.  It adds a bounded public-state market controller for one supported
case: when repeated farm-state comparisons identify an opponent following the
same trajectory, a route-planned premium sale may be moved at most four turns
earlier.  If the opponent reacts with a matching early sale, a second-order
one-turn-earlier candidate becomes eligible.

The controller never uses team identity, rating, submission metadata, or the
opponent's private inventory.  It reconstructs opponent premium supply from
public market inventory changes, visible Town demand, and the candidate's own
effective sale.  `obs.step` is reconstructed from `day * 24 + hour` when the
environment omits it.

Three confidence tiers are explicit:

- confirmed near-clone: bounded H4/H5 premium-sale timing intervention;
- uncertain or different strategy: unchanged coherent V109 route;
- critical broken state: V109's latched, model-disabled deterministic V11
  fallback.

Opponent sale phases are recorded in diagnostics but do not change actions.
A 51-episode, episode-split playback rejected phase-only front-running: all 27
screened candidates had a non-positive logged future quote difference, with a
mean of -15.59.  That negative result is retained in
`data/analysis/v110_rejected_phase_gate.json`.

Normal closed-loop diagnostics covered starter, the distinct public V27
lineage, and V109 as state generators, both seats and two new seeds.  All 12
games completed with zero animal losses.  The old-agent games are diagnostic
only, not promotion evidence.  A separate forced-fallback pair also completed
with zero animal loss.

V110 is an offline-validated live candidate.  Rating 3000 is an objective, not
a verified or guaranteed result.  See `docs/v110_design_report.md` for facts,
inferences, rejected hypotheses, limitations, and reproduction commands.
