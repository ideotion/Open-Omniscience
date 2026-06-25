# TimesFM Reliability & the Time-Series Foundation Model Landscape

**Prepared:** 19 June 2026 · **Subject:** Google Research TimesFM (1.x / 2.0-500M / 2.5-200M) and competing pretrained time-series forecasting models
**Method:** primary sources prioritised (papers, official repos, HF model cards, the Salesforce GIFT-Eval leaderboard). Every source carries its publication/update date. Vendor self-reported benchmarks are treated as point-in-time marketing and cross-checked against the neutral leaderboard wherever possible.

> **Read this first — the single most important caveat.** This field turns over roughly every two quarters. A "#1 on GIFT-Eval" claim is only true on the day it is published. TimesFM-2.5 genuinely led the GIFT-Eval zero-shot board when it shipped in September 2025; nine months later it sits mid-pack among foundation models. Treat *every* ranking below as a dated snapshot, not a durable fact.

---

## Part 1 — How reliable is TimesFM?

### The neutral anchor: where TimesFM actually stands today

The least-conflicted yardstick is the Salesforce **GIFT-Eval** leaderboard — 97 task configurations drawn from 55 datasets across 7 domains and 10 frequencies, with a deliberately non-leaking ~230B-point pretraining set provided so foundation models can be trained without contaminating the test split ([GIFT-Eval paper, arXiv 2410.10393, 11 Nov 2024](https://arxiv.org/abs/2410.10393); [official leaderboard, HF Spaces](https://huggingface.co/spaces/Salesforce/GIFT-Eval)). Models are ranked by **average MASE rank** (point accuracy) and **average CRPS/WQL rank** (probabilistic accuracy) across all slices; lower is better.

![GIFT-Eval standings for TimesFM versions vs other foundation models and classical baselines, snapshot 18 June 2026](gift_eval_standings.png)

Reading from a mirror of the official board refreshed **18 June 2026** ([tsfm.ai GIFT-Eval mirror, snapshot 18 Jun 2026](https://tsfm.ai/benchmarks/gift-eval)):

- **TimesFM-2.5** average MASE rank ≈ **32.1**, behind Toto-2.0-2.5B (≈25.4), Toto-2.0-1B (≈26.7), Chronos-2 (≈28.3) and Timer-S1 (≈31.6), and just ahead of TiRex (≈35.3) ([tsfm.ai mirror, 18 Jun 2026](https://tsfm.ai/benchmarks/gift-eval)).
- **TimesFM-2.0-500M** ≈ **49.5**; **TimesFM-1.0-200M** ≈ **70.3** (the 1.0 model now ranks *below* Auto-ARIMA at ≈75.0 only marginally, and is essentially in classical-baseline territory) ([tsfm.ai mirror, 18 Jun 2026](https://tsfm.ai/benchmarks/gift-eval)).
- For context, the very top of the public board is occupied by **agentic / ensemble / fine-tuned** systems (e.g. the "Toto-2.0 Family-and-Friends" ensemble and Toto-2.0-2.5B-FT) and a few **leakage-flagged** entries — none of which are like-for-like zero-shot single models, so they are excluded from the chart above ([tsfm.ai mirror, 18 Jun 2026](https://tsfm.ai/benchmarks/gift-eval)).

So the honest headline is: **TimesFM-2.5 is a strong, top-tier-but-no-longer-leading zero-shot foundation model on the one benchmark explicitly engineered to be contamination-resistant.** The "state of the art" framing in Google's launch materials ([MarkTechPost, 16 Sep 2025](https://www.marktechpost.com/2025/09/16/google-ai-ships-timesfm-2-5-smaller-longer-context-foundation-model-that-now-leads-gift-eval-zero-shot-forecasting/)) was accurate *at launch* and is now stale.

### Axis 1 — Accuracy (zero-shot and fine-tuned)

**Zero-shot, GIFT-Eval (neutral):** ranks above. TimesFM-2.5 is competitive on both the MASE (point) and CRPS (probabilistic) axes but is no longer first ([tsfm.ai mirror, 18 Jun 2026](https://tsfm.ai/benchmarks/gift-eval)). When Chronos-2 was published (Oct 2025) its authors reported beating both TimesFM-2.5 and TiRex on GIFT-Eval win-rate and skill score for WQL and MASE, with a pretraining corpus de-overlapped from every GIFT-Eval test slice ([Chronos-2, arXiv 2510.15821, 17 Oct 2025](https://arxiv.org/abs/2510.15821)). The Toto-2.0 report (May 2026) similarly places its three largest sizes ahead of external foundation models on GIFT-Eval ([Datadog "Toto 2.0", 14 May 2026](https://www.datadoghq.com/blog/ai/toto-2/)).

**Monash archive (the original ICML-2024 evidence):** in pure zero-shot mode, TimesFM-1.0 was shown to beat most statistical models (ARIMA, ETS) and match or exceed several supervised deep-learning baselines trained per-series, using scaled-MAE and geometric-mean aggregates ([TimesFM paper summary, aimultiple, 10 Feb 2026](https://research.aimultiple.com/time-series-foundation-models/); [ICML 2024 paper, OpenReview](https://openreview.net/forum?id=jn2iTJas6h)). **Caveat:** Monash is now considered heavily contaminated for cross-model comparison (see Axis 3), so these numbers should not be read as a clean ranking.

**Long-horizon (ETT / LSF):** the original paper reported TimesFM zero-shot rivalling per-dataset-trained PatchTST on ETT-style long-horizon tasks ([aimultiple, 10 Feb 2026](https://research.aimultiple.com/time-series-foundation-models/)). An independent 2026 operational study found TimesFM-2.0 **beat every baseline on the Traffic dataset (MASE 0.482)**, and that TimesFM-2.5 and Chronos beat all supervised deep-learning baselines zero-shot on periodic/seasonal data — but the same study found **specialist models still win on physically-constrained data** (XGBoost MASE 0.573 vs best foundation model 1.046 on Energy) ([Operational Viability study, arXiv 2605.24381, ~May 2026](https://arxiv.org/html/2605.24381)).

**Concrete metrics, honestly:** GIFT-Eval's public headline is an *aggregate rank* plus normalised MASE/CRPS (geometric mean over 97 configs, normalised so seasonal-naive ≈ 1.0). Exact normalised values shift with every new submission, so the **rank** is the more stable cross-model number; the per-dataset MASE figures above (Traffic 0.482; Energy FM 1.046 vs XGBoost 0.573) are the most concrete independent point estimates available.

**Fine-tuning:** TimesFM supports parameter-efficient fine-tuning (LoRA/PEFT). A worked finance example kept trainable parameters under ~100K via LoRA adapters specifically to limit over-fitting on non-stationary data ([MQL5 TimesFM-2.5 + MetaTrader, 21 Apr 2026](https://www.mql5.com/en/articles/22096)). In process-mining benchmarks, zero-shot TSFMs cut MAE/RMSE 15–30% vs seasonal-naive/XGBoost, but **LoRA fine-tuning added only 1–5%, and sometimes hurt on small/sparse data** ([Time Series Foundation Models survey topic, emergentmind, 19 Dec 2025](https://www.emergentmind.com/topics/time-series-foundation-models)). Net: fine-tuning helps modestly and is not a reliability cure-all.

### Axis 2 — Independent reproduction & contradicting evaluations

- **Independent re-runs exist and broadly hold.** GIFT-Eval results for TimesFM are produced by Salesforce's harness (independent of Google) with public replication notebooks ([tsfm.ai mirror, 18 Jun 2026](https://tsfm.ai/benchmarks/gift-eval)). Independent academic and vendor evaluations (onTime, the operational-viability study, the Moirai-2 and Chronos-2 papers' baseline tables) reproduce TimesFM in the same competitive band ([onTime benchmark, MDPI, 8 Sep 2025](https://www.mdpi.com/2813-0324/11/1/32); [Operational Viability, ~May 2026](https://arxiv.org/html/2605.24381); [Moirai 2.0, arXiv 2511.11698, v1 12 Nov 2025](https://arxiv.org/html/2511.11698v1)).
- **Contradicting / deflating evaluations.** On short-history regimes (yearly/quarterly Monash sets), foundation models including TimesFM can be beaten by simple statistical ensembles — e.g. Chronos-1 was outperformed by a Statistical Ensemble on key Monash datasets, and the same caution applies to TimesFM ([AI Horizon Forecast deep dive, 3 May 2026](https://aihorizonforecast.substack.com/p/time-series-foundation-models-a-deep)). A bankruptcy-prediction study found classical ML consistently beat foundation/LLM approaches across horizons ([Are Foundation Models Useful for Bankruptcy Prediction?, arXiv 2511.16375](https://arxiv.org/pdf/2511.16375)).

### Axis 3 — Train/test contamination & leakage

This is the field's biggest reliability problem, and it is **not specific to TimesFM** — but TimesFM is named repeatedly in the leakage literature.

- A dataset-lineage audit of 22 published TSFMs found **no community consensus on train vs eval splits — one model's pretraining corpus is another's test set** — and identifies both *direct* leakage (multi-purpose dataset reuse) and *indirect* leakage (temporal overlap from shared causal drivers like COVID). It singles out the Monash Australian Electricity Demand set as used for pretraining (Lag-Llama, Timer), train/test (Moirai) **and** zero-shot (Chronos, TimesFM) — "practically useless for cross-model comparison" — and ETTh1/h2/m1 as similarly compromised ([Rethinking Evaluation: (Un)known Information Leakage, arXiv 2510.13654, HTML 25 Feb 2026](https://arxiv.org/html/2510.13654)).
- A benchmarking-requirements paper quantifies the damage: when evaluation sets leaked into pretraining (it names a benchmark that inadvertently included three sets already in TimesFM/UniTS/TTM pretraining), leaking models showed **47%–184% lower MSE**, versus only **0.3%–14%** advantage on non-leaked sets — i.e. most of the apparent "win" was memorisation, and larger models leaked harder ([TSFM Benchmarking Challenges & Requirements, ResearchGate, 7 May 2026](https://www.researchgate.net/publication/396517573_Time_Series_Foundation_Models_Benchmarking_Challenges_and_Requirements)).
- A dedicated contamination-auditing framework probed several models and, notably, found **TimesFM-2.0 did not show a stable contamination signal** under its references (neither strongly implicated nor exonerated) ([TSFMAudit, arXiv 2605.26161, ~May 2026](https://arxiv.org/html/2605.26161)).

**How TimesFM specifically addresses it:** TimesFM-2.5's model card lists its pretraining sources as **GIFT-Eval-Pretrain (the non-leaking set), Wikimedia pageviews (through Nov 2023), Google Trends (through end-2022), plus synthetic/augmented data** ([tsfm.ai TimesFM-2.5 model page, 17 Dec 2025](https://tsfm.ai/models/google/timesfm-2.5-200m-pytorch)). Because it trains on GIFT-Eval-Pretrain rather than the test split, **its GIFT-Eval result is comparatively clean** — which is exactly why GIFT-Eval (not Monash/ETT) is the right board to judge it on. Its results on Monash/ETT, by contrast, should be discounted for leakage.

### Axis 4 — Known failure modes & limitations

Drawn from independent studies *and* candid vendor admissions:

- **Very short history.** Yearly/quarterly/monthly series with tiny histories (e.g. Monash M1-yearly: ~15 points, horizon 6) are a known weak spot; always compare against naive/seasonal-naive/statistical baselines there ([AI Horizon Forecast, 3 May 2026](https://aihorizonforecast.substack.com/p/time-series-foundation-models-a-deep)).
- **Long horizons.** Foundation models lose structure at extreme horizons where a properly-fitted seasonal model extrapolates cleanly — Datadog reports even a 2.5B model degrading at 8,192 steps ([Datadog "Toto 2.0", 14 May 2026](https://www.datadoghq.com/blog/ai/toto-2/)). The Moirai-2 authors likewise report accuracy **declining at longer horizons** and plateauing with parameter count ([Moirai 2.0, arXiv 2511.11698, 3 Feb 2026](https://arxiv.org/abs/2511.11698)).
- **Regime shifts / out-of-distribution / non-stationarity.** Failure modes the class exhibits that classical models do not: drift, mode collapse, and structural breakdown past training context ([Datadog "Toto 2.0", 14 May 2026](https://www.datadoghq.com/blog/ai/toto-2/)). Interestingly, model rankings flip with stationarity — on a contamination-resistant benchmark, **Chronos-2 dominates stationary series but TimesFM-2.5 overtakes it on non-stationary series**, suggesting TimesFM's inductive bias is comparatively favourable for regime change ([It's TIME benchmark, arXiv 2602.12147, HTML v3 4 Mar 2026](https://arxiv.org/html/2602.12147v3)).
- **Financial / heavy-tailed data.** TimesFM's patched decoder handles business-calendar gaps without architecture changes, but its quantile heads must be aligned to risk measures (VaR/ES) and it is not purpose-built for tail fidelity ([TSFM-in-Finance survey, ACM DL, 1145/3785706.3785728](https://dl.acm.org/doi/full/10.1145/3785706.3785728)). Markets are non-stationary and data-scarce (~252 trading days/yr), so practitioners fine-tune with heavy regularisation rather than trust zero-shot ([MQL5, 21 Apr 2026](https://www.mql5.com/en/articles/22096)).
- **Exogenous shocks.** Not separately reliable — covered by the regime-shift / OOD failure modes above.

### Axis 5 — Probabilistic quality (is the uncertainty calibrated?)

TimesFM-2.5 adds an **optional ~30M-parameter continuous quantile head** (q10–q90 etc.); covariate-aware quantiles returned alongside point forecasts ([Pixels & Pulse architecture review, 31 Mar 2026](https://thepixelspulse.com/posts/google-timesfm-2-5-production-architecture/); [tsfm.ai model page, 17 Dec 2025](https://tsfm.ai/models/google/timesfm-2.5-200m-pytorch)). It now reports a top-tier **CRPS** rank on GIFT-Eval as well as MASE ([MarkTechPost, 16 Sep 2025](https://www.marktechpost.com/2025/09/16/google-ai-ships-timesfm-2-5-smaller-longer-context-foundation-model-that-now-leads-gift-eval-zero-shot-forecasting/)), so it is *not* merely "point-good, interval-bad" in aggregate.

**However**, the cross-cutting finding for the whole class is that **interval calibration degrades with horizon** in a way classical methods avoid — "calibrated uncertainty that doesn't degrade with horizon" is listed as a property foundation models *lack* ([Datadog "Toto 2.0", 14 May 2026](https://www.datadoghq.com/blog/ai/toto-2/)). For genuinely uncertainty-critical use, models built around quantile/flow objectives end-to-end (Chronos-2, Moirai-2, Toto-2.0, Sundial, TiRex) are designed for this from the ground up, whereas TimesFM's quantile head is an add-on. **Direct, independent calibration curves for TimesFM-2.5's quantile head are sparse in the literature** — see the low-confidence list.

### Axis 6 — Operational reliability

- **Inference cost / latency / hardware.** All foundation models carry a "throughput gap": an independent study clocked the three tested foundation models at **200–1,764 ms/forecast on GPU**, while every supervised baseline ran **<120 ms on CPU** (DLinear 0.13 ms, PatchTST 9.03 ms). TimesFM-2.5 was **faster than 2.0** thanks to the halved parameter count, while T5-based Chronos was slowest due to autoregressive tokenisation ([Operational Viability, arXiv 2605.24381, ~May 2026](https://arxiv.org/html/2605.24381)). The 16k context is powerful but is itself a latency bottleneck for real-time use ([Pixels & Pulse, 31 Mar 2026](https://thepixelspulse.com/posts/google-timesfm-2-5-production-architecture/)).
- **Version churn / breaking changes (2.0 → 2.5).** This is real. 2.5 unifies the previously-split JAX/PyTorch code into `src/timesfm/timesfm_2p5/`, archiving 1.0/2.0 under `v1/` ([DeepWiki v1 archive, 13 May 2026](https://deepwiki.com/google-research/timesfm/7.1-v1-archive-(timesfm-1.0-and-2.0))); it changes parameter count (500M→200M), context (2048→16,384), adds rotary attention, QK-norm, per-dimension attention scaling and QKV fusion, and drops the frequency-indicator input ([HF transformers TimesFM-2.5 docs, 27 Feb 2026](https://huggingface.co/docs/transformers/model_doc/timesfm2_5); [tsfm.ai model page, 17 Dec 2025](https://tsfm.ai/models/google/timesfm-2.5-200m-pytorch)). Expect to rewrite integration code when moving versions.
- **Covariate (XReg) maturity.** 2.5 launched *without* covariate support; **XReg covariate support was re-added in an October 2025 update** ([Pixels & Pulse, 31 Mar 2026](https://thepixelspulse.com/posts/google-timesfm-2-5-production-architecture/)). It is functional but newer/less battle-tested than, say, Chronos-2's native covariate path.
- **Fine-tuning (LoRA/PEFT) stability.** Works, with the modest gains and small-data fragility noted in Axis 1; practitioners deliberately cap LoRA rank to avoid over-fitting non-stationary data ([MQL5, 21 Apr 2026](https://www.mql5.com/en/articles/22096)).

### Part 1 verdict — blunt

**Where TimesFM is trustworthy:**
- **General zero-shot point forecasting on data with real seasonal/trend structure** (traffic, energy demand profiles, web/retail demand with weekly/daily cycles). It is a genuine top-tier model on the contamination-resistant GIFT-Eval board, fully open (Apache-2.0), small (200M), fast relative to its peers, and easy to deploy.
- **Non-stationary / regime-changing data**, where its inductive bias compares *favourably* to several peers ([It's TIME, 4 Mar 2026](https://arxiv.org/html/2602.12147v3)).
- **As a strong default baseline** that you can stand up in minutes before investing in a specialist model.

**Where it is not — do NOT rely on it for:**
- **Tight, horizon-stable uncertainty quantification** (risk limits, safety stock at a guaranteed service level). The quantile head is an add-on and class-wide interval calibration degrades with horizon ([Datadog, 14 May 2026](https://www.datadoghq.com/blog/ai/toto-2/)). Use a quantile/flow-native model and back-test coverage.
- **Very long horizons** (thousands of steps) — fit a seasonal/ETS model instead ([Datadog, 14 May 2026](https://www.datadoghq.com/blog/ai/toto-2/)).
- **Very short histories** (yearly/quarterly with a handful of points) — seasonal-naive / AutoARIMA / statistical ensembles often win ([AI Horizon Forecast, 3 May 2026](https://aihorizonforecast.substack.com/p/time-series-foundation-models-a-deep)).
- **Physically-constrained, data-rich domains** where a tuned XGBoost/PatchTST specialist exists (e.g. plant energy) — specialists still win materially ([Operational Viability, ~May 2026](https://arxiv.org/html/2605.24381)).
- **Heavy-tailed financial trading signals zero-shot** — only with heavy-regularised fine-tuning and risk-aligned quantiles, and even then with scepticism ([TSFM-in-Finance survey](https://dl.acm.org/doi/full/10.1145/3785706.3785728)).
- **Real-time / sub-100 ms paths** on CPU — the throughput gap is structural ([Operational Viability, ~May 2026](https://arxiv.org/html/2605.24381)).
- **Any leaderboard claim from a vendor at face value**, including Google's own "#1" — verify against the dated neutral board.

---

## Part 2 — Competing / equivalent technologies

![Release cadence of major time-series foundation models, 2024–2026, with TimesFM highlighted](tsfm_timeline.png)

**How to read the "GIFT-Eval rank" column:** average MASE rank from the [tsfm.ai mirror of the Salesforce board, snapshot 18 Jun 2026](https://tsfm.ai/benchmarks/gift-eval) (lower = better; ~94 entries total). Where a model isn't on the board (closed-source), that's noted. Ranks mix model sizes; I cite a representative checkpoint.

| Model | Developer · latest update | Architecture | Params / context / horizon | Prob? · Covariates? · Multivariate-native? | GIFT-Eval rank (18 Jun 2026) | License · access |
|---|---|---|---|---|---|---|
| **TimesFM 2.5** *(subject)* | Google Research · Sep 2025 (XReg Oct 2025) | Decoder-only, patched; rotary attn, QK-norm | 200M · 16,384 · ~1k | Yes (opt. 30M quantile head) · Yes (XReg) · No (univariate+cov) | ~32 | Apache-2.0 · HF / GitHub / BigQuery |
| **Chronos-2** | Amazon · Oct 2025 | Encoder-only (T5-enc), patched, group attention / ICL | 120M · long · multi-step | Yes (quantiles) · **Yes (native, zero-shot)** · **Yes (native)** | ~22 | Apache-2.0 · HF / SageMaker / AutoGluon |
| **Chronos-1 / Chronos-Bolt** | Amazon · 2024 | Enc-dec (T5), value tokenisation / Bolt patched | 9M–710M · 512 · multi | Yes (sampled) · via ext. regressor · No | ~48 (Bolt-base) / ~63 (C-large) | Apache-2.0 · HF / AutoGluon |
| **Toto 2.0** | Datadog · Apr 2026 | Decoder-only, alternating time/variate attn, u-μP | 4M–2.5B · variable · multi | Yes (quantiles) · planned (use 1.0) · **Yes (native)** | ~13 (2.5B) / ~26 (1B) | Apache-2.0 · HF / GitHub / GluonTS |
| **Toto 1.0** | Datadog · May 2025 (FT+cov Feb 2026) | Decoder-only, time/variate attn | 151M · variable · multi | Yes · **Yes (FT)** · **Yes** | ~48 | Apache-2.0 · HF / GitHub |
| **Timer-S1** | ByteDance + Tsinghua · Mar 2026 | Decoder-only **MoE** + serial-token prediction | 8.3B total / 0.75B active · 11.5k · long | Limited · — · partial | ~28 | (research/open weights) · HF |
| **TiRex** | NXAI (Hochreiter) · May 2025 | **xLSTM** (recurrent), in-context | 35M · long+short · both | Yes (quantiles) · — · No | ~32–35 | **NXAI community license** (not fully permissive) · HF |
| **Moirai 2.0** | Salesforce · Aug–Nov 2025 | Decoder-only, quantile loss, multi-token | small (R-small) · long · multi | Yes (quantiles) · Yes · **Yes (any-variate)** | ~45 | **CC-BY-NC-4.0** (non-commercial) · HF |
| **Moirai 1.x / Moirai-MoE** | Salesforce · 2024 | Encoder-only masked, any-variate attn; MoE variant | 14M/91M/311M · ~5k · multi | Yes (mixture dist.) · Yes · **Yes (any-variate)** | ~61–72 | **CC-BY-NC-4.0** · HF |
| **Sundial** | Tsinghua (THUML) · Feb 2025 | Decoder-only, **flow-matching** generative (no tokenisation) | 128M · long · multi | **Yes (generative)** · — · Yes | ~51 | Apache-2.0 (typical THUML) · HF |
| **Time-MoE** | Princeton/Griffith et al. · Sep 2024 (ICLR'25) | Decoder-only **MoE**, point-wise tokens | up to 2.4B (sparse) · 4,096 · any | Mostly point · — · No | not on board (line continued by Timer-S1) | Apache-2.0 (code) / CC-BY-4.0 · HF |
| **TimeGPT-1 / TimeGEN-1** | Nixtla · 2023–ongoing | Encoder-decoder transformer | undisclosed · large · multi | Yes (conformal) · Yes · partial | **not on board (closed)** | **Proprietary, API-only** (+ Azure / paid self-host) |
| **MOMENT** | CMU AutonLab · May 2024 (ICML'24) | **Encoder-only (T5-enc)**, masked reconstruction | 40M/125M/385M · 512 · — | weak zero-shot · — · channel-indep | low (forecasting weak) | Apache-2.0 / MIT · HF |
| **Lag-Llama** | ServiceNow/Mila/Morgan Stanley · 2023–24 | Decoder-only (LLaMA), lag features | small (single-digit–tens of M) · — · — | **Yes (Student-t)** · lags only · No | ~84 (**below seasonal-naive**) | Apache-2.0 · HF |
| **Granite TTM (Tiny Time Mixers)** | IBM · 2024 (R2/R3) | **Non-transformer**, TSMixer/MLP-Mixer | ~1M–5M+ · short · multi | mostly point · **Yes (FT, future-known)** · **Yes (channel-mixing)** | ~38–84 (FT vs PT) | Apache-2.0 (enterprise weights) · HF |
| **IBM FlowState** | IBM · 2025 | **SSM encoder + functional-basis decoder**, timescale-invariant | ~9M · continuous-rate · long | Yes · — · partial | ~27–32 | Apache-2.0 · HF |
| *Newer notables:* **YingLong** (Alibaba) | 2025 | transformer | 6M–300M | — | ~55–68 | open · HF |
| **TabPFN-TS** (PriorLabs) | 2024–25 | tabular-PFN adapted to TS | — | Yes · **Yes (covariates)** · — | ~57 | open · HF |
| **Kairos** (ShanghaiTech) | 2025 | Enc-dec, dynamic patching + adaptive RoPE | 10M/23M/50M | — | ~43–47 | open · HF |

*(Architecture/size facts above are drawn from each model's primary source, cited in the per-model notes that follow.)*

### Per-model notes — and how each compares to TimesFM

**Chronos-2 (Amazon).** 120M encoder-only model (T5-encoder lineage) that uses patching + a *group-attention* mechanism to do in-context learning across related series, variates and covariates — making it univariate, multivariate **and** covariate-informed in one zero-shot model, trained on real + synthetic data with the pretraining corpus de-overlapped from GIFT-Eval ([Chronos-2, arXiv 2510.15821, 17 Oct 2025](https://arxiv.org/abs/2510.15821); [HF amazon/chronos-2, 17 Oct 2025](https://huggingface.co/amazon/chronos-2)). Fast (>300 forecasts/s on an A10G; ~478 MB on disk; runs on CPU) ([Amazon Science, Oct 2025](https://www.amazon.science/blog/introducing-chronos-2-from-univariate-to-universal-forecasting); [Towards Data Science, ~Jun 2026](https://towardsdatascience.com/five-questions-about-chronos-2-the-time-series-foundation-model/)). **vs TimesFM:** *beats* TimesFM-2.5 on GIFT-Eval at publication and is far stronger for **covariate-heavy and multivariate** work (TimesFM's covariate path is a newer add-on); roughly comparable openness (Apache-2.0). On *non-stationary* data TimesFM-2.5 has been shown to edge ahead ([It's TIME, 4 Mar 2026](https://arxiv.org/html/2602.12147v3)). Today Chronos-2 ranks above TimesFM-2.5 on the neutral board (~22 vs ~32).

**Chronos-1 / Chronos-Bolt (Amazon).** The original casts forecasting as language modelling via value scaling+quantisation over a T5 backbone (20M–710M); Chronos-Bolt is the patch-based, direct-multi-step, much faster variant ([chronos-forecasting GitHub](https://github.com/amazon-science/chronos-forecasting)). **vs TimesFM:** older generation; Bolt-base (~48) and Chronos-large (~63) both trail TimesFM-2.5; autoregressive Chronos-1 is the slowest foundation model tested ([Operational Viability, ~May 2026](https://arxiv.org/html/2605.24381)). Superseded by Chronos-2.

**Toto / Toto 2.0 (Datadog).** Decoder-only with alternating *time-axis and variate-axis* attention, multivariate-native, observability-focused; Toto 2.0 is a u-μP-scaled family from 4M to 2.5B trained from a single recipe, with forecast quality improving monotonically with scale ([Toto, arXiv 2505.14766, May 2025](https://arxiv.org/abs/2505.14766); [Datadog "Toto 2.0", 14 May 2026](https://www.datadoghq.com/blog/ai/toto-2/)). Crucially for trust, **Toto 2.0's base models are pretrained on *no* public time-series data** (only Datadog telemetry + synthetic; public data enters only at fine-tuning), making its public-benchmark numbers a genuine cross-domain generalisation test ([Toto 2.0, arXiv 2605.20119, ~May 2026](https://arxiv.org/html/2605.20119v1)). It tops BOOM, leads foundation models on GIFT-Eval, and is #1 on the contamination-resistant TIME benchmark ([Datadog, 14 May 2026](https://www.datadoghq.com/blog/ai/toto-2/)). **vs TimesFM:** Toto-2.0 (2.5B/1B) currently **outranks TimesFM-2.5** on GIFT-Eval (~13/26 vs ~32) and is the strongest *open* (Apache-2.0) model on the board; but Toto 2.0 lacks fine-tuning and exogenous-variable support today (use Toto 1.0 for those) ([datadog/toto GitHub](https://github.com/datadog/toto)), whereas TimesFM has both. Toto is heavier at the top end (2.5B vs 200M).

**Timer-S1 (ByteDance + Tsinghua).** A billion-scale sparse-MoE (8.3B total, 0.75B active) decoder with an 11.5k context and a "serial-token prediction" objective to cut long-horizon error accumulation; trained on the ~1-trillion-point TimeBench corpus ([Timer-S1, arXiv 2603.04791, Mar 2026](https://arxiv.org/abs/2603.04791); [HF bytedance-research/Timer-S1](https://huggingface.co/bytedance-research/Timer-S1)). **vs TimesFM:** ranks slightly *above* TimesFM-2.5 (~28) and is explicitly stronger at medium/long horizons; far larger and heavier to serve.

**TiRex (NXAI).** A 35M **xLSTM** (recurrent, state-tracking) model — a deliberate bet that recurrence beats transformers for time series — with quantile output and strong short *and* long horizon results; it briefly led GIFT-Eval in mid-2025 ([TiRex, arXiv 2505.23719, NeurIPS 2025](https://arxiv.org/abs/2505.23719); [NX-AI/TiRex HF](https://huggingface.co/NX-AI/TiRex)). Edge-deployable down to PLCs. **vs TimesFM:** comparable rank today (~32–35), much smaller, but its **NXAI community licence is not fully permissive** — a real constraint vs TimesFM's Apache-2.0.

**Moirai 2.0 / Moirai 1.x / Moirai-MoE (Salesforce).** Moirai 1.x is an encoder-only masked model with "any-variate" attention (true multivariate + covariates, mixture-distribution output); Moirai-MoE adds sparse experts; **Moirai 2.0 switched to a decoder-only architecture with quantile loss and multi-token prediction**, trained on a 36M-series corpus, and is ~30× smaller / 2× faster than Moirai-1.0-large ([Moirai 2.0, arXiv 2511.11698, v3 3 Feb 2026](https://arxiv.org/abs/2511.11698); [Salesforce blog, 13 Aug 2025](https://www.salesforce.com/blog/moirai-2-0/)). The authors candidly report performance plateauing with size and **declining at long horizons** ([arXiv 2511.11698](https://arxiv.org/abs/2511.11698)). **vs TimesFM:** Moirai's headline strength is **native multivariate + covariates**; but Moirai 2.0 ranks *below* TimesFM-2.5 on the current board (~45 vs ~32), and — decisively for many users — **all Moirai weights are CC-BY-NC-4.0 (non-commercial)**: you cannot self-host them in a revenue product without a Salesforce licence ([Spheron deployment guide, 11 May 2026](https://www.spheron.network/blog/deploy-time-series-foundation-models-gpu-cloud/)). TimesFM's Apache-2.0 is a major practical advantage here.

**Sundial (Tsinghua).** Decoder-only **generative** model using flow-matching ("TimeFlow Loss") to model a continuous next-patch distribution without discrete tokenisation, pretrained on ~1T points; generating more samples yields better-calibrated intervals ([Sundial, arXiv 2502.00816, ICML 2025](https://arxiv.org/pdf/2502.00816)). **vs TimesFM:** philosophically the *probabilistic-native* counterpoint; ranks below TimesFM-2.5 on point MASE (~51) but is attractive when you want sampled predictive distributions rather than fixed quantiles.

**Time-MoE.** First TSFM scaled to 2.4B via sparse MoE (decoder-only, point-wise tokens, any horizon, 4,096 context) at ICLR-2025 ([Time-MoE, arXiv 2409.16040, ICLR 2025 Spotlight](https://arxiv.org/abs/2409.16040)). **vs TimesFM:** an efficiency/scaling milestone, mostly point-forecast and univariate; its lineage now lives on in Timer-S1, which is what actually appears on the leaderboard.

**TimeGPT-1 (Nixtla).** Encoder-decoder transformer trained on 100B+ points; production-ready with anomaly detection, exogenous variables and conformal-prediction intervals — but **closed source, accessed via API / Azure (TimeGEN-1) / paid self-host** ([Nixtla README — "TimeGPT is closed source"](https://github.com/Nixtla/nixtla/blob/main/README.md); [TimeGPT-1, arXiv 2310.03589, 2023]). **vs TimesFM:** the opposite of TimesFM on openness. It cannot be independently placed on GIFT-Eval (closed), so its accuracy claims are vendor-self-reported and not neutrally verifiable; academic studies routinely exclude it for inaccessibility ([TimeRAF, arXiv 2412.20810](https://arxiv.org/pdf/2412.20810)). Choose it for a managed, low-ops API; avoid it if you need auditability or self-hosting.

**MOMENT (CMU).** Encoder-only T5 pretrained by masked reconstruction; a *general* time-series model (forecasting, classification, anomaly detection, imputation) that **relies on fine-tuning / linear probing for forecasting** rather than strong zero-shot ([MOMENT, arXiv 2402.03885, ICML 2024](https://arxiv.org/pdf/2402.03885); [TFMAdapter, arXiv 2509.13906](https://arxiv.org/pdf/2509.13906)). **vs TimesFM:** weaker as a zero-shot *forecaster*; more useful as a representation backbone for multi-task time-series work.

**Lag-Llama (ServiceNow/Mila/Morgan Stanley).** Early open *probabilistic* decoder (LLaMA backbone, lag features, Student-t head); univariate ([Lag-Llama, arXiv 2310.08278, 2023–24]; [IBM tutorial, 19 Nov 2025](https://www.ibm.com/think/tutorials/lag-llama)). **vs TimesFM:** now clearly outclassed — it sits at GIFT-Eval rank ~84, **below seasonal-naive** ([tsfm.ai mirror, 18 Jun 2026](https://tsfm.ai/benchmarks/gift-eval)). Its remaining appeal is pedagogical and that its LLaMA architecture makes LoRA/PEFT trivial.

**Granite TTM / Tiny Time Mixers (IBM).** Deliberately tiny (~1M+) **non-transformer** TSMixer/MLP model with adaptive patching; multivariate via channel-mixing, supports exogenous and known-future inputs on fine-tuning, and runs GPU-free on CPU ([TTM, arXiv 2401.03955, Jan 2024](https://arxiv.org/pdf/2401.03955); [IBM Granite docs](https://www.ibm.com/granite/docs/models/time-series)). **vs TimesFM:** trades peak accuracy for extreme efficiency and CPU deployability; pretrained TTM trails TimesFM on GIFT-Eval but fine-tuned TTM closes much of the gap, and it's the better pick when you have no GPU and clear covariates.

**IBM FlowState.** A small (~9M) state-space-model encoder + functional-basis decoder that is *timescale-invariant* (continuous forecasting at any sampling rate) ([IBM Granite docs](https://www.ibm.com/granite/docs/models/time-series)). **vs TimesFM:** punches above its weight on GIFT-Eval (~27–32, near TimesFM-2.5) at a fraction of the size — notable for resolution-heterogeneous data.

**Newer entrants** worth tracking: **YingLong** (Alibaba, 6M–300M, ~55–68), **TabPFN-TS** (PriorLabs; tabular-PFN with covariate support, ~57), and **Kairos** (ShanghaiTech; mixture-of-size dynamic patching + instance-adaptive RoPE, ~43–47) ([tsfm.ai mirror, 18 Jun 2026](https://tsfm.ai/benchmarks/gift-eval); [Re(Visiting) TSFMs in Finance, arXiv 2511.18578](https://arxiv.org/pdf/2511.18578)).

---

## Part 3 — Recommendation

### (a) General-purpose zero-shot forecasting
**Top pick: Chronos-2 (Amazon) or Toto-2.0 (Datadog).** Both currently outrank TimesFM-2.5 on the neutral GIFT-Eval board, both are Apache-2.0, and both took explicit anti-contamination steps in pretraining ([Chronos-2, 17 Oct 2025](https://arxiv.org/abs/2510.15821); [Toto 2.0, ~May 2026](https://arxiv.org/html/2605.20119v1); [tsfm.ai mirror, 18 Jun 2026](https://tsfm.ai/benchmarks/gift-eval)). Choose **Chronos-2** if you have covariates/multivariate structure (its native ICL is the standout) or want CPU-friendly speed; choose **Toto-2.0** if you want the strongest scaled accuracy and don't need covariates yet. **TimesFM-2.5 remains an excellent third choice / default baseline** — smallest of the three at 200M, fast, and *better than both on non-stationary data* ([It's TIME, 4 Mar 2026](https://arxiv.org/html/2602.12147v3)).

### (b) Probabilistic / uncertainty-critical use
**Use a quantile- or flow-native model and back-test coverage yourself.** Strong candidates by design: **Chronos-2** and **Moirai-2** (quantile loss, well-placed CRPS), **Toto-2.0** (quantile, scaled), **Sundial** (flow-matching generative, sampled intervals), and **TiRex** (quantile, strong both horizons) ([Chronos-2](https://arxiv.org/abs/2510.15821); [Moirai 2.0](https://arxiv.org/abs/2511.11698); [Sundial](https://arxiv.org/pdf/2502.00816); [TiRex](https://arxiv.org/abs/2505.23719)). **Do not assume any of them — TimesFM included — is calibrated at long horizons**; class-wide, interval calibration degrades with horizon, so validate empirical coverage on your data before trusting intervals for risk/inventory decisions ([Datadog, 14 May 2026](https://www.datadoghq.com/blog/ai/toto-2/)). If your use is regulated and you need auditable conformal intervals out-of-the-box and accept an API, TimeGPT is an option — at the cost of openness and neutral verifiability.

### (c) Fully open / self-hostable (no API, permissive licence)
**This is exactly where TimesFM-2.5 shines, and where two leaders disqualify themselves.** Permissive, self-hostable, commercially-usable (Apache-2.0): **TimesFM-2.5, Chronos-2 / Chronos-Bolt, Toto-2.0, Lag-Llama, Granite TTM / FlowState, Time-MoE, Sundial** ([Spheron, 11 May 2026](https://www.spheron.network/blog/deploy-time-series-foundation-models-gpu-cloud/); [Toto Apache-2.0](https://arxiv.org/abs/2505.14766)). **Disqualified for permissive self-hosting: Moirai (all versions, CC-BY-NC-4.0 — non-commercial)** and **TimeGPT (proprietary/API)** ([Spheron, 11 May 2026](https://www.spheron.network/blog/deploy-time-series-foundation-models-gpu-cloud/)); **TiRex** sits in between under a non-standard NXAI community licence ([NX-AI/TiRex HF](https://huggingface.co/NX-AI/TiRex)). For a no-API, permissive, self-hosted stack today, the cleanest high-accuracy choice is **Toto-2.0 or Chronos-2 (Apache-2.0)**, with **TimesFM-2.5** the best small/low-latency option and **Granite TTM/FlowState** for CPU-only/edge.

> Given your Open-Omniscience constraints (Debian, amnesic Qubes VM, gigabyte-scale local storage, no proprietary dependencies), the **Apache-2.0 + CPU-capable** subset is the relevant one: **TimesFM-2.5, Chronos-2/Bolt, Granite TTM, FlowState**. Moirai and TimeGPT are off the table on licence/API grounds.

### Are TS foundation models actually better than strong classical/statistical baselines yet?
Partially, and only under specific conditions. On modern, more-realistic benchmarks (fev-bench, GIFT-Eval) the latest models *do* beat seasonal-naive/ETS/AutoARIMA — but the *margin* is the story: a sceptical analysis notes that after training on millions of series, the best models beat a decent seasonal baseline by only **about a third on average**, which argues that the learnable cross-series structure in these benchmarks is limited rather than that a revolution has arrived ([Against Time-Series Foundation Models, 10 Mar 2026](https://shakoist.substack.com/p/against-time-series-foundation-models)). The class **wins clearly** in cold-start / long-tail / many-series-at-once settings and on data with strong universal seasonality, where there's no time to fit per-series models ([Operational Viability, ~May 2026](https://arxiv.org/html/2605.24381)). It **still loses** to tuned specialists (LightGBM/XGBoost, PatchTST/N-BEATS/TiDE) on data-rich, physically-constrained, or very-short / very-long-horizon problems, and to simple seasonal/ETS models on clean extrapolation and horizon-stable calibration ([Operational Viability, ~May 2026](https://arxiv.org/html/2605.24381); [Datadog, 14 May 2026](https://www.datadoghq.com/blog/ai/toto-2/); [AI Horizon Forecast, 3 May 2026](https://aihorizonforecast.substack.com/p/time-series-foundation-models-a-deep)). And remember the deep-learning lesson that predates this wave: vanilla transformers do not win "for free" — gains come from time-series-appropriate representation (patching, variate tokens), inductive biases, and benchmark hygiene, and strong linear baselines remain hard to beat ([Choosing the Forecasting Stack, 27 Jan 2026](https://medium.com/@adnanmasood/choosing-the-forecasting-stack-classical-models-transformers-and-foundation-models-94c8a9479fa8)). **Practical rule: always run seasonal-naive + AutoARIMA/ETS (and a LightGBM if you have covariates) as baselines; only adopt a foundation model where it measurably wins on *your* data and horizon.**

---

## Sources

*Neutral benchmarks*
- Salesforce GIFT-Eval leaderboard — official, live: https://huggingface.co/spaces/Salesforce/GIFT-Eval
- GIFT-Eval public mirror, snapshot **18 Jun 2026**: https://tsfm.ai/benchmarks/gift-eval
- GIFT-Eval paper, arXiv 2410.10393, **11 Nov 2024**: https://arxiv.org/abs/2410.10393

*Contamination / evaluation integrity*
- Rethinking Evaluation: (Un)known Information Leakage, arXiv 2510.13654, HTML **25 Feb 2026**: https://arxiv.org/html/2510.13654
- TSFM Benchmarking Challenges & Requirements, ResearchGate, **7 May 2026**: https://www.researchgate.net/publication/396517573_Time_Series_Foundation_Models_Benchmarking_Challenges_and_Requirements
- TSFMAudit (contamination auditing), arXiv 2605.26161, **~May 2026**: https://arxiv.org/html/2605.26161
- It's TIME (contamination-resistant benchmark), arXiv 2602.12147, HTML v3 **4 Mar 2026**: https://arxiv.org/html/2602.12147v3

*TimesFM*
- A decoder-only foundation model for time-series forecasting, ICML 2024: https://openreview.net/forum?id=jn2iTJas6h
- TimesFM-2.5 model page (pretraining sources, 16k ctx, quantile head), tsfm.ai, **17 Dec 2025**: https://tsfm.ai/models/google/timesfm-2.5-200m-pytorch
- TimesFM-2.5 transformers docs (architecture changes), HF, **27 Feb 2026**: https://huggingface.co/docs/transformers/model_doc/timesfm2_5
- TimesFM-2.5 launch, MarkTechPost, **16 Sep 2025**: https://www.marktechpost.com/2025/09/16/google-ai-ships-timesfm-2-5-smaller-longer-context-foundation-model-that-now-leads-gift-eval-zero-shot-forecasting/
- v1 archive (1.0/2.0 specs), DeepWiki, **13 May 2026**: https://deepwiki.com/google-research/timesfm/7.1-v1-archive-(timesfm-1.0-and-2.0)
- Production architecture review (XReg Oct-2025, latency), Pixels & Pulse, **31 Mar 2026**: https://thepixelspulse.com/posts/google-timesfm-2-5-production-architecture/
- TimesFM benchmark summary (Monash/ETT), aimultiple, **10 Feb 2026**: https://research.aimultiple.com/time-series-foundation-models/
- TimesFM-2.5 + MetaTrader/LoRA finance, MQL5, **21 Apr 2026**: https://www.mql5.com/en/articles/22096

*Competing models*
- Chronos-2, arXiv 2510.15821, **17 Oct 2025**: https://arxiv.org/abs/2510.15821 · HF: https://huggingface.co/amazon/chronos-2 · Amazon Science: https://www.amazon.science/blog/introducing-chronos-2-from-univariate-to-universal-forecasting
- Chronos / Chronos-Bolt repo (Apache-2.0): https://github.com/amazon-science/chronos-forecasting
- Toto, arXiv 2505.14766, **May 2025**: https://arxiv.org/abs/2505.14766 · Toto 2.0, arXiv 2605.20119, **~May 2026**: https://arxiv.org/html/2605.20119v1 · Datadog blog **14 May 2026**: https://www.datadoghq.com/blog/ai/toto-2/ · repo: https://github.com/datadog/toto
- Moirai 2.0, arXiv 2511.11698, v3 **3 Feb 2026**: https://arxiv.org/abs/2511.11698 · Salesforce blog **13 Aug 2025**: https://www.salesforce.com/blog/moirai-2-0/ · HF: https://huggingface.co/Salesforce/moirai-2.0-R-small
- TiRex, arXiv 2505.23719, **NeurIPS 2025**: https://arxiv.org/abs/2505.23719 · HF: https://huggingface.co/NX-AI/TiRex
- Sundial, arXiv 2502.00816, **ICML 2025**: https://arxiv.org/pdf/2502.00816
- Time-MoE, arXiv 2409.16040, **ICLR 2025**: https://arxiv.org/abs/2409.16040
- Timer-S1, arXiv 2603.04791, **Mar 2026**: https://arxiv.org/abs/2603.04791 · HF: https://huggingface.co/bytedance-research/Timer-S1
- TimeGPT closed-source note, Nixtla repo: https://github.com/Nixtla/nixtla/blob/main/README.md
- MOMENT, arXiv 2402.03885, **ICML 2024**: https://arxiv.org/pdf/2402.03885
- Lag-Llama, IBM tutorial, **19 Nov 2025**: https://www.ibm.com/think/tutorials/lag-llama
- Granite TTM, arXiv 2401.03955, **Jan 2024**: https://arxiv.org/pdf/2401.03955 · IBM Granite TS docs: https://www.ibm.com/granite/docs/models/time-series

*Baselines, operations, licensing*
- Operational Viability of TSFMs (latency, MASE), arXiv 2605.24381, **~May 2026**: https://arxiv.org/html/2605.24381
- Against Time-Series Foundation Models (margin critique), **10 Mar 2026**: https://shakoist.substack.com/p/against-time-series-foundation-models
- TSFM deep dive (short-history weakness), AI Horizon Forecast, **3 May 2026**: https://aihorizonforecast.substack.com/p/time-series-foundation-models-a-deep
- onTime zero/few/full-shot benchmark, MDPI, **8 Sep 2025**: https://www.mdpi.com/2813-0324/11/1/32
- Forecasting stack overview, **27 Jan 2026**: https://medium.com/@adnanmasood/choosing-the-forecasting-stack-classical-models-transformers-and-foundation-models-94c8a9479fa8
- License/deployment roundup, Spheron, **11 May 2026**: https://www.spheron.network/blog/deploy-time-series-foundation-models-gpu-cloud/
- TSFM-in-Finance survey (risk-aware eval), ACM DL: https://dl.acm.org/doi/full/10.1145/3785706.3785728

---

## Low-confidence / unverified

- **Exact GIFT-Eval ranks** are a moving target. All ranks here are from a *mirror* refreshed 18 Jun 2026, not a direct read of the official HF Space at the moment you read this; re-check the live board. The mirror (tsfm.ai) is also a commercial vendor, though it claims to auto-sync the official Salesforce results.
- **Normalised MASE/CRPS values** (as opposed to ranks) are not reproduced numerically here because they shift with each submission; treat the per-dataset MASE figures (Traffic 0.482, Energy 0.573 vs 1.046) as the only hard point estimates, from a single 2026 study.
- **TimesFM-2.5 quantile-head calibration:** I found no independent, published reliability-diagram / coverage study isolating TimesFM-2.5's interval calibration. The "degrades with horizon" claim is a *class-wide* finding (Datadog) extrapolated to TimesFM; verify on your own data.
- **TimesFM-2.5 max horizon:** sources disagree (one demo cites ~256-step decode, another ~1k horizon). The model decodes in chunks, so effective horizon depends on configuration.
- **Lag-Llama parameter count:** reported inconsistently (one comparison table lists 200M; the released checkpoint is widely described as far smaller, single-digit to low-tens of millions). Treated as "small," exact figure unconfirmed.
- **Sundial / Timer-S1 licences:** stated as open/Apache by convention for THUML/ByteDance research releases, but I did not directly confirm the licence string on each model card.
- **Chronos-2 disk/throughput numbers** (478 MB, >300 forecasts/s) come from one vendor blog plus one practitioner write-up; hardware-dependent.
- **"Toto-2.0 leads foundation models on GIFT-Eval"** and **"Chronos-2 #1 among pretrained models"** are vendor self-reports from different dates (May 2026 and Oct 2025 respectively); they are mutually consistent with the dated neutral board but each was true at its own publication moment.
- Several 2026 arXiv items are recent preprints (e.g. 2602.06909 "Revisiting the Generic Transformer," 2605.x) that may not yet be peer-reviewed; weight accordingly.
- **Moirai-MoE** specifics (sizes, exact release) are summarised from secondary mentions rather than a direct read of its model card.
