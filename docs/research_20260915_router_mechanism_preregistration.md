# Router mechanism study preregistration — 2026-09-15

この研究は前回不合格PSRのrepairではなく、旧spent panel上の非tape改善を、public-state router、固定route、初期market/portfolio footprint、相手closed-loop応答へ切り分ける診断である。P1 full、D1、R0の既存pairは再実行せず、V111をproduction Championとして固定する。

実行順は、開始時監査、既存replayによるrouter/identity/timeline監査、合法かつstate-compatibleなA0/A1/A2だけのA/A・smoke・旧spent評価、mechanism gate、条件成立時だけのV111由来C1、旧spent compatibility、条件成立時だけのDevelopment確認、artifact検証、最終判断とする。

Primary contrastはP1 full対A0/A1/A2。A0はstep 0で選択されたown routeを719 decisions固定、A1はstep 144の再選択だけを無効化、A2はstep 576の再選択だけを無効化する。router固有価値の最低条件は、P1 fullが合法なA0より1 source-seed block以上改善し、2 sources以上で同方向、W→L増加または新Safety classなし。route固定が同等以上ならtotal-policy upliftをrouter upliftと呼ばない。

全ablationはresearch-only、promotion不可。raw Safetyを平均coinで救済しない。candidate/source/package、engine、configuration、opponent、seed、seat、evaluator hashをpair keyに含め、pairごとにflushする。A/A不一致、720 states未完走、schema異常、prefix incompatibilityは当該ablationをINVALID_ABLATIONとして止め、手補正variantへ置換しない。

C1はrouter固有価値またはD1/P1共通の公開状態機構が2 sources以上で残り、identity proxyでなく、V111のrepository-owned state-compatible suffixまたは毎step再検証contractとして調達から販売・rejoinまで一意に定義できる場合だけ作る。P1 blob/tape/tree/route/threshold/action列を使わない。旧spent gateの全条件を通るまで新Developmentを開かない。C2は単一Safety first-event familyだけに限る。

promotion 10091101–10091112、Fresh 10091901–10091912、旧Development 10091421–10091436は常に封印する。今回Development候補10091521–10091536もC1/C2旧spent gate通過時だけ一括登録・使用する。Kaggle提出、kernel push、submission slot変更を行わない。

license/provenance不明、identity-proxy判定不能、独立source不足、確認未完了の上限はPROMISING_UNPROVEN。deploy candidateのSafety違反、禁止feature、W→Lはreject。最終statusは指定された5値だけを用いる。
