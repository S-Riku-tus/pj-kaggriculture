# Current state — 2026-09-10

Decision context: the observed leader is **SpaTaro, 3062.4**, at `2026-09-10T07:17:31.459092+00:00`. The target 3000 is therefore a real current competitive tier, not a sufficient condition for first place. This is a timestamped snapshot, not a promise that a live leaderboard remains unchanged. [Official leaderboard](https://www.kaggle.com/competitions/kaggriculture/leaderboard); [saved API response](../data/current_field_20260910/leaderboard.json).

## Champion and repository identity

The frozen **local production Champion is V111**. Branch `main`, initial HEAD `f4d9e35c47bfbe9815bb9c65c998218ccf08d5c0`; `git ls-remote origin refs/heads/main` matched. The initial tracked and untracked status was clean. There is no root `main.py` in local HEAD or GitHub main: this repository uses versioned `agents/<version>/main.py`. Thus a root-file equality claim would be incorrect.

- V111 main SHA256: `699c73f75ec786e9bddcfabb6476fc64c07939f22abe3ed00691a5bef6f72660`.
- V111 archive SHA256: `85ba0176b1774ca1bc45f77601210d847e4bb8c01b550181c3c87bd3f6a1c85e`; all archived source members match local source. A byte-identical control is frozen in `experiments/research_20260910/champion_v111.tar.gz`.
- V113 is a rejected Challenger, not the production Champion. Its historical formal evaluation had 0 Loss→Win and 0 Win→Loss, with two Draw→Win against the clone calibration case and new weed incidents in four pairs. Current V113 source differs from its submitted archive in documentation/diagnostic strings; it is not byte-identical. No previous V114 existed at initial audit.
- **Remote latest submission identity is unresolved.** Our team's latest public submission is `56089444`, submitted September 8, with rating 1347.3 at acquisition; previous `55941525` was 1384.9. Neither has a verified local artifact mapping. Do not label either V111 or V114. Known V111 IDs are `55909167` and `55912910`; their available games end September 1. A fresh download of those games is still historical evidence.

The initial audit inventories `agents`, `artifacts/submissions`, `experiments`, `data/evaluation`, `data/analysis`, `docs`, `scripts/evaluation`, `tests`, environment files, registries and 895 tracked-file hashes. Existing research and Champion files are preserved. [Full initial audit](../experiments/research_20260909/initial_repository_audit.json).

## Engine and access

Installed `kaggle-environments 1.32.7`; Kaggle CLI `2.2.4`; pytest `8.4.2`; Ruff `0.12.12`; NumPy `2.5.2`. The installed Kaggriculture engine SHA256 is `bc8a54879ef02c7ea64b8b333d6a976f0ea65c4949149d01f463f23bccee653e`, exactly matching the downloaded official master engine. [Official engine](https://github.com/Kaggle/kaggle-environments/blob/master/kaggle_environments/envs/kaggriculture/kaggriculture.py); [mechanics probes](../experiments/research_20260909/mechanics_probes.json).

CLI command help and authentication were checked. Authenticated competition access reported `AUTHENTICATION_REQUIRED`; public Kaggle APIs using competition ID **147734** supplied leaderboard, teams and episode metadata/replays. Anonymous notebook source/output calls returned 403; those failures are retained, not interpreted as unavailable private code. Public GitHub archives supplied four executable policies. HTTP 429 responses were retried sequentially with delays, and successful downloads were cached.

There are **720 stored states, 719 decisions (t0–t718)**. The last decision is day 29 hour 22, and the final state is day 29 hour 23. There is no final end-of-day automatic deposit. The score is final coin; shed or carried inventory is not terminal score.

## Leaderboard snapshot

| Rank | Team | Team ID | Submission | Rating | Team last submission age (hours) | API episodes returned |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | SpaTaro | 16640510 | 56114097 | 3062.4 | 26.2 | 148 |
| 2 | Himanshu Kumar | 16657785 | 56122709 | 3021.7 | 12.7 | 135 |
| 3 | Otter Vibe | 16760569 | 56097405 | 2996.6 | 43.7 | 231 |
| 4 | デワンシュ | 16801351 | 56133847 | 2985.8 | 5.4 | 86 |
| 5 | kanno | 16732496 | 56133568 | 2980.5 | 2.7 | 92 |
| 6 | binghua | 16685556 | 56092906 | 2976.7 | 41.5 | 269 |
| 7 | mtmr_s1 | 16758882 | 56125629 | 2970.6 | 16.5 | 132 |
| 8 | feel the agi | 16805699 | 56119872 | 2960.7 | 7.3 | 181 |
| 9 | Yusuke Hayashi | 16681405 | 56136071 | 2954.6 | 4.1 | 74 |
| 10 | Unknown Mother-Goose | 16730612 | 56127667 | 2950.4 | 6.7 | 135 |
| 11 | Mengfei Li | 16622349 | 56047440 | 2945.1 | 98.0 | 566 |
| 12 | pensukesan | 16748173 | 56123692 | 2933.1 | 18.0 | 146 |
| 13 | Squirrel | 16845258 | 56128710 | 2931.6 | 13.3 | 120 |
| 14 | cooked | 16850683 | 56136098 | 2930.1 | 4.0 | 71 |
| 15 | Tarang222 | 16797543 | 56100833 | 2923.7 | 23.7 | 250 |
| 16 | supr3mum | 16683567 | 56128714 | 2923.0 | 13.3 | 115 |
| 17 | lc今天刷了吗 | 16783721 | 56134637 | 2918.8 | 5.6 | 84 |
| 18 | Terry Luo | 16689430 | 56123001 | 2913.1 | 18.5 | 149 |
| 19 | que la cuenten como quieran | 16839530 | 56113029 | 2912.2 | 6.1 | 202 |
| 20 | pupen_o | 16621628 | 56130168 | 2907.6 | 7.9 | 115 |
| 21 | redblackbst | 16732521 | 56130144 | 2906.8 | 5.4 | 117 |
| 22 | Hiro Nomo | 16628951 | 56132841 | 2903.1 | 1.7 | 92 |
| 23 | Max Fofanov | 16661325 | 56130819 | 2903.1 | 10.4 | 101 |
| 24 | Christoffer Thimsen | 16717665 | 56134464 | 2897.5 | 5.8 | 86 |
| 25 | 薄荷喵呜 | 16861637 | 56135054 | 2897.2 | 2.9 | 84 |
| 26 | maco-macoo | 16632566 | 56132252 | 2887.5 | 8.0 | 101 |
| 27 | PeriwinkleBlueOvO | 16820607 | 56122079 | 2886.5 | 19.2 | 147 |
| 28 | Agricola | 16727266 | 56114889 | 2881.9 | 8.1 | 183 |
| 29 | Sean Peppers | 16841108 | 56133866 | 2881.5 | 6.5 | 92 |
| 30 | MartinZiserman | 16847763 | 56123686 | 2869.3 | 8.3 | 141 |

Age is the team's last submission timestamp, not a verified source build age. Returned episode counts can be an API window rather than lifetime counts. Full rating distribution: N=8474, quantiles `{"0": -213.1, "0.1": 282.4, "0.25": 471.5, "0.5": 799.2, "0.75": 1477.4, "0.9": 2302.6, "0.99": 2793.7, "1": 3062.4}`. The complete leaderboard is in the raw response.

## Current gap and evidence boundary

V111 has three coherent route backbones and very little midseason new-crop choice. During days 15–24 all planned new planting in all three backbones is Wheat (69/72/70 actions). Current top replays show a common opening cluster but material alternative continuations, including Carrot exposure at rank 1 and Tomato/Goose at rank 3. These are mechanistic research leads, not proof that copying their asset counts wins.

New full-source opponents exposed a large gap: on four discovery seeds and both seats V111 scored **10W/0D/22L**, versus mooman 0/0/8, souvik 2/0/6, ggmljs 8/0/0, qeinstein 0/0/8. The first three share source ancestry; four executable policies are at most two conservatively merged broad ancestry groups. These results are not a calibrated Kaggle rating.

No current evidence supports calling V111 a 2500-class or 3000 contender. Historical V111 games mostly concern the older ~1500 field, the latest unmapped submission is 1347.3, and V111 loses heavily to newly acquired public policies. A provisional **older ~1600-class baseline** is defensible only as historical context; its exact current rating is unmeasured.

Discovery, development, promotion and fresh seeds are separately registered. New replay holdout entries contain public metadata (including outcomes) but their replay bodies were not downloaded; they are not completely blind metadata. The genuinely unused simulation seeds remain sealed unless all prior gates pass. Existing evaluation seeds are development data. [Frozen registry](../experiments/research_20260910/source_registry.json).
