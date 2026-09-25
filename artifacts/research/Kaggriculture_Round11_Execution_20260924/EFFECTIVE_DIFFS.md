# Round11 Effective Diffs

## B1 / NO_CHANGE

- B1 sourceは変更なし。
- NO_CHANGEはB1を1回呼ぶだけで、公式2組の全720状態・719判断が完全一致。

## 公開原版

- 6原版は取得した最後のcallableをそのまま実行した。
- More Wheat原版は3近傍軌跡を保持する一方、B1最後の`opening_liquidity_agent`を持たず、原版比較はその機能だけのablationではない。
- Order Book v3原版もE410/E402/rescue/openingを保持しない。
- raw replayの生産列は6候補すべてB1と一致。名前を独立な生産familyとして数えない。

## M20 multi hypothesis

- `_v92_p_forecast`: top1から、最高scoreとの差1.0以内・最大3軌跡へ変更。
- `_v92_predict`: 代替軌跡だけが成立させた発火をtelemetryへ追加。
- B1の全chain、BUY8/SELL3 opening、最後の`opening_liquidity_agent`を保持。
- 開発: 最終行動244判断変更、得点+5/32試合。
- holdout: 最終行動3,234判断変更、得点−1/192試合。REJECT。

## M11 final-order response

- B1本体は1判断につき1回だけ呼ぶ。
- copyした最終action上で既存候補集合を評価。
- 固定価格注文は前へ動かさず、BUY_PRODUCTと同品目SELLを除外。
- final仮説は36判断を変更、混合仮説は採用0。併用はM20を一次得点で上回らない。

## WOOL controls

- `wool_gate_open_control`: `V9_RACEGATE_BASE["WOOL"]=0`だけを常時適用。32試合で得点率0.6875→0.625、最終行動1,320判断変更。REJECT。
- `cw1_conditional_wool`: 2/3予測、net rival>=8、現値>=150、予想価格低下>=5の場合だけ既存reserveを開く。
- CW1は内部予約8回・24個を記録したが、最終行動0変更・全32軌跡同一。実行不成立としてREJECT。

## 採用

- 新しい有効差分は採用しない。
- 最終選択はbyte不変のB1。

