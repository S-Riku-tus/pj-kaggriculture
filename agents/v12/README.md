# V12

V12 is a research checkpoint on V11's safe executor. A conservatively selected
Rank-2 portfolio branch was evaluated, then disabled after unseen closed-loop
diagnostics exposed a severe lower-tail regression. The selection artifact is
retained so the rejected hypothesis remains reproducible.

Two executor experiments (Wheat pickup capping and local FEED-to-CARE
completion) remain available behind disabled flags for reproducible ablation.
They improved their direct proxy metrics but displaced feed/harvest work and
are not part of the release policy.

The 3000 rating objective is aspirational. Offline fidelity and local matches do
not establish leaderboard strength.
