# 実装差分

## A0

Round8 spatial pure v6 archiveを変更せず使用した。これは比較基準であり、hashは `0b579c...a6e30`。

## A1

- Round8の重みと観測特徴の意味を凍結した。
- 同turnで確定した先行actor actionだけをshadow stateへ適用し、後続actorの合法手と数量を再計算した。
- marketは最終actor後の状態を参照するようにした。
- 手書きplan、v124呼出し、教師tapeは推論に使用しない。

A1は実行契約だけを直す対照であり、新checkpointではない。8試合ではA0より悪化したため昇格しなかった。

## A2

- 学習データ生成と推論の双方で、actorのaccepted prefixおよびmarketのaccepted order prefixを同じ特徴契約に統一した。
- market prefixに注文token、受入数量、残予算、在庫、雇用・土地増分を反映した。相手の未来注文は入力しない。
- seat+stepだけの古いspatial cacheに依存せず、prefix revisionごとに再計算する。
- `shadow` と `reserved` の二重控除を廃止し、accepted shadow stateを資源の権威にした。
- marketの全量購入不能時の全削除をやめ、固定engineの部分約定に合わせた。
- A2用の4 headを2 learning seedで実学習し、validationだけでseed 20260924を選択した。

## 実験中に発見して直した実装欠陥

1. A1/A2の`main.py`が`model_compat`より先にruntimeをimportし、3層checkpointの`w2`を出力層として誤解釈して`w3`を使わない可能性があった。import順を固定し、最終archiveから読み込んだ4重みhashを検証した。
2. actor shadowで、通常の`WATER`後に作物yieldを増やす固定engineの処理が欠けていた。非施肥は+1、施肥中は+2、作物上限までという固定engine式へ合わせた。
3. 同一module callableで連続episodeを実行すると履歴が残る可能性があった。step 0でruntime stateをresetするようにし、外部展開した最終archiveで2 episode連続検証した。

## 固定engine差分fixture

`fixed_engine_fixtures_v1.json` の15/15が通過した。PLANT→WATER、HARVEST→PLANT、BUILD→PLACE、PLACE→PICKUP、重複FEED後CARE、WATER→HARVEST、FERTILIZE→WATER→HARVEST、種不足、部分取得、倉庫満杯、部分購入、SELL→BUY、DROP→SELL、日替わり、終局直前を数量まで照合した。

## 変更していないもの

- Round8 archive、原リプレイ、既存split、過去結果は上書きしていない。
- 推論時にv122/v124、teacher action tape、既存router、手書き畜産planを呼ばない。
- public/private境界を変更せず、相手private、未来Shop、未来action、終局結果を特徴へ入れない。
- Kaggle提出は作成していない。

