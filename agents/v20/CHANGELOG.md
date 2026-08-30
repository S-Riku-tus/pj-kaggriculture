# V20 changelog

- Added intraday 24-hour labels alongside 72-hour labels.
- Trained independent 24-hour and 72-hour seat-aware Cow advantage forests.
- Required material validation improvement at both horizons.
- Required both forests and uncertainty gates to support purchase delay.
- Left Sheep, crop strategy, and deterministic execution unchanged.
- Rejected and disabled after 1-2 delayed-purchase steps caused severe closed-loop regression.
