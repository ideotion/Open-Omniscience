# Several models, each with its speciality — the experiment, and what it has to control for

**Status:** design of record for the NEXT session. Nothing built. The maintainer asked
for the experiment explicitly ("let's test this in the next session, with 3 different
batch sizes, starting with 100 articles up to 1000"), and this file exists so that
session measures the right thing rather than re-deriving the question.

**The ask, verbatim:** *"add to the test the possibility (and the impact of) having
several models, each with their specialty, for example Qwen for language detection only
and Mistral's for the rest. I'd like to see how we can configure this type of setup:
should each model run for a certain batch size each, then unload / load the other, and
run another on the same article batch? In this case, what should the batch size be?"*

---

## 1. Why this is worth measuring at all

The 10 August runs produced the first evidence that specialisation is real rather than
hypothetical, and it is narrow:

| model | keyword triage | source tags | language ID | perception p50 |
|---|---|---|---|---|
| Ministral-3 3B | **87.9 %** | **45.5 %** | 94.1 % | 0.95 s |
| Qwen3.5 0.8B | 0 % | 0 % | **100 %** (17/17) | **0.39 s** |
| LFM2.5 1.2B Instruct | 0 % | 0 % | 29.4 % | 0.57 s |
| LFM2.5 1.2B Base | 0 % | 0 % | 0 % | 2.86 s |

Exactly one cell justifies a second model: **Qwen is better AND 2.4× faster at language
ID**, and worthless at everything else. Everything else in the table says "use
Ministral". So the experiment is not "which models should we mix" — it is **"is that one
cell worth the cost of switching"**, and the cost of switching is the whole question.

**n = 17.** That is an anecdote. The first thing the session does is re-measure language
ID on a few hundred articles; if Qwen's advantage does not survive that, the experiment
stops there and the answer is "one model", which is a real finding and cheaper to act on.

## 2. The switching cost is the experiment

A two-model setup on one 8 GB card cannot hold both. Every switch is:

```
stop vLLM (or drop Ollama residency) → free VRAM → start the other → load weights
```

which the field runs already timed at roughly **60–90 s per model load**, plus vLLM's
own startup. That is the number every design below is competing against.

So the quantity to measure is not throughput per model. It is:

> **effective articles/hour for the WHOLE pipeline, including the switches**, at each
> batch size — against the one-model baseline that never switches.

If the two-model pipeline is not faster than Ministral doing everything, the extra
accuracy on language ID has to be worth the loss, and that is the maintainer's call, not
a number.

## 3. The three candidate shapes

**(a) Batch-then-switch** — the maintainer's own proposal. Take N articles, run model A's
task over all N, unload, load B, run B's tasks over the same N, move to the next batch.
Switches per corpus = `2 × (corpus / N)`. Bigger N amortises the switch; bigger N also
means a longer wait before ANY article is fully processed, and a crash loses more work.

**(b) Task-phased** — run language ID over the ENTIRE corpus with the small model, then
switch once, then everything else with the big one. Switches per corpus = **1**. This is
strictly better than (a) on switch cost and strictly worse on latency-to-first-complete
article, and it needs the sweeps to be independently resumable (they already are — each
carries a persisted cursor).

**(c) One model** — the baseline. No switches, one accuracy profile.

**A prediction worth recording before it is measured, so the measurement can refute it:**
(b) should win on throughput by a wide margin, because switch cost is a fixed ~90 s paid
once instead of `2 × corpus/N` times, and the sweeps are already cursor-resumable so the
"phase" structure costs nothing to build. If that holds, the interesting output of this
experiment is not the best batch size — it is that **batch size is the wrong knob**, and
the maintainer's question answers itself in the negative. The batch-size sweep is still
worth running, because it is what makes that answer evidence rather than an argument.

## 4. What to run

Batch sizes **100 / 300 / 1000** articles (the maintainer's range), against a fixed
article sample, for each of (a), (b), (c). Per configuration report, each alone:

- wall-clock to complete the whole sample,
- effective articles/hour,
- **time spent switching** as its own line (the number the design turns on),
- per-task quality on the same sample (triage validity, langdetect accuracy, perception
  precision/recall/hallucination) — because a faster pipeline that is worse is not
  faster at anything that matters,
- peak VRAM, and whether any switch failed.

No composite score. The table is the output.

## 5. Three things that will bite

**The switch must be a real switch.** `arbitration.hand_gpu_to` now waits for the port to
go quiet and refuses when a stop did not take (2026-08-10) — the experiment must read
that refusal and report it, never treat a refused switch as a fast one. A configuration
whose switches silently failed would look like the fastest.

**Ollama and vLLM switch differently.** Ollama drops residency with `keep_alive: 0` and
reloads on the next call, so its "switch" is a lazy reload the model itself pays for;
vLLM must be stopped and restarted. Timing them with one stopwatch and calling both
"switch cost" would compare two different mechanisms. Measure per backend, state which.

**The sample must be one sample.** The same article ids through every configuration, or
the quality columns are measuring the sample rather than the model. The frozen bench
batch already has this discipline (a digest, and a resume across a changed digest is
refused) and the experiment should reuse it rather than sampling its own.

## 6. What already exists

- `src/llm/arbitration.py` — model-aware readiness, honest stop outcomes, the bounded
  wait. The switch primitive is built and tested.
- `src/ai_layer/coordinator.py` — the round-robin lane and `user_batch_hold`, so a
  background sweep cannot contend with the experiment.
- `src/ai_layer/bench_batch.py` — the frozen sample and its digest.
- Every sweep carries a persisted cursor, which is what makes shape (b) buildable at all.

What does **not** exist: per-task model assignment. Today one model serves everything
(`active_model()`). A two-model setup needs a task→model map, and that map is also the
thing the maintainer would configure in Settings if the experiment says it is worth it.
Building the map before the measurement would be building a knob for a setup that may
turn out to be slower.

---

*Open Omniscience — GPL-3.0-or-later. Copyright (C) 2026 Ideotion.*
