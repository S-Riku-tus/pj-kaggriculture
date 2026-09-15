# Clean PSR研究 事前登録（2026-09-14開始）

## 固定する問いと候補

Production ChampionはV111のまま固定する。Primaryは、既知相手の名前・source/seed identity・位置signature・将来SELL表を使わず、現行公開PSR Version 3をstep 0から単独実行する`P1_psr_clean`である。`D1_e052a_no_opponent_tape`はv116から既知相手tape経路だけを除いた交絡診断であり、成績にかかわらずpromotion候補にしない。`R0_v116_frozen_reference`は既存32結果のみを読む。

Primary仮説は、P1がqeinsteinで観測されたcomplete-policy価値の一部をtapeなしで保持し、途中委任よりroute/state整合性を保ち、R0よりraw Safetyを減らすというもの。ただしSafety 0は仮定しない。診断仮説は、D1がqeinsteinではR0に近く、tape2が8/8発火したsouvikでは改善が縮むというもの。

候補source/hash、engine 1.32.7、configuration、評価core、entrypoint、license状態は`candidate_integrity.json`、`source_acquisition.json`、`preregistration.json`へ凍結する。現行notebook本体はApache-2.0表示だが、本文が言及する`provenance.json`を取得物に含まず、route dataのtransitive licenseを確認できない。このためP1は少なくとも本研究ではresearch-onlyである。

## 実行順

新規game前にpackage import isolation、最後のcallable、両seat、step 0 resetをtestする。続いてV111、D1、P1を同じ固定contextで独立loadしてA/Aし、action/state/final coinが一致することを要求する。A/Aは自己対戦の引分要求ではない。

A/A後、P1の結果を生成する前に下記の独立source baseline-only screenと選定を完了する。その後のsmokeはqeinsteinとsouvik、seed 10091011、両seat。D1/P1の各gameが720 states（通常719 decisions）を完走し、traceとraw Safetyを先に確認する。その後だけ、旧spent Development 10091011–10091014、旧4 sources、両seatの32 contextをD1/P1それぞれfull720 paired評価する。R0は再走しない。pair keyはcandidate ID、candidate hash、evaluation-core hash、source、seed、seatを含み、pair完了ごとにJSONLへflush/fsyncする。重複・部分recordを拒否する。

## 独立source screen

P1/D1結果を見る前に、license・revision・native callable・import ancestryを監査した。baseline-only screen対象はDeepesh MIT、Lonespear MIT、robriculture lean_feed CC-BY-4.0の3件だけである。AlpeshとGzmCRはlicense未確認、COKとSeyamalamはpublic-route/PSR近縁なので除外する。

V111だけを同じspent 4 seeds・両seatで評価し、win-score 0.25–0.75（両端含む）を満たす独立sourceを最大2件選ぶ。複数なら、異なるancestry、opening、crop/animal portfolio、market timing、事前に付けたdiversity priority、source IDの順で決める。P1との相性を使わない。robricultureだけが残っても、過去0/0/4の弱いanchorなので強い第3 ancestryとは数えない。適格sourceがなければ最終上限は`PROMISING_UNPROVEN`とする。

## raw SafetyとPrimary discovery gate

raw Safetyは既存`classify_candidate_incidents`のhard-safety理由に、strict all-stepのsilent field/market no-op、partial market commit、missing handsを加えた事前登録理由とする。runtime error、timeout、incomplete、negative cash、delivery failure、crop-to-weed、spawned weed、animal lossを含み、32 contextすべてで理由0を要求する。絶対event数も別表示するが、事後的に比較定義を緩めない。

次をすべて満たした場合だけdiscovery合格とする。

- runtime/delivery違反0、raw Safety context 0。
- P1のV111比win-score差が正。
- L→Wが2以上の独立source-seed block、かつ2以上のsource。両seatは1事例。
- W→L 0。W→Dも悪化として表示し、全source別win-score差が非負。
- 自己対戦除外、tape2発火source除外、PSR/Kaito近縁除外の差がすべて非負。
- equal-source、equal-ancestry、sourceごとの1.2/0.8変動を含む計9 scenarioのworst deltaが正。
- source-seed block単位100,000回bootstrap（固定RNG seed 20260914）の95%下限が0より大きい。
- 禁止featureの静的・runtime監査に合格。

点推定、平均coin、標本内safe oracleで不合格を救済しない。safe oracleは標本内上界でありdeploy可能selector性能とは呼ばない。

## P2とDevelopment確認

P1がefficacyの可能性を保ちながらraw Safetyだけに失敗した場合に限り、勝敗をrepair選択に使わず、first-event contractから一種類だけ`P2_psr_clean_safety1`を定義できる。失敗action・資源・tile・unit・同日作業、source/seed/opponent非依存、一意の置換と優先順位、全置換log、schedule復帰条件を事前amendmentへ書く。単純PASS sanitizerが損失や必須作業欠落を隠せば不合格。P2も失敗したら探索を終了する。

P1または許可されたP2が全discovery gateを通った場合だけ、repository全体で未使用を再確認した10091421–10091436を16 block一括登録する。旧4 sourcesと事前選択した独立sourceを固定し、全seed・両seat・full720を行う。active 64以上、baseline敗戦上のsafe delivery 16以上、safe改善4 block以上かつ2 independent ancestry以上、全Safety/runtime/delivery 0、全source非悪化、block bootstrap下限>0、9 stress/equal-ancestry/全除外差>0、検証済み独立ancestry 3以上を要求する。未完了はE4合格としない。

promotion 10091101–10091112とFresh 10091901–10091912は全条件で封印し、Kaggle submission、kernel push、submission slot変更は行わない。discovery gateが一つでも不合格なら新規Developmentを開かず、閾値・selector・source・複数repairを探索しない。
