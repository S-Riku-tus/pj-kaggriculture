# V67

V67 retains V63's day-11/12, teacher-in-domain role-continuity tie-break, then
adds a relative objective: the winner-only teacher model must predict that the
72-hour money-gap ratio will be at least its current value. Otherwise execution
falls back exactly to V14.

The added relative labels improved over day-only baselines on episode-held-out
validation and test logs. This establishes predictability, not causal rating
gain; closed-loop unseen-seed and opponent validation remains required.
