# V8 Top-3 Expert Atlas Agent

V8 is selected by fidelity to public Rank 1-3 trajectories, not by win rate
against earlier repository agents.  It was trained from 447 non-self public
episodes: Rank 1 is the primary behavioural teacher, while Rank 2 and Rank 3
define the range in which imitation is considered reliable.

The strategy layer predicts absolute portfolio anchors 24 and 72 hours ahead
for crops, animals, hands, land, and pastures.  A confidence gate combines
tree disagreement with distance from the Top-3 state envelope.  Confident
states follow the learned expert target; unfamiliar states blend continuously
toward V7's observation-only safe targets.  Existing assets are always hard
lower bounds, so predictions cannot repeatedly sell or recreate a delta.

Day 0 keeps the proven deterministic opening.  Days 1-5 use Rank 1's modal
field route only while farmer/hand positions still match the teacher.  Market
orders are copied only where their own consensus is at least 75%; otherwise
the dynamic market planner remains in control.  The executor keeps feed,
animal care, transaction feasibility, and final liquidation deterministic.

The local starter opponent is used only as an executable trajectory probe.
Its score and win rate are explicitly excluded from V8 selection.  The latest
four probe trajectories all completed without animal loss and averaged 68.0
productive tiles on Day 20 and 67.25 on Day 24.  These checks do not establish
a Kaggle rating or guarantee the stated 3000-rating goal.

Build the Kaggle artifact with:

```powershell
.\.venv\Scripts\python.exe scripts\package_submission.py --agent agents\v8
```

Submit `artifacts/submissions/v8.tar.gz`.
