# Kaggriculture continuation research report — 2026-09-12

## 判断

新しいcandidateは提出しない。production ChampionはV111のまま。実行可能な代替行動を6 options（売却2、非管理Sheep、Cow保持、管理付きSheep/Goose）でfull720 paired評価したが、validかつhard SafetyなしのL→Wを確認できなかった。したがってstate-dependent selectorは作成していない。総合判定は **REJECT_ALL_NEW_CANDIDATES_KEEP_V111**、提出判断は **DO_NOT_SUBMIT**。

最新取得時点 2026-09-12T04:33:26.213100+00:00 のLeaderboard #1は Majkel1337、Rating 3198.2、submission 56156662。自チームの最新表示はsubmission 56089444、Rating 1334.1だが、remote archive identityはunknownでlocal V111へ帰属させない。真のlocal ChampionはV111、source `699c73f75ec786e9bddcfabb6476fc64c07939f22abe3ed00691a5bef6f72660`、archive `85ba0176b1774ca1bc45f77601210d847e4bb8c01b550181c3c87bd3f6a1c85e`、engine `bc8a54879ef02c7ea64b8b333d6a976f0ea65c4949149d01f463f23bccee653e`（kaggle-environments 1.32.7）。

## Paired evaluation

`eligible / activation / engine-backed treatment`、W/D/L、勝敗反転を同じDevelopment 4 seeds×4 sources×両seatで比較した。seedはsource横断で共有されるため、独立blockは4だけである。平均coinは判断の補助で、勝敗反転を優先した。

| Option | eligible/active/actual | V111 W/D/L | candidate W/D/L | L→W/W→L | Δself | Δopp | Δmargin | Safety/invalid | 判断 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 在庫即時売却 | 32/32/32 | 12/0/20 | 12/0/20 | 0/0 | -83.4 | +151.5 | -234.9 | 0/0 | REJECT_NO_CAUSAL_UPLIFT |
| Town更新時売却 | 32/32/32 | 12/0/20 | 12/0/20 | 0/0 | -75.9 | +190.8 | -266.7 | 0/0 | REJECT_NO_CAUSAL_UPLIFT |
| 非管理Sheep強制 | 22/22/22 | 12/0/20 | 10/0/22 | 0/2 | -2385.5 | +284.3 | -2669.8 | 22/0 | REJECT_SAFETY_REGRESSION |
| Cow保持（区間設定不正） | 2/2/0 | 12/0/20 | 12/0/20 | 0/0 | -283.7 | +280.2 | -563.9 | 0/2 | INVALID_EVALUATION_CONFIGURATION |
| Cow保持r1 | 2/2/2 | 12/0/20 | 12/0/20 | 0/0 | -283.7 | +280.2 | -563.9 | 0/0 | REJECT_NO_CAUSAL_UPLIFT |
| 管理付きSheep | 22/22/22 | 12/0/20 | 10/0/22 | 0/2 | -2306.9 | -249.1 | -2057.8 | 0/0 | REJECT_NO_CAUSAL_UPLIFT_WITH_WIN_REGRESSION |
| 管理付きGoose | 22/22/22 | 12/0/20 | 10/0/22 | 0/2 | +128.2 | +1220.6 | -1092.4 | 0/0 | REJECT_NO_CAUSAL_UPLIFT_WITH_WIN_REGRESSION |

runner秒は各summaryの`elapsed_seconds_this_run`で、resume済み結果を再利用したrunを含むため候補間の速度比較には使わない。

| Option | runner sec | incomplete/runtime fail | invalid/unexpected div | delivery/tx fail | new no-op field/market | new failed buy | Δanimal loss | Δcrop→weed/empty→weed | negative cash |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 在庫即時売却 | 0.2 | 0/0 | 0/0 | 0/0 | 0/0 | 0 | 0 | +0/+0 | 0 |
| Town更新時売却 | 1583.0 | 0/0 | 0/0 | 0/0 | 0/0 | 0 | 0 | +0/+0 | 0 |
| 非管理Sheep強制 | 1389.6 | 0/0 | 0/0 | 0/0 | 126/219 | 0 | 0 | +0/+0 | 0 |
| Cow保持（区間設定不正） | 714.6 | 0/0 | 2/2 | 0/0 | 0/0 | 0 | 0 | +0/+0 | 0 |
| Cow保持r1 | 307.6 | 0/0 | 0/0 | 0/0 | 0/0 | 0 | 0 | +0/+0 | 0 |
| 管理付きSheep | 2726.1 | 0/0 | 0/0 | 0/0 | 0/0 | 0 | 0 | +0/+0 | 0 |
| 管理付きGoose | 2731.8 | 0/0 | 0/0 | 0/0 | 0/0 | 0 | 0 | +0/+0 | 0 |

Primaryに売却continuationを選んだ理由は、live shedだけで発火でき、field・必要購入・worker系列を変えず、V111の終盤在庫仮説を最小の実行契約として検証できたため。即時/Town同期の双方が32/32で安全に発火し、全64 contractでaction fidelity mismatch、field rewrite、必要購入変更、failed extra saleは0だった。しかしL→Wは0で、平均marginも悪化した。これは **no causal uplift** で棄却する。

非管理Sheepは22/32で発火し、L→W 0、W→L 2、発火22件すべてで新規silent no-opを生じたため **Safety regression**。Cow保持の初版はactionがt248で正しく変わったが、半開区間を`[248,248]`とした評価設定ミスで2件invalid。上書きせずr1を`[248,249)`で凍結・全件再実行した。管理付き動物も購入から配置後の空HARVEST回避・生成品売却まで契約として評価した。

### lineage別

| Option | lineage | candidate W/D/L | L→W/W→L | mean Δmargin |
| --- | --- | --- | --- | --- |
| 在庫即時売却 | ggmljs_v16 | 8/0/0 | 0/0 | -657.5 |
| 在庫即時売却 | mooman_e052a | 2/0/6 | 0/0 | +172.8 |
| 在庫即時売却 | qeinstein_moev2 | 2/0/6 | 0/0 | -278.8 |
| 在庫即時売却 | souvik_v4 | 0/0/8 | 0/0 | -176.0 |
| Town更新時売却 | ggmljs_v16 | 8/0/0 | 0/0 | -657.0 |
| Town更新時売却 | mooman_e052a | 2/0/6 | 0/0 | +17.0 |
| Town更新時売却 | qeinstein_moev2 | 2/0/6 | 0/0 | -271.0 |
| Town更新時売却 | souvik_v4 | 0/0/8 | 0/0 | -155.8 |
| 非管理Sheep強制 | ggmljs_v16 | 8/0/0 | 0/0 | -1080.1 |
| 非管理Sheep強制 | mooman_e052a | 2/0/6 | 0/0 | -4448.0 |
| 非管理Sheep強制 | qeinstein_moev2 | 0/0/8 | 0/2 | -3442.2 |
| 非管理Sheep強制 | souvik_v4 | 0/0/8 | 0/0 | -1709.0 |
| Cow保持r1 | ggmljs_v16 | 8/0/0 | 0/0 | -2255.8 |
| Cow保持r1 | mooman_e052a | 2/0/6 | 0/0 | +0.0 |
| Cow保持r1 | qeinstein_moev2 | 2/0/6 | 0/0 | +0.0 |
| Cow保持r1 | souvik_v4 | 0/0/8 | 0/0 | +0.0 |
| 管理付きSheep | ggmljs_v16 | 8/0/0 | 0/0 | +673.4 |
| 管理付きSheep | mooman_e052a | 2/0/6 | 0/0 | -4068.0 |
| 管理付きSheep | qeinstein_moev2 | 0/0/8 | 0/2 | -3535.5 |
| 管理付きSheep | souvik_v4 | 0/0/8 | 0/0 | -1301.2 |
| 管理付きGoose | ggmljs_v16 | 8/0/0 | 0/0 | +798.0 |
| 管理付きGoose | mooman_e052a | 2/0/6 | 0/0 | -3141.0 |
| 管理付きGoose | qeinstein_moev2 | 0/0/8 | 0/2 | -887.5 |
| 管理付きGoose | souvik_v4 | 0/0/8 | 0/0 | -1139.0 |

各summaryにはequal-weight payoff matrix、robust reweighting（radius 0.2）、Bradley–Terry diagnostic、whole-seed bootstrapを保存した。4 seed blockと保守的に2 ancestry群しかないため、0反転を「一般に不可能」とは解釈しない。

| Option | weighted Δwin score | robust worst Δ | seed-block 95% CI | BT ability差 [95%] |
| --- | --- | --- | --- | --- |
| 在庫即時売却 | +0.000 | +0.000 | [+0.000, +0.000] | -0.000 [-1.132, +1.132] |
| Town更新時売却 | +0.000 | +0.000 | [+0.000, +0.000] | -0.000 [-1.132, +1.132] |
| 非管理Sheep強制 | -0.062 | -0.112 | [-0.188, +0.000] | -0.870 [-2.366, +0.626] |
| Cow保持r1 | +0.000 | +0.000 | [+0.000, +0.000] | -0.000 [-1.132, +1.132] |
| 管理付きSheep | -0.062 | -0.112 | [-0.188, +0.000] | -0.870 [-2.366, +0.626] |
| 管理付きGoose | -0.062 | -0.112 | [-0.188, +0.000] | -0.870 [-2.366, +0.626] |

このDevelopment panelでのV111は一貫して12W/0D/20L（37.5%）。これは使用済み4 seedと旧4 sourceに条件付けたE3推定で、Leaderboard Ratingの推定値ではない。current Topとのsource照合ができないため、現在の実戦実力は未同定とする。

## V114敗戦説明の再検証

元のV114probe replay 24発火pairsを、凍結engine sourceから再生した。結果自体（0W/32L、L→W 0、W→L 12）は変わらない。

- 実行不整合: t153–215でfailed purchaseはcontrol 0、treatment 24。atomic PLANT blockは16→88、silent field no-opは44→188。固定Wheat=25の投影は実価格ではない。
- 自然寿命終了: lifespan endは360→473だが、その時点の未収穫yield合計は192→192。寿命件数の増加だけを収穫損失と呼べない。
- 水切れ: water deathは120→75、消失時のcurrent yieldは96→48。旧説明の「水管理崩壊」という一括原因は支持されない。
- 実収穫量: 各HARVEST action直前直後のprivate在庫差で、成功HARVESTを直接集計した。

| product | control | forced route | delta units |
| --- | --- | --- | --- |
| WHEAT | 9724 | 9492 | -232 |
| CARROT | 1368 | 576 | -792 |
| STRAWBERRY | 7456 | 5773 | -1683 |
| MELON | 1584 | 1584 | 0 |
| MILK | 6254 | 3294 | -2960 |
| WOOL | 2902 | 5568 | 2666 |

- 相手価格利益: 24件すべてで相手moneyが一時的にcontrolを上回り、最終self coin増の9件中5件では相手の増分がさらに大きかった。平均Δself -12712.3、Δopponent +96.9、Δmargin -12809.2。価格・数量・相手応答を含む総効果であり、媒介割合は同定していない。
- Town/RNG: 価格とTownは24/24で分岐し、Townの最初の差はt216。22/24では相手actionも後続分岐した。engineは空き地weed抽選後にTownを引くため、同seedでもactionで乱数消費経路が変わる。これらのpairを主評価から除外していない。

## source調査と感度

既存4 policy間のcomplete-policy round robinは非推移性を確認した。

| A | B | A W/D/L | A mean margin |
| --- | --- | --- | --- |
| ggmljs_v16 | mooman_e052a | 0/0/8 | -27927.2 |
| ggmljs_v16 | qeinstein_moev2 | 0/0/8 | -26920.5 |
| ggmljs_v16 | souvik_v4 | 0/0/8 | -26074.2 |
| mooman_e052a | qeinstein_moev2 | 6/0/2 | +3033.5 |
| mooman_e052a | souvik_v4 | 6/0/2 | +6916.0 |
| qeinstein_moev2 | souvik_v4 | 4/0/4 | +2567.0 |

独立public source `robriculture/lean_feed`（commit `7f54373b67cf41f71168f09457390f6663e3a6a1`、CC-BY-4.0）は4/4完走したがV111に0/0/4、平均margin -73608.2。独立ancestryのregression anchorには使えるが、強い代理相手とは扱わない。最新上位artifactのsource identityは依然unknown。

## Safety、holdout、artifact

評価順は実行妥当性→delivery→Safety→対戦改善。Safety違反をcoinで救済していない。P10 margin、day12/18/20/24 lead→loss、terminal stranded inventoryとfinal-price proxyは各candidateの`summary.json`に対応する `final_decision.json` の`economy`へ保存した。proxyは達成可能売却益ではない。

pair recordにはfirst self action/money/portfolio/position、public market/price/Town、opponent responseとlag、opponent moneyのdivergence auditを保存した。介入後のTown分岐を除外条件にはしていない。

| Option | P10 margin C→T | lead→loss D12/18/20/24 C→T | stranded proxy C→T | terminal stranded units C→T |
| --- | --- | --- | --- | --- |
| 在庫即時売却 | -23861→-24305 | 0→0/0→0/0→0/0→0 | 46.4→46.4 | STRAWBERRY:8, WOOL:30, FERTILIZER:40 → STRAWBERRY:8, WOOL:30, FERTILIZER:40 |
| Town更新時売却 | -23861→-24287 | 0→0/0→0/0→0/0→0 | 46.4→46.4 | STRAWBERRY:8, WOOL:30, FERTILIZER:40 → STRAWBERRY:8, WOOL:30, FERTILIZER:40 |
| 非管理Sheep強制 | -23861→-20989 | 0→0/0→0/0→0/0→0 | 46.4→423.9 | STRAWBERRY:8, WOOL:30, FERTILIZER:40 → STRAWBERRY:8, WOOL:354, FERTILIZER:40 |
| Cow保持r1 | -23861→-23861 | 0→0/0→0/0→0/0→0 | 46.4→36.1 | STRAWBERRY:8, WOOL:30, FERTILIZER:40 → STRAWBERRY:8, FERTILIZER:40 |
| 管理付きSheep | -23861→-20361 | 0→0/0→0/0→0/0→0 | 46.4→46.4 | STRAWBERRY:8, WOOL:30, FERTILIZER:40 → STRAWBERRY:8, WOOL:30, FERTILIZER:40 |
| 管理付きGoose | -23861→-21678 | 0→0/0→0/0→0/0→0 | 46.4→46.4 | STRAWBERRY:8, WOOL:30, FERTILIZER:40 → STRAWBERRY:8, WOOL:30, FERTILIZER:40 |

使用seedは [10091011, 10091012, 10091013, 10091014] のみ。promotion 10091101–10091112、Fresh 10091901–10091912とのoverlapはともに0で、Freshは **SEALED**。先行E3 gateを通る候補がないためE4/E5を開かなかった。予約replay bodyも取得していない。

research archiveとstandalone runtimeはversion別に保存し、Championを変更していない。旧候補のfreeze後に`lifecycle.py`だけを実収穫量のreplay診断用に拡張したが、paired実行coreの`runner.py`/`safety.py`は変えていない。この差はartifact verificationに明記した。新candidateはすべてresearch-onlyで、提出可能な新artifactとして認定しない。既存V111 archiveだけが保全済みChampion artifactである。Kaggle提出は行っていない。

## 何が強くなり、何が未証明か

実際に強くなった新policyはない。強くなったのは評価系で、requested/emitted/engine commit、自然寿命、水切れ、実HARVEST、相手money、Town分岐を分離できるようになった。売却タイミング、late animal choice、管理付き動物はいずれもこのpanelで勝敗改善を示さなかった。

未証明なのは、現在のTop sourceに対するV111の実力、上位artifactのidentity、異なるdecision pointの安全なroute、独立ancestryを増やしたmetaでの効果、E4/E5/E6である。

次の5時間では、V111と30–60%程度で競る独立complete policyを先に取得・再現し、同じDevelopment seedでV111の敗戦状態を増やす。その上で、t248以外の最初の資金制約decision pointについて、元schedule内の二つの完走済みcontinuationを比較する。safe L→Wが複数相手・複数状態に現れるまでselectorやforecastは作らない。見つかった時だけliveで観測可能な1回限りのgateを凍結し、E4後にFreshを一度開く。

## Artifacts

- [Final decision](../experiments/research_20260911_continuations/final_decision.json)
- [Recomputed V114 postmortem](../experiments/research_20260911_continuations/postmortem_recomputed.json)
- [Holdout audit](../experiments/research_20260911_continuations/final_holdout_audit.json)
- [Artifact verification](../experiments/research_20260911_continuations/final_artifact_verification.json)
- [Evaluation data](../data/evaluation/research_20260911_continuations/)
- [Preregistrations](research_20260911_preregistration.md)

## 再現command

以下は凍結済みartifactとDevelopment seedだけを使い、Freshを開かない。

```powershell
./.venv/Scripts/python.exe scripts/research_20260911.py audit
./.venv/Scripts/python.exe scripts/research_20260911.py aa --workers 6
foreach ($version in @('v115p_immediate','v115p_town','v115p_livestock','v115p_retain_cow_r1','v115p_managed_sheep','v115p_managed_goose')) {
    ./.venv/Scripts/python.exe scripts/research_20260911.py paired --version $version --workers 6
}
./.venv/Scripts/python.exe scripts/postmortem_20260911.py
./.venv/Scripts/python.exe scripts/analyze_continuations_20260911.py table
./.venv/Scripts/python.exe scripts/finalize_research_20260912.py
./.venv/Scripts/python.exe -m pytest -q tests/test_continuations_20260911.py
uv run ruff check scripts/research_20260911.py scripts/postmortem_20260911.py scripts/analyze_continuations_20260911.py scripts/external_20260911.py scripts/finalize_research_20260912.py scripts/evaluation/runner.py scripts/evaluation/safety.py scripts/evaluation/lifecycle.py scripts/continuation_option_template.py scripts/livestock_option_template.py scripts/managed_animal_template.py scripts/retain_cow_option_template.py tests/test_continuations_20260911.py
```
