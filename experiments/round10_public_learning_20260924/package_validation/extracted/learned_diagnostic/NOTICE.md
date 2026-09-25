# Attribution and modification notice

`base_main.py` in the generated archive is the public agent extracted from
Dmitrii Gluzdov's “Kaggriculture: Herd-Safe Sale Window | LB 2700”, notebook
version 2 as fetched on 2026-09-24. Its embedded Apache-2.0 license and upstream
notices are retained verbatim.

Round10's only B2 modification is in `main.py`: on engine step 0, replace B1's
Wheat `BUY 8 -> SELL 3 -> BUY_SEED 1` orders with
`BUY 10 -> SELL 5 -> BUY_SEED 1`. All later decisions call the unmodified
public B1 implementation on the actual closed-loop observation.
