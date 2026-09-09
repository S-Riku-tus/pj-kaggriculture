# V113 Live opponent behavioral-family analysis

## Conclusion

The 58 public live episodes contain 35 quantity-agnostic h200 field-route clusters, but these are Bronze recorded-behavior clusters, not 58 independent executable policies. Exact h719 trajectory hashes are deliberately not counted as policy families.

Only 5 episodes strongly correspond to a local Gold family at h200+, and point to gold_family_21_e9b175a2, public_candidate_addendum_probe:gold_family_01_1f13714f, public_pure_route_probe:gold_family_10_fcc926c5. Another 18 episodes match only through h100 and remain ambiguous shared openings.

The field therefore contains 53 live trajectories and 33 h200 route clusters without strong local-Gold correspondence. They are acquisition leads, not Gold promotions.

## Evidence and identity boundary

- Source evidence is E6 observational; live trajectories are Bronze.
- h24/h100 clusters describe openings; h200 describes early continuation. Numeric quantities are removed.
- A common opening does not imply common code. h100-only matches are not assigned to a Gold family.
- Strong correspondence requires an exact, quantity-preserving recorded-action prefix match through h200 or later.
- Even a strong prefix correspondence does not make the live opponent executable or Gold.

## Prefix-cluster inventory

| View | h24 | h100 | h200 | h400 | h719 |
| --- | --- | --- | --- | --- | --- |
| quantity-agnostic field route | 19 | 22 | 35 | 43 | 51 |
| quantity-agnostic field + market | 22 | 27 | 39 | 57 | 58 |
| exact recorded action prefix | 24 | 28 | 40 | 57 | 58 |

The final row is trajectory identity, not policy identity. In particular, 58 unique h719 hashes do not establish 58 families.

## Strong local Gold correspondence

| Episode | Submission | Result | Margin | Exact through | Gold representative | h200 route cluster |
| --- | --- | --- | --- | --- | --- | --- |
| 104507913 | 55932910 | loss | -1012 | 200 | public_route_v27, public_v27_raw | live_field_route_h200_c05 |
| 104509179 | 55424701 | win | +2160 | 400 | public_v27_raw | live_field_route_h200_c05 |
| 104509628 | 55931220 | win | +83 | 200 | public_route_v27, public_v27_raw | live_field_route_h200_c05 |
| 104514450 | 55800011 | win | +14397 | 200 | public_github_cok_zhangziliang_head | live_field_route_h200_c01 |
| 104520088 | 55909352 | win | +8029 | 200 | public_github_cok_zhangziliang_head | live_field_route_h200_c01 |

These are prefix correspondences to the listed executable artifacts. No live episode exactly matches a common-probe trajectory through h719.

## h100 shared openings

18 episodes match a local executable trajectory through h100 but not h200. These include V43/mainline-style shared openings; their later continuations differ, so they are not local-family matches.

Episodes: 104507842, 104510054, 104512704, 104513571, 104517922, 104519214, 104519654, 104520529, 104521034, 104521384, 104521818, 104523977, 104524436, 104524863, 104525309, 104526676, 104532282, 104536598.

## h200 field-route clusters of interest

| Cluster | N | W-D-L | WR | Mean margin | Loss episodes | Close episodes | 1600+ wins |
| --- | --- | --- | --- | --- | --- | --- | --- |
| live_field_route_h200_c01 | 9 | 9-0-0 | 100.0% | +10260 | - | 104517922 | 104514450,104520088,104523123,104523977 |
| live_field_route_h200_c02 | 6 | 6-0-0 | 100.0% | +5516 | - | 104514016,104515036,104518362 | - |
| live_field_route_h200_c03 | 5 | 1-0-4 | 20.0% | -3220 | 104512704,104521034,104524863,104532282 | 104521034,104536598 | 104536598 |
| live_field_route_h200_c04 | 3 | 3-0-0 | 100.0% | +10407 | - | 104511059 | - |
| live_field_route_h200_c05 | 3 | 2-0-1 | 66.7% | +410 | 104507913 | 104507913,104509179,104509628 | - |
| live_field_route_h200_c06 | 2 | 1-0-1 | 50.0% | -2440 | 104522258 | - | 104554452 |
| live_field_route_h200_c07 | 2 | 2-0-0 | 100.0% | +12247 | - | - | - |
| live_field_route_h200_c08 | 1 | 0-0-1 | 0.0% | -3316 | 104526928 | - | - |
| live_field_route_h200_c12 | 1 | 0-0-1 | 0.0% | -28368 | 104508722 | - | - |
| live_field_route_h200_c13 | 1 | 0-0-1 | 0.0% | -2417 | 104525745 | 104525745 | - |
| live_field_route_h200_c16 | 1 | 0-0-1 | 0.0% | -1099 | 104521818 | 104521818 | - |
| live_field_route_h200_c17 | 1 | 1-0-0 | 100.0% | +1589 | - | 104526676 | 104526676 |
| live_field_route_h200_c18 | 1 | 1-0-0 | 100.0% | +893 | - | 104513137 | - |
| live_field_route_h200_c21 | 1 | 0-0-1 | 0.0% | -13143 | 104513571 | - | - |
| live_field_route_h200_c22 | 1 | 0-0-1 | 0.0% | -15348 | 104516622 | - | - |
| live_field_route_h200_c24 | 1 | 1-0-0 | 100.0% | +22126 | - | - | - |
| live_field_route_h200_c25 | 1 | 1-0-0 | 100.0% | +7779 | - | - | 104526194 |
| live_field_route_h200_c26 | 1 | 0-0-1 | 0.0% | -9708 | 104523554 | - | - |
| live_field_route_h200_c27 | 1 | 1-0-0 | 100.0% | +3299 | - | - | 104525309 |
| live_field_route_h200_c28 | 1 | 1-0-0 | 100.0% | +3487 | - | - | 104549591 |
| live_field_route_h200_c29 | 1 | 1-0-0 | 100.0% | +11998 | - | - | 104536856 |
| live_field_route_h200_c31 | 1 | 1-0-0 | 100.0% | +3519 | - | - | 104521384 |
| live_field_route_h200_c32 | 1 | 1-0-0 | 100.0% | +16616 | - | - | 104522745 |
| live_field_route_h200_c34 | 1 | 1-0-0 | 100.0% | +956 | - | 104515754 | 104515754 |
| live_field_route_h200_c35 | 1 | 0-0-1 | 0.0% | -13812 | 104514883 | - | - |

## Priority episode sets

Losses: 14 episodes across 11 h200 route clusters.

| Episode | Submission | Opponent | Opp rating | Gap | Margin | h200 route | Local correspondence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 104508722 | 55921736 | istinetz | 1186.7 | -24.8 | -28368 | live_field_route_h200_c12 | no_strong_local_gold_correspondence |
| 104516622 | 55925703 | Mohit Babel | 1570.3 | -3.3 | -15348 | live_field_route_h200_c22 | no_strong_local_gold_correspondence |
| 104514883 | 55778582 | vineet dairashri | 1493.2 | -40.3 | -13812 | live_field_route_h200_c35 | no_strong_local_gold_correspondence |
| 104513571 | 55877482 | fvong | 1519.5 | +10.4 | -13143 | live_field_route_h200_c21 | shared_opening_h100_only |
| 104522258 | 55934880 | Dannya AbdulHadi | 1758.9 | +122.5 | -12187 | live_field_route_h200_c06 | no_strong_local_gold_correspondence |
| 104523554 | 55934907 | Michael Shihong Zhang | 1638.1 | -12.8 | -9708 | live_field_route_h200_c26 | no_strong_local_gold_correspondence |
| 104512704 | 55932210 | kurushun | 1592.9 | +88.5 | -6021 | live_field_route_h200_c03 | shared_opening_h100_only |
| 104524863 | 55804049 | Diavolo | 1654.0 | -2.3 | -5581 | live_field_route_h200_c03 | shared_opening_h100_only |
| 104532282 | 55813308 | Rohit Raj Singh | 1681.5 | +23.7 | -5492 | live_field_route_h200_c03 | shared_opening_h100_only |
| 104526928 | 55934129 | Lumberjacks | 1691.5 | +28.1 | -3316 | live_field_route_h200_c08 | no_strong_local_gold_correspondence |
| 104525745 | 55520308 | uri_kkyhr | 1676.5 | +20.5 | -2417 | live_field_route_h200_c13 | no_strong_local_gold_correspondence |
| 104521034 | 55861952 | The Great Alliance | 1651.3 | +7.4 | -1421 | live_field_route_h200_c03 | shared_opening_h100_only |
| 104521818 | 55918910 | Berat Egemen Gök | 1666.7 | +22.7 | -1099 | live_field_route_h200_c16 | shared_opening_h100_only |
| 104507913 | 55932910 | Llin Ding | 1116.6 | -150.4 | -1012 | live_field_route_h200_c05 | strong_h200_plus_gold_correspondence |

Close-margin diagnostic (`|margin| <= 3000`): 15 episodes across 10 h200 route clusters. Episode IDs: 104525745, 104521034, 104521818, 104507913, 104509628, 104514016, 104513137, 104515754, 104517922, 104526676, 104515036, 104511059, 104518362, 104509179, 104536598.

Wins against absolute opponent rating >=1600: 14 across 11 h200 route clusters. Episode IDs: 104515754, 104526676, 104536598, 104525309, 104549591, 104521384, 104554452, 104526194, 104520088, 104523123, 104536856, 104523977, 104514450, 104522745.

Rating-upset wins (opponent at least +100): 2 episodes: 104554452, 104506991.

## Gold-acquisition interpretation

The h200+ correspondences confirm that known executable action families were represented in the live field. The remaining losses, close games, and high-rating wins identify opponent submissions and Bronze h200 clusters to prioritize for public-code discovery. Fingerprint similarity alone cannot promote them to Gold; executable code and common-seed, both-seat probing are still required.

A/B/C gate-cohort and outcome fields are retained per episode and cluster in the JSON. They are descriptive and do not estimate the Cow→Sheep gate's causal effect.
