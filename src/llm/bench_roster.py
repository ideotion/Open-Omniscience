"""The comparative-bench model roster: six models, two backends, one honest table.

Maintainer ask 2026-08-02: a button beside each install control that downloads a
chosen set of bench models, so the model-comparison work has the same models on
whichever backend a machine serves with.

WHERE THESE IDENTIFIERS COME FROM, and why that is the whole point of this module.
Almost every string below was read off a live model page on 2026-08-02 by an
internet-connected session. The build sandbox cannot reach huggingface.co, ollama.com
or registry.ollama.ai (the gateway 403s all three), so nothing here could be checked by
the session that wrote the file -- which is exactly the condition under which this
project has fabricated model tags before. ``src/llm/ollama.py``'s catalog still carries
the scar:

    "(The previous catalog -- gemma4:e2b, llama4, qwen3.5 -- was hallucinated.)"

Two corrections from that same acquisition run, recorded because they cut both ways:
``qwen3.5`` IS real now (released after several model cutoffs, which is why it read as
fictional), and so is ``gemma4``. A name being invented once does not make it invented
forever, and a name being real today does not excuse having written it before it was.

"ALMOST" IS LOAD-BEARING, so every identifier states its own tier rather than inheriting
a blanket claim from this docstring. ``verification: "fetched"`` means a page was loaded;
``"search-verified"`` means the acquisition run NAMED the string but no fetch was
recorded for it. Exactly one row is at the weaker tier today
(``lfm25-1-2b-instruct``, added on the maintainer's 2026-08-02 decision because four of
the bench's five tasks are constrained-output instruct tasks that its Base sibling cannot
answer). The field has NO default: a row added without one raises, because a silent
default would claim the stronger tier for whoever forgot to think about it.

WHAT THIS FILE REFUSES TO DO. Three rows have no Ollama tag at all. None gets a
near-match: ``library/smollm`` is a different, older model, ``lfm2.5-thinking`` is a
different variant, and a user-namespace upload is not a first-party tag until somebody
confirms whose namespace it is. They are reported ABSENT for that backend, with what was
searched, because a substitution presented as the requested model is worse than a gap.
An absence that is merely UNRESOLVED carries an ``open_question`` saying what would
settle it -- a gap somebody can close in one lookup should not read like a dead end.

FLAGS ARE SHOWN BEFORE THE BYTES, not discovered through a failed download. A gated
repo, a base (non-instruct) checkpoint, an unread licence and a third-party GGUF are
each a real reason an operator might not want a model -- and the gated one will simply
fail without an accepted licence and a token, which is a thing to say beforehand.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

#: When the roster was verified against live model pages. Registered in
#: ``configs/external_artifacts.yml`` (the protocol guard test requires it) so a stale
#: roster is reported rather than silently trusted -- model libraries move fast, and
#: three of these six changed shape within months of each other.
BENCH_ROSTER_AS_OF = "2026-08"

#: Flag vocabulary. Each is a fact an operator should have BEFORE downloading, and each
#: is rendered next to the model rather than buried in a note.
FLAG_MEANINGS: dict[str, str] = {
    "gated": (
        "Hugging Face requires you to accept the licence and supply a token. An "
        "automated download fails without both."
    ),
    "base_model": (
        "A base (pre-trained) checkpoint, NOT instruction-tuned. Every task this app "
        "runs is an instruct task, so it will underperform badly here; the publisher "
        "recommends it for fine-tuning."
    ),
    "licence_unverified": (
        "The licence text was not read. Not filed as permissive until someone reads it."
    ),
    "vision_capable": (
        "A vision-language model. It serves plain text fine, which is all this app "
        "asks of it, but it is not a text-only model."
    ),
    "third_party_passthrough": (
        "Reachable only through a GGUF published by a third party, not the model's own "
        "organisation -- a weaker provenance claim than a library tag."
    ),
    "context_varies_by_quant": (
        "The advertised context length applies to the listed quant only; other quants "
        "of the same model ship a much smaller window."
    ),
    "sources_disagree": (
        "The model card and the registry metadata state different parameter counts. "
        "Both are recorded rather than one being picked."
    ),
    "use_policy": (
        "The licence carries an acceptable-use policy you must comply with. Available, "
        "but not ticked for you — read it and decide."
    ),
    "use_rider": (
        "An otherwise-permissive licence with a rider on the model card (typically "
        "third-party rights). Milder than an acceptable-use policy, and stated so the "
        "'permissive' label stays honest."
    ),
}

#: Which backend a flag actually describes. Several are properties of ONE channel, not
#: of the model: Gemma-3n is gated on Hugging Face and ungated on Ollama, and
#: "context varies by quant" is a statement about Ollama tags. Showing a warning on a
#: row where it does not apply is a fabricated warning -- the mirror image of a
#: fabricated pass, and just as corrosive to a table meant to be trusted.
_FLAG_SCOPE: dict[str, set[str]] = {
    "gated": {"vllm"},
    "context_varies_by_quant": {"ollama"},
    "third_party_passthrough": {"ollama"},
}

#: Flags that keep a row from being pre-ticked.
#:
#: ``use_policy`` is here and ``use_rider`` is NOT, because the two are not the same
#: thing and the acquisition run said so outright: Gemma carries a Prohibited Use
#: Policy you must comply with, while Ministral's Apache-2.0 adds a third-party-rights
#: rider on the card -- "not a Gemma-class restriction, but not bare Apache-2.0
#: either". Collapsing them into one flag unticked this app's OWN DEFAULT MODEL over a
#: sentence about IP rights, which is how an over-blunt honesty rule starts destroying
#: the thing it was meant to protect. Both are labelled; only the policy blocks.
_BLOCKS_DEFAULT = {"gated", "base_model", "licence_unverified", "use_policy"}

#: The roster. ``hf`` drives the vLLM path, ``ollama`` the Ollama path; either may be
#: ``None``, which means "not published there" and is rendered as such.
#:
#: ``default_on`` is deliberately NOT "everything": an entry carrying a blocking flag
#: (gated, base-only, unread licence) ships UNTICKED, the same convention the law
#: catalog uses when a source is a lead rather than a fetched fact. The operator can
#: still tick it; they just have to mean it.
BENCH_ROSTER: list[dict] = [
    {
        "key": "qwen35-0-8b",
        "label": "Qwen3.5-0.8B",
        "default_on": True,
        "flags": ["vision_capable", "sources_disagree"],
        "hf": {
            "repo": "Qwen/Qwen3.5-0.8B",
            "verification": "fetched",
            "gated": False,
            "licence": "Apache-2.0",
            "use_restrictions": False,
            "params": "0.8B (card) / 0.9B (registry metadata)",
            "context_length": 262144,
            "card_url": "https://huggingface.co/Qwen/Qwen3.5-0.8B",
            "size": "~1.75 GB (from search results, not the file tree)",
        },
        "ollama": {
            "tag": "qwen3.5:0.8b-q8_0",
            "verification": "fetched",
            "source": "library",
            "size": "1.0 GB",
            "context_length": 262144,
            # Not an oversight: the 0.8b size has no q4_K_M at all, while every larger
            # size does. Picking q4_K_M here would have 404'd at pull time.
            "quant_note": "no q4_K_M exists at 0.8b — q8_0 is the smallest real quant",
            "available_quants": ["q8_0", "bf16", "mlx", "mlx-bf16", "mxfp8", "nvfp4"],
        },
        "note": "Released after several model cutoffs, which is why this name reads as fictional and is not.",
    },
    {
        "key": "gemma-3n-e2b-it",
        "label": "Gemma-3n-E2B-IT",
        # Gated on Hugging Face: an automated vLLM download cannot succeed unattended.
        "default_on": False,
        "flags": ["gated", "sources_disagree"],
        "hf": {
            # CASE MATTERS: the requested spelling (…-E2B-IT) 404s. This is the repo.
            "repo": "google/gemma-3n-E2B-it",
            "verification": "fetched",
            "gated": True,
            "licence": "Gemma Terms of Use",
            "use_restrictions": True,
            "use_restrictions_url": "https://ai.google.dev/gemma/prohibited_use_policy",
            "params": "6B raw / 2B effective (card) / 5B (registry metadata)",
            "context_length": 32768,
            "card_url": "https://huggingface.co/google/gemma-3n-E2B-it",
            "size": None,
        },
        "ollama": {
            "tag": "gemma3n:e2b-it-q4_K_M",
            "verification": "fetched",
            "source": "library",
            "size": "5.6 GB",
            "context_length": 32768,
            "available_quants": ["q4_K_M", "q8_0", "fp16"],
            "note": "The Ollama build is text-input only; the Hugging Face one also takes image, audio and video.",
        },
        "note": "Not gated on Ollama — only the Hugging Face path needs an accepted licence and a token.",
    },
    {
        "key": "phi-4-mini-instruct",
        "label": "Phi-4-mini-instruct",
        "default_on": True,
        "flags": ["context_varies_by_quant", "sources_disagree"],
        "hf": {
            "repo": "microsoft/Phi-4-mini-instruct",
            "verification": "fetched",
            "gated": False,
            "licence": "MIT",
            "use_restrictions": False,
            "params": "3.8B (card) / 4B (registry metadata)",
            "context_length": 131072,
            "card_url": "https://huggingface.co/microsoft/Phi-4-mini-instruct",
            "size": None,
        },
        "ollama": {
            "tag": "phi4-mini:3.8b-q4_K_M",
            "verification": "fetched",
            "source": "library",
            "size": "2.5 GB",
            "context_length": 131072,
            "quant_note": "the q8_0 and fp16 tags ship a 4K window, not 128K",
            "available_quants": ["q4_K_M", "q8_0", "fp16"],
            "min_ollama_version": "0.5.13",
        },
        "note": "The cleanest of the six: ungated, MIT, text-only in and out.",
    },
    {
        "key": "smollm3-3b",
        "label": "SmolLM3-3B",
        "default_on": True,
        "flags": [],
        "hf": {
            "repo": "HuggingFaceTB/SmolLM3-3B",
            "verification": "fetched",
            "gated": False,
            "licence": "Apache-2.0",
            "use_restrictions": False,
            "params": "3B",
            "context_length": 65536,
            "context_note": "131072 is reachable only via a manual YaRN rope_scaling edit",
            "card_url": "https://huggingface.co/HuggingFaceTB/SmolLM3-3B",
            "size": None,
        },
        # Absent from the library. `library/smollm` is the older 135M/360M/1.7B family —
        # a DIFFERENT model — so it is not offered in its place.
        "ollama": None,
        "ollama_absent": {
            "reason": "not published in the official Ollama library",
            "searched": (
                "ollama.com/library/smollm3 (not found); library/smollm (a different, "
                "older model family); ollama/ollama issue #11340 (closed)"
            ),
            # There IS a way to reach it — see ALTERNATIVES below. It lives there rather
            # than here because it is a different artefact, not this row wearing a hat.
            "alternative_key": "smollm3-3b-gguf-passthrough",
        },
        "note": "The requested spelling was 'SmalLM3'; the real name is SmolLM3.",
    },
    {
        "key": "ministral-3-3b-instruct-2512",
        "label": "Ministral-3-3B-Instruct-2512",
        "default_on": True,
        "flags": ["vision_capable"],
        "hf": {
            "repo": "mistralai/Ministral-3-3B-Instruct-2512",
            "verification": "fetched",
            "gated": False,
            # Apache-2.0, but the card adds a third-party-rights rider. Recorded so the
            # catalog's permissive-first ordering stays honest about what it is ordering.
            "licence": "Apache-2.0 (card adds a third-party-rights rider)",
            "use_restrictions": True,
            "params": "4B total (3.4B language model + 0.4B vision encoder)",
            "context_length": 262144,
            "precision": "FP8 by default; a separate BF16 repo exists",
            "card_url": "https://huggingface.co/mistralai/Ministral-3-3B-Instruct-2512",
            "size": "~4.67 GB safetensors (from search results, not the file tree)",
        },
        "ollama": {
            "tag": "ministral-3:3b-instruct-2512-q4_K_M",
            "verification": "fetched",
            "source": "library",
            "size": "3.0 GB",
            "context_length": 262144,
            "available_quants": ["q4_K_M", "q8_0", "fp16"],
            "min_ollama_version": "0.13.1",
        },
        "note": "Already this app's verified default on both backends — the roster's calibration row.",
    },
    {
        "key": "lfm25-1-2b-base",
        "label": "LFM2.5-1.2B-Base",
        # A base checkpoint with an unread licence: two reasons not to pre-tick it.
        "default_on": False,
        "flags": ["base_model", "licence_unverified"],
        "hf": {
            "repo": "LiquidAI/LFM2.5-1.2B-Base",
            "verification": "fetched",
            "gated": False,
            "licence": "other (badge only; called 'LFM Open License v1.0' on mirrors, unread)",
            "use_restrictions": None,  # genuinely unknown, not assumed either way
            "params": "1.17B (card) / 1B (registry metadata)",
            "context_length": 32768,
            "card_url": "https://huggingface.co/LiquidAI/LFM2.5-1.2B-Base",
            "size": None,
        },
        "ollama": None,
        "ollama_absent": {
            "reason": "the Base variant is not published on Ollama in any confirmable form",
            "searched": (
                "library/lfm2.5 (the 8B-A1B model only); library/lfm2.5-thinking (1.2b "
                "but the Thinking variant); LiquidAI/lfm2.5-1.2b-instruct (Instruct, and "
                "a user namespace)"
            ),
            # The publisher's own card links its "Base-GGUF" row at the Instruct-GGUF
            # repo, which looks like their copy-paste error. Not resolved, not guessed.
            "passthrough_tag": None,
            "passthrough_caveat": (
                "the card's Base-GGUF row links to the Instruct-GGUF repo; the Base GGUF "
                "could not be confirmed, and the Instruct id was not written in its place"
            ),
        },
        "note": (
            "The instruct sibling is LiquidAI/LFM2.5-1.2B-Instruct. It was NOT substituted: "
            "Base is what was asked for, and the difference is stated instead. It is offered "
            "ADDITIONALLY as its own row below, so the bench has a LiquidAI datapoint that "
            "measures something."
        ),
    },
    {
        # ADDED, NOT SUBSTITUTED (maintainer decision 2026-08-02). The row above is the
        # one that was asked for and it stays exactly as it was.
        #
        # WHY A SECOND ROW EARNS ITS PLACE. Four of the bench's five tasks
        # (``model_bench.BENCH_TASKS``: perception, triage, source_tags, langdetect) are
        # CONSTRAINED-OUTPUT instruct tasks -- extract fields, echo a term back exactly,
        # pick from a closed vocabulary, emit a language code. A base checkpoint answers
        # none of them; only ``latency`` would produce a real number. So ticking Base
        # yields one usable metric out of five plus four near-zeros that mean "wrong
        # tool", not "bad model" -- and a near-zero with no memory of why is exactly the
        # number that gets misread later. The Instruct sibling is what can actually
        # answer the question the roster exists to ask.
        "key": "lfm25-1-2b-instruct",
        "label": "LFM2.5-1.2B-Instruct",
        # Unticked for the same reason as its Base sibling: nobody has read the licence.
        "default_on": False,
        "flags": ["licence_unverified"],
        "hf": {
            "repo": "LiquidAI/LFM2.5-1.2B-Instruct",
            # THE ONE ROW IN THIS FILE THAT WAS NOT READ OFF A LIVE PAGE. The id comes
            # from the acquisition run's own prose (the Base card names its sibling), so
            # it is the run's string rather than an invention -- but no page fetch was
            # recorded for it, and the difference between "someone loaded this URL" and
            # "someone mentioned this name" is the whole distance between a verified
            # identifier and a plausible one. Filed at the weaker tier and shown as such.
            "verification": "search-verified",
            "gated": False,
            # Deliberately not copied from the Base row. The Base card's licence badge
            # and parameter split are facts about THAT repo; asserting them here would be
            # inventing agreement between two pages only one of which was read.
            "licence": "other (unread — assumed to match the Base sibling's badge, unconfirmed)",
            "use_restrictions": None,
            "params": None,
            "context_length": None,
            "card_url": "https://huggingface.co/LiquidAI/LFM2.5-1.2B-Instruct",
            "size": None,
        },
        "ollama": None,
        "ollama_absent": {
            "reason": "no first-party Ollama tag confirmed for the Instruct variant",
            "searched": (
                "library/lfm2.5 (the 8B-A1B model only); library/lfm2.5-thinking (1.2b, "
                "first-party, but the Thinking variant); LiquidAI/lfm2.5-1.2b-instruct "
                "(the right variant and size, in a user namespace)"
            ),
            # THE OPEN QUESTION, recorded so the next connected session can close it in
            # one lookup. `LiquidAI/lfm2.5-1.2b-instruct` was set aside as "a user
            # namespace" -- but if that Ollama account IS LiquidAI, it is FIRST-PARTY
            # publishing and this absence disappears. That is a different provenance
            # claim entirely from the community re-uploads rejected for SmolLM3
            # (alibayram, yasserrmd, ...), where the objection was that nobody knew who
            # built the file. Not resolved here, and not guessed either way.
            "open_question": (
                "is the Ollama account 'LiquidAI' the publisher's own? If yes, "
                "LiquidAI/lfm2.5-1.2b-instruct is a first-party tag and this row installs "
                "on Ollama too; if it is somebody who took the name, the absence stands"
            ),
            "passthrough_tag": None,
            "passthrough_caveat": (
                "library/lfm2.5-thinking is first-party and the right size, but a Thinking "
                "variant emits reasoning traces that fail format validity on three of the "
                "four constrained-output tasks -- a finding about reasoning models, not a "
                "LiquidAI capability measurement, so it is not offered under this name"
            ),
        },
        "note": (
            "Added so the bench can measure a LiquidAI model on instruct tasks. Its Base "
            "sibling above is unchanged and still the row that was requested."
        ),
    },
]


#: ALTERNATIVES — a different way to reach a roster model, kept as its own artefact.
#:
#: The acquisition run that produced these was explicit about the shape: "Each entry is
#: a DIFFERENT artefact from the row it substitutes. Commit under its own key; do not
#: overwrite the original row." That is the never-substitute rule applied one level
#: down, and it is why these are not folded into the rows above: an operator choosing a
#: third-party GGUF should know that is what they chose.
#:
#: None is ever pre-ticked. An alternative is a deliberate choice, not a default.
ALTERNATIVES: list[dict] = [
    {
        "key": "smollm3-3b-gguf-passthrough",
        "substitutes": "smollm3-3b",
        "label": "SmolLM3-3B (community GGUF, via Ollama passthrough)",
        "substitution_type": "same_model_different_channel",
        "backend": "ollama",
        "flags": ["third_party_passthrough"],
        "tag": "hf.co/ggml-org/SmolLM3-3B-GGUF:Q4_K_M",
            "verification": "fetched",
        "source": "hf_passthrough",
        "first_party": False,
        "size": "1.92 GB",
        "available_quants": ["Q4_K_M", "Q8_0", "F16"],
        "provenance": (
            "the pull string was read verbatim off the Ollama panel of the Hugging Face "
            "page, not constructed"
        ),
        "caveat": (
            "ggml-org is the llama.cpp team, NOT HuggingFaceTB. This is a third-party "
            "build of the right model — label it passthrough, never library."
        ),
        "operational_note": (
            "Thinking mode needs --jinja under llama.cpp; under Ollama the chat template "
            "comes from the GGUF, so verify /think and /no_think behave before trusting it."
        ),
        # Recorded so a later session does not "helpfully" add one of these back. They
        # are unaffiliated re-uploads with no provenance, which is the whole objection.
        "rejected": [
            "alibayram/smollm3",
            "yasserrmd/smollm3",
            "pedrolucas/smollm3",
            "R4C3R/smollm3-3b-heretic",
        ],
        "rejected_reason": "unaffiliated community re-uploads, no provenance",
    },
]


def alternatives_for(backend: str, key: str | None = None) -> list[dict]:
    """Alternative channels for ``backend``, optionally for one roster key."""
    return [
        a
        for a in ALTERNATIVES
        if a["backend"] == backend and (key is None or a["substitutes"] == key)
    ]


def _entry_for_backend(entry: dict, backend: str) -> dict:
    """One roster row as the UI needs it for ONE backend: the identifier to install, or
    an honest statement of why there is none.

    ``installable`` is about EXISTENCE, not advisability. A gated repo is installable in
    the sense that we have a real identifier for it -- what it needs is a licence the
    operator accepts and a token, which is a warning, not an absence. Conflating the two
    would either hide a real model or promise one we cannot fetch."""
    if backend == "vllm":
        hf = entry.get("hf")
        if not hf:
            return {
                "installable": False,
                "absent_reason": "no Hugging Face repository recorded",
                "searched": None,
            }
        return {
            "installable": True,
            "identifier": hf["repo"],
            "size": hf.get("size"),
            "licence": hf.get("licence"),
            "context_length": hf.get("context_length"),
            "gated": bool(hf.get("gated")),
            "source": "huggingface",
            # NO DEFAULT. An absent value would silently claim the STRONGER tier, which
            # is the wrong direction for a field whose whole job is to be honest about
            # provenance; the registry test below makes absence impossible instead.
            "verification": hf["verification"],
        }

    oll = entry.get("ollama")
    if oll:
        return {
            "installable": True,
            "identifier": oll["tag"],
            "size": oll.get("size"),
            "licence": (entry.get("hf") or {}).get("licence"),
            "context_length": oll.get("context_length"),
            "gated": False,
            "source": oll.get("source", "library"),
            "quant_note": oll.get("quant_note"),
            "min_ollama_version": oll.get("min_ollama_version"),
            "verification": oll["verification"],
        }

    absent = entry.get("ollama_absent") or {}
    # An alternative channel does NOT make this row installable. It is offered beside
    # the row, under its own key, so that picking it is a visible choice rather than a
    # gap the table quietly filled in.
    return {
        "installable": False,
        "absent_reason": absent.get("reason", "not published for this backend"),
        "searched": absent.get("searched"),
        "caveat": absent.get("passthrough_caveat"),
        "alternative_key": absent.get("alternative_key"),
        # An absence that is merely UNRESOLVED is not the same as one that is settled,
        # and a panel that renders them identically buries the cheaper of the two.
        "open_question": absent.get("open_question"),
    }


def roster_for(backend: str) -> dict:
    """The roster as the Settings panel renders it for ``backend`` ("vllm" | "ollama").

    Every row is returned, including the ones with nothing to install: a model that is
    absent from a backend is a finding the operator should see, not a row quietly
    dropped so the table looks complete."""
    backend = "vllm" if backend == "vllm" else "ollama"
    rows = []
    for entry in BENCH_ROSTER:
        target = _entry_for_backend(entry, backend)
        # Only the flags that describe THIS backend, plus the use-restriction flag
        # derived from whichever licence actually applies here.
        flags = [f for f in entry["flags"] if backend in _FLAG_SCOPE.get(f, {"vllm", "ollama"})]
        hf = entry.get("hf") or {}
        if hf.get("use_restrictions") is True:
            # A policy you must comply with, or a rider on an otherwise-permissive
            # licence? The presence of a policy document is what separates them.
            flags.append("use_policy" if hf.get("use_restrictions_url") else "use_rider")
        # A row is pre-ticked only when it is BOTH installable here and free of the
        # flags that mean "you probably do not want this by default".
        blocking = _BLOCKS_DEFAULT & set(flags)
        rows.append(
            {
                "key": entry["key"],
                "label": entry["label"],
                "flags": flags,
                "note": entry.get("note"),
                "card_url": (entry.get("hf") or {}).get("card_url"),
                "default_on": bool(entry["default_on"] and target["installable"] and not blocking),
                **target,
            }
        )
    return {
        "backend": backend,
        "as_of": BENCH_ROSTER_AS_OF,
        "models": rows,
        # Listed separately, never merged into `models`: the table says what each model
        # IS, and this says what else could be reached and at what cost in provenance.
        "alternatives": alternatives_for(backend),
        "flag_meanings": FLAG_MEANINGS,
        "method": (
            "Every identifier was read off a live model page on 2026-08-02 and carries "
            "its own flags; a model not published for this backend is reported absent "
            "with what was searched, never replaced by a similar one."
        ),
        "caveat": (
            "Model libraries move fast. Sizes marked as coming from search results were "
            "not read off a file tree, and a roster older than its freshness window is "
            "reported stale by the diagnostics rather than silently trusted."
        ),
    }


def identifiers_for(backend: str, keys: list[str]) -> tuple[list[dict], list[dict]]:
    """Resolve selected keys to (installable, refused) for ``backend``.

    Refusals are returned rather than dropped: asking for six models and being handed
    four downloads with no explanation is precisely the silence this roster exists to
    prevent."""
    wanted = list(dict.fromkeys(keys))  # de-duplicated, order preserved
    by_key = {e["key"]: e for e in BENCH_ROSTER}
    ok: list[dict] = []
    refused: list[dict] = []
    for key in wanted:
        entry = by_key.get(key)
        if entry is None:
            refused.append({"key": key, "reason": "not in the bench roster"})
            continue
        target = _entry_for_backend(entry, backend)
        if not target["installable"]:
            refused.append(
                {
                    "key": key,
                    "label": entry["label"],
                    "reason": target["absent_reason"],
                    "searched": target.get("searched"),
                }
            )
            continue
        ok.append({"key": key, "label": entry["label"], **target})
    return ok, refused
