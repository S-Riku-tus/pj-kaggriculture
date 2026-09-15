# 公開状態routerのclean-room評価（2026-09-14/15）

## 結論

最終判断は **REJECT_SAFETY** である。P1_psr_clean は旧spent panelで 24/0/8、V111比
win-score差 +0.3750 を得たが、raw Safetyは
32/32 contextで不合格となり、V111の既存勝ちも
2件失った。production ChampionはV111のまま維持する。

Kaggle提出、kernel push、submission slot変更は実施していない。promotion seeds
10091101–10091112、Fresh seeds 10091901–10091912、新規Development seeds
10091421–10091436はいずれも未使用である。

## Sourceとintegrity

公開notebook [Kaggriculture: 93.8% Win Rate Public State Router](https://www.kaggle.com/code/thomastschinkel/kaggriculture-93-8-win-rate-public-state-router)
のVersion 3をread-only APIで取得した。main.py SHA-256は
`91772fda544e2d5768afff819e2de75ecb7a12db8acb40a48ee9edcf76aca434`である。
表示licenseはApache-2.0だが、本文が言及するroute-data provenance.jsonを取得物内で確認できず、
transitive provenance/licenseは未確認である。そのためP1は結果にかかわらずresearch-onlyとした。

静的・runtime監査ではP1にopponent名/source/seed/ID、既知相手position signature、将来SELL表、
private opponent state、future RNGへの依存は見つからなかった。P1はstep 0から単独で動き、
外側のv56 opening、E030、tape/oracle、step216 hybrid等を混ぜていない。

## Paired結果

| candidate | W/D/L | V111比 win-score差 | raw Safety | L→W blocks | W→L |
|---|---:|---:|---:|---:|---:|
| R0 v116 frozen | 20/8/4 | +0.3750 | 28/32 | 5 | 0 |
| D1 no tape | 22/2/8 | +0.3438 | 28/32 | 6 | 2 |
| P1 clean PSR | 24/0/8 | +0.3750 | 32/32 | 7 | 2 |

P1のsource別差は、mooman +0.0000、
souvik +1.0000、ggmljs
+0.0000、qeinstein
+0.5000だった。whole source+seed block bootstrap
95%区間は [+0.0625,
+0.6875] である。両seatは各source+seedの1事例として保持した。

## Tape交絡とablation

既存32 replayの独立再計算は、tape2がmoomanとsouvikで各8/8、qeinsteinとggmljsで0/8
という既報と一致した。sidecar tracerは32×719 decisionの実actionと完全一致した。

D1ではqeinsteinのL→W 4件とsouvikのL→W 6件が残り、souvik改善は件数上は縮まなかった。
ただしR0→D1の全体差は -0.0312 で、D1は
raw Safety 28/32かつW→L 2件の診断候補である。この同一context結果は、tapeが無因果であることや
別panelへの一般化を証明しない。D1→P1は複数層が同時に変わるため単一component効果とは呼ばない。

## Safetyとrepair判断

P1では新規animal lossとcrop-to-weedがともに32/32で発生した。first-event監査は、animal lossを
2日連続未給餌によるescape（必須FEED欠落）として、crop-to-weedをwater deathまたはlifespan decay/
収穫欠落として区別した。さらにsource依存でsilent market no-op、partial commit、field no-opもある。
これは1個のinvalid actionをPASSへ置換するだけでは隠せない複数contract failureである。

P1は既にW→L=2でPrimary efficacy条件も外しているため、Safety専用repairで救済するP2の作成条件を
満たさない。勝敗を見てrepairを選ぶこと、複数repair探索は行わなかった。

## 独立sourceと一般化

Primary結果を見る前のV111-only screenでは、Deepesh、Lonespear、robriculture_lean_feedの3 source
すべてにV111が8/8勝ち、win-score 1.0だった。事前登録の0.25–0.75を満たすsourceは0件で、
追加sourceは選択されなかった。したがって検証済みancestryは既存2群のままで、強い第3 ancestryへの
一般化は未証明である。最終status上限は`PROMISING_UNPROVEN`だったが、P1自身はSafety不合格のため
`REJECT_SAFETY`となる。

## Gateと終了状態

Primary discovery gateは `false`。失敗項目は
raw_safety_zero, win_to_loss_zero である。
このため新規Development確認は開始せず、numeric production agentも作成していない。
experiment内のP1/D1 archiveはresearch-onlyであり、V111を変更しない。

全gameは720 states（通常719 decisions）を完走し、runtime error、timeout、negative cash、delivery failureは0。
A/AはV111、D1、P1のすべてで独立ロード間のaction/state/final coinが一致した。旧V111 controlは
evaluator metadataの不整合を保守的に扱って再利用せず独立再実行し、旧replayと
`remainingOverageTime`を除く全720 stateが一致した。

詳細なsource/ancestry集計、9 reweighting、除外感度、bootstrap、divergence、coin、lifecycle、
terminal proxy、order/step監査、sample-in safe oracleはcandidate summaryと
`performance_attribution.json`に保存した。相手coin低下はclosed-loopのtotal-policy差であり、
単一actionの因果効果とは解釈しない。
