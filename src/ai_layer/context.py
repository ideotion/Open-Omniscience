"""Context budgeting: how much of an article a model actually sees (E-S4, ruling 16).

Two questions, answered separately because they have opposite right answers.

**How big should the context be?** Not "as big as the model allows". The KV cache
scales with context and is paid on EVERY call, in memory and in latency, and on vLLM
it is paid again in lost concurrency. So the budget is sized to the corpus that
actually exists — roughly the 95th percentile of article length, measured by the
shipped ``article_length`` diagnostic — and the 1 % tail is handled as a tail rather
than by taxing the other 99 %.

**What happens to an article that does not fit?** It depends entirely on who asked,
and conflating the two would be the dishonest move:

* a BACKGROUND sweep head-truncates and RECORDS that it did — "analyzed the first N
  of M characters" travels with the result, so a thin extraction is never mistaken
  for a thin article;
* a USER-DRIVEN summarize or translate NEVER silently truncates. It splits at
  paragraph boundaries, runs every part, and says so. A translation that quietly
  stopped at 6,000 characters looks exactly like a complete one.

CHARS-TO-TOKENS IS AN ESTIMATE AND IS LABELLED ONE. Tokenizers differ by model and
by script, and this module has no tokenizer. The ratios below are conservative
rules of thumb, per script because the variation across scripts is far larger than
the variation across models: a Chinese character is roughly a token, a Latin word is
roughly four characters. Every function that uses them says so in its output rather
than presenting a derived number as a token count.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import re
import unicodedata

#: Conservative chars-per-token rules of thumb, by script. Lower = denser text.
#: NOT measured with a tokenizer — see the module docstring. Erring low costs a
#: little unused context; erring high overflows it, so these lean low.
CHARS_PER_TOKEN: dict[str, float] = {
    "latin": 4.0,
    "cyrillic": 2.5,
    "greek": 2.5,
    "arabic": 2.5,
    "hebrew": 2.5,
    "devanagari": 2.5,
    "bengali": 2.5,
    "thai": 2.5,
    "cjk": 1.2,
}
DEFAULT_CHARS_PER_TOKEN = 2.5

#: Characters per whitespace-separated WORD, by script — the second estimate in the
#: chain, needed because the shipped ``article_length`` diagnostic measures words and
#: the context window is spent on characters. Unsegmented scripts are absent on
#: purpose: ``word_count`` is meaningless there (the diagnostic itself flags them), so
#: a conversion would be arithmetic on a number that means nothing.
CHARS_PER_WORD: dict[str, float] = {
    "latin": 6.0,
    "cyrillic": 7.0,
    "greek": 7.0,
    "arabic": 6.0,
    "hebrew": 6.0,
    "devanagari": 6.0,
    "bengali": 6.0,
}

#: Tokens set aside for the system prompt, the title line and formatting overhead.
PROMPT_OVERHEAD_TOKENS = 512
#: Tokens set aside for the model's OWN answer. A summary/translation shares the
#: context window with its input, so a budget that spent all of it on the article
#: would leave the model no room to reply.
OUTPUT_RESERVE_TOKENS = 1024

#: The pre-E-S4 constant, kept as the fallback so a machine that can tell us nothing
#: behaves exactly as it did before rather than getting a guessed budget.
LEGACY_TEXT_BUDGET_CHARS = 6000

_SCRIPT_RANGES = (
    ("cjk", (0x3040, 0x30FF), (0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xAC00, 0xD7AF)),
    ("cyrillic", (0x0400, 0x04FF)),
    ("greek", (0x0370, 0x03FF)),
    ("hebrew", (0x0590, 0x05FF)),
    ("arabic", (0x0600, 0x06FF), (0x0750, 0x077F)),
    ("devanagari", (0x0900, 0x097F)),
    ("bengali", (0x0980, 0x09FF)),
    ("thai", (0x0E00, 0x0E7F)),
)


def dominant_script(text: str, sample: int = 2000) -> str:
    """The script most of ``text`` is written in, or ``"latin"`` when it carries no
    letters to judge by. A sample is enough: an article does not change script
    halfway, and scanning a megabyte to answer a ratio question would be waste."""
    counts: dict[str, int] = {}
    for ch in (text or "")[:sample]:
        if not ch.isalpha():
            continue
        cp = ord(ch)
        name = "latin"
        for entry in _SCRIPT_RANGES:
            label, ranges = entry[0], entry[1:]
            if any(lo <= cp <= hi for lo, hi in ranges):
                name = label
                break
        else:
            if not unicodedata.name(ch, "").startswith("LATIN"):
                name = "latin"
        counts[name] = counts.get(name, 0) + 1
    return max(counts, key=lambda k: counts[k]) if counts else "latin"


def chars_per_token(script: str) -> float:
    return CHARS_PER_TOKEN.get(script, DEFAULT_CHARS_PER_TOKEN)


def estimate_tokens(chars: int, script: str = "latin") -> int:
    """An ESTIMATE, never a token count. Callers state the method beside the number."""
    return int(max(0, chars) / chars_per_token(script)) if chars else 0


def text_budget_chars(num_ctx: int | None, script: str = "latin") -> int:
    """How many characters of article text fit alongside the prompt and the answer.

    ``None`` (nothing configured) falls back to the pre-E-S4 constant rather than a
    derived guess: a machine that told us nothing should behave as it always did.
    """
    if not num_ctx or num_ctx <= 0:
        return LEGACY_TEXT_BUDGET_CHARS
    usable = int(num_ctx) - PROMPT_OVERHEAD_TOKENS - OUTPUT_RESERVE_TOKENS
    if usable <= 0:
        return LEGACY_TEXT_BUDGET_CHARS
    return max(1000, int(usable * chars_per_token(script)))


# --------------------------------------------------------------------------- #
#  The Ollama num_ctx auto-tune (the documented B7 gap).
# --------------------------------------------------------------------------- #
#: Rough KV-cache cost per 1k tokens of context for a 3-8B-class model, in MB. A
#: DISCLOSED heuristic mirroring vLLM's own ``compute_server_args`` posture — never a
#: measured fact, and the operator override always wins.
KV_MB_PER_1K_TOKENS = 140.0
#: Never propose less than this: below it the model cannot hold one article.
MIN_NUM_CTX = 4096
#: Never propose more than this from a heuristic. A bigger window is the operator's
#: explicit choice, not something a rule of thumb should hand out.
MAX_NUM_CTX = 32768
_CTX_STEPS = (4096, 8192, 12288, 16384, 24576, 32768)


def chars_from_words(words: int | None, script: str) -> int | None:
    """Convert a word count to characters, or ``None`` where words mean nothing.

    An unsegmented script has no whitespace words, so its ``word_count`` is one giant
    token and multiplying it by anything produces a confident wrong number. Returning
    ``None`` there sends the caller down the unmeasured branch, which is the truth.
    """
    if not words or words <= 0 or script not in CHARS_PER_WORD:
        return None
    return int(words * CHARS_PER_WORD[script])


def recommend_num_ctx(
    *,
    p95_chars: int | None = None,
    p95_words: int | None = None,
    script: str = "latin",
    ram_gb: float | None = None,
    vram_mb: int | None = None,
    configured: int | None = None,
    headroom_frac: float = 0.25,
) -> dict:
    """Propose an Ollama ``num_ctx`` from the corpus and the machine.

    Mirrors vLLM's ``compute_server_args``: a stated heuristic, a stated caveat, and
    an operator override honoured verbatim. Two inputs, and BOTH may honestly be
    missing:

    * ``p95_chars`` — what the corpus needs, from the ``article_length`` diagnostic.
      Missing means we do not know what to cover, so nothing is proposed.
    * ``ram_gb`` / ``vram_mb`` — what the machine can afford. Missing means we cannot
      say what it can afford, and a proposal made anyway would be a number nobody
      measured.

    Either absence yields ``recommended: None`` with a reason — never a guessed
    value, and never silently the maximum.
    """
    method = (
        "cover the corpus's ~p95 article length plus prompt and answer reserve, then cap "
        f"by what the machine can hold at ~{KV_MB_PER_1K_TOKENS:.0f} MB of KV cache per 1k "
        f"tokens with {headroom_frac:.0%} headroom; rounded down to a standard step."
    )
    caveat = (
        "Both halves are ESTIMATES. Characters-per-token is a per-script rule of thumb, "
        "not a tokenizer, and the KV-cache figure is a rough model-class average. This "
        "is a starting point to measure from, not a guarantee — the operator override "
        "always wins."
    )
    derived_from_words = False
    if not p95_chars and p95_words:
        p95_chars = chars_from_words(p95_words, script)
        derived_from_words = p95_chars is not None
        if p95_chars is None:
            method += (
                " The corpus length came in WORDS for an unsegmented script, where a word "
                "count is one giant token — so it was not converted."
            )
    out: dict = {
        "recommended": None,
        "configured": configured,
        "method": method
        + (
            f" Article length was derived from the word-count p95 via ~"
            f"{CHARS_PER_WORD.get(script, 0):.0f} characters per word — an estimate on top "
            "of an estimate, stated rather than hidden."
            if derived_from_words
            else ""
        ),
        "caveat": caveat,
        "inputs": {
            "p95_chars": p95_chars,
            "p95_words": p95_words,
            "script": script,
            "ram_gb": ram_gb,
            "vram_mb": vram_mb,
        },
    }
    if not p95_chars or p95_chars <= 0:
        out["reason"] = (
            "the corpus's article-length distribution is unmeasured — run the "
            "article-length diagnostic first; a context sized without it would be a guess"
        )
        return out
    need = (
        estimate_tokens(int(p95_chars), script) + PROMPT_OVERHEAD_TOKENS + OUTPUT_RESERVE_TOKENS
    )
    out["needed_tokens_estimate"] = need

    afford_mb = None
    if vram_mb and vram_mb > 0:
        afford_mb = float(vram_mb) * (1.0 - headroom_frac)
        out["afford_basis"] = "VRAM"
    elif ram_gb and ram_gb > 0:
        afford_mb = float(ram_gb) * 1024.0 * (1.0 - headroom_frac)
        out["afford_basis"] = "system RAM"
    if afford_mb is None:
        out["reason"] = (
            "neither VRAM nor system RAM could be read, so what this machine can afford is "
            "UNMEASURED — no context is proposed rather than one guessed from nothing"
        )
        return out

    ceiling = int((afford_mb / KV_MB_PER_1K_TOKENS) * 1000)
    target = min(max(need, MIN_NUM_CTX), ceiling, MAX_NUM_CTX)
    # Round DOWN to a standard step: a value between steps buys nothing and makes two
    # machines' settings look meaningfully different when they are not.
    steps = [s for s in _CTX_STEPS if s <= target]
    out["recommended"] = steps[-1] if steps else MIN_NUM_CTX
    out["ceiling_tokens_estimate"] = ceiling
    if need > ceiling:
        out["reason"] = (
            f"the corpus wants ~{need} tokens but this machine affords ~{ceiling}; the "
            "recommendation is the machine's limit, so the longest articles will be "
            "truncated with disclosure rather than silently overflowing the window"
        )
    else:
        out["reason"] = "covers the corpus's ~p95 article within what the machine affords"
    return out


# --------------------------------------------------------------------------- #
#  Fitting text into the budget.
# --------------------------------------------------------------------------- #
def head_truncate(text: str, budget_chars: int) -> tuple[str, dict | None]:
    """Cut ``text`` to the budget and say so — the BACKGROUND-sweep path.

    Returns ``(text, disclosure_or_None)``. The disclosure is the point: an
    extraction over the first 6,000 characters of a 40,000-character article is not
    an extraction over the article, and a result that does not say so invites being
    read as one.
    """
    text = text or ""
    if budget_chars <= 0 or len(text) <= budget_chars:
        return text, None
    return text[:budget_chars], {
        "truncated": True,
        "analyzed_chars": budget_chars,
        "total_chars": len(text),
        "note": (
            f"analyzed the first {budget_chars} of {len(text)} characters — the rest was "
            "not seen by the model"
        ),
    }


_PARA = re.compile(r"(?<=\n\n)")
_SENT = re.compile(r"(?<=[.!?。！？])\s+")


def _split_after(pattern: re.Pattern[str], text: str) -> list[str]:
    """Split at the END of each match, keeping the separator with the piece before it.

    ``re.split`` CONSUMES the separator, so splitting on ``(?<=[.!?])\\s+`` silently
    drops the space between every sentence — a translation reassembled from those
    pieces comes back subtly wrong, and the loss is invisible unless something
    asserts exact coverage. Cutting at ``m.end()`` keeps the text intact.
    """
    out: list[str] = []
    last = 0
    for m in pattern.finditer(text):
        if m.end() > last:
            out.append(text[last : m.end()])
            last = m.end()
    if last < len(text):
        out.append(text[last:])
    return out


def _atoms(text: str, budget_chars: int) -> list[str]:
    """Split into pieces that CONCATENATE BACK to the input exactly.

    Paragraph boundaries first (they are where a translation may be cut without
    changing meaning), sentence ends next, and a hard cut only for a single sentence
    longer than the whole budget — which is a real case (a wall of text with no
    punctuation) and must not silently drop the overflow.
    """
    out: list[str] = []
    for para in _split_after(_PARA, text):
        if len(para) <= budget_chars:
            out.append(para)
            continue
        for sent in _split_after(_SENT, para):
            if len(sent) <= budget_chars:
                out.append(sent)
                continue
            for i in range(0, len(sent), budget_chars):
                out.append(sent[i : i + budget_chars])
    return [a for a in out if a]


def chunk_text(text: str, budget_chars: int) -> list[str]:
    """Split ``text`` into parts that each fit the budget and together ARE the text.

    ``"".join(chunk_text(t, n)) == t`` — the property the whole user-driven path
    rests on. A chunker that dropped a separator would lose content while looking
    like it had covered everything, which is precisely the failure this replaces.
    """
    text = text or ""
    if budget_chars <= 0 or len(text) <= budget_chars:
        return [text] if text else []
    chunks: list[str] = []
    current = ""
    for atom in _atoms(text, budget_chars):
        if current and len(current) + len(atom) > budget_chars:
            chunks.append(current)
            current = atom
        else:
            current += atom
    if current:
        chunks.append(current)
    return chunks


__all__ = [
    "CHARS_PER_TOKEN",
    "KV_MB_PER_1K_TOKENS",
    "LEGACY_TEXT_BUDGET_CHARS",
    "OUTPUT_RESERVE_TOKENS",
    "PROMPT_OVERHEAD_TOKENS",
    "chars_per_token",
    "chunk_text",
    "dominant_script",
    "estimate_tokens",
    "head_truncate",
    "recommend_num_ctx",
    "text_budget_chars",
]
