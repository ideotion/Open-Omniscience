"""
Grounding — can this sentence be traced back to the text it was given?

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Design record §7. Pure: no model, no DB, no network. This module never calls an
LLM — it JUDGES one, so that a sentence which cannot be traced to its evidence is
replaced by a deterministic template rather than published.

WHAT THIS CATCHES, and it is worth being exact about because the temptation is to
claim more: it catches INVENTED FACTS — a figure or a name that appears in a
generated sentence and nowhere in the text the model was handed. That is the
echo-back discipline already proven in the keyword-triage path, applied to prose.

WHAT IT DOES NOT CATCH: a sentence built entirely from real numbers and real
names, arranged into a false claim. Nothing mechanical catches that. The design
record says so, this docstring says so, and the payload says so — because a
validator that is quietly believed to do more than it does is worse than none.

TWO CHECKS, EACH WITH ITS OWN DENOMINATOR, and each reporting three states:

* **Numbers** — language-agnostic, always applicable. Every numeric literal in the
  sentence must appear in the evidence.
* **Capitalised names** — applicable ONLY in languages where an initial capital
  carries entity signal. It does not in German (every noun is capitalised), and it
  cannot in scripts with no case at all. Running it there would manufacture
  failures out of ordinary prose, and a fabricated FAIL is exactly as dishonest as
  a fabricated pass — the recorded lesson from the perception gate. Where it does
  not apply, it reports so; it never silently passes.

A check with nothing to test (a sentence with no numbers) is ``None`` —
UNMEASURED — not a pass. The overall verdict treats an unmeasured check as
neither support nor objection, and says which checks actually ran.
"""

from __future__ import annotations

import re
import unicodedata

#: A numeric literal: digits, with optional grouping separators and a decimal part.
#: Percent/currency symbols are not part of the number — "62%" yields "62", which is
#: what must be found in the evidence.
_NUMBER_RE = re.compile(r"\d[\d .,\s]*\d|\d")

#: A run of capitalised words — "European Commission", "Storm Fiona". Requires the
#: run to be at least one token of >= 2 characters so a stray initial is not a name.
_CAP_RUN_RE = re.compile(r"\b[A-ZÀ-Þ][\wÀ-ɏ'’-]+(?:\s+[A-ZÀ-Þ][\wÀ-ɏ'’-]+)*")

#: Languages where an initial capital carries entity signal. German is DELIBERATELY
#: absent: it capitalises every noun, so the check would flag ordinary prose. Scripts
#: without case (zh, ja, ko, ar, he, th, hi, bn…) are absent for the same reason —
#: there is nothing for the check to read, which is a gap, not a pass.
CASE_LANGUAGES: frozenset[str] = frozenset(
    {"en", "fr", "es", "pt", "it", "nl", "sv", "da", "no", "fi", "pl", "cs", "ro", "id", "tr"}
)

#: Words that begin a sentence and are capitalised for that reason alone. Only the
#: FIRST token of a sentence is exempt, so a name that happens to open a sentence is
#: not checked — an under-check, chosen over flagging every sentence's first word.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _fold(s: str) -> str:
    """Case-fold and strip accents for a forgiving containment match.

    The same forgiveness the triage echo-back uses: a model that writes "Ukraine"
    where the evidence says "ukraine" has not invented anything, and failing it
    would be a fabricated failure.
    """
    return "".join(
        c for c in unicodedata.normalize("NFKD", s.casefold()) if not unicodedata.combining(c)
    )


def normalise_number(raw: str) -> str:
    """A numeric literal reduced to a comparable form.

    Grouping separators are dropped so "1,240" / "1 240" / "1240" compare equal; a
    decimal point is KEPT so "6.1" can never satisfy a claim about "61". The
    ambiguity is real — some locales group with "." and decimalise with "," — so
    the rule is stated rather than guessed: a separator followed by exactly three
    digits at the end of a group is grouping; anything else is a decimal point.
    """
    s = raw.strip().replace(" ", "").replace(" ", "")
    # Normalise the decimal mark: the LAST separator is a decimal point only when it
    # is not followed by exactly three digits.
    m = re.search(r"[.,](\d+)$", s)
    if m and len(m.group(1)) != 3:
        head, tail = s[: m.start()], m.group(1)
        return re.sub(r"[.,]", "", head) + "." + tail
    return re.sub(r"[.,]", "", s)


def numbers_in(text: str) -> list[str]:
    """Every numeric literal in ``text``, normalised, in order of appearance."""
    out: list[str] = []
    for m in _NUMBER_RE.finditer(text or ""):
        n = normalise_number(m.group(0))
        if n and n not in out:
            out.append(n)
    return out


def capitalised_runs(text: str) -> list[str]:
    """Capitalised word runs, excluding each sentence's first token.

    Sentence-initial capitals are excluded because they are grammar, not names.
    That under-checks a name that opens a sentence, which is the right direction:
    the alternative flags every sentence's first word and drowns the real signal.
    """
    out: list[str] = []
    for part in _SENTENCE_SPLIT.split(text or ""):
        part = part.strip()
        if not part:
            continue
        for m in _CAP_RUN_RE.finditer(part):
            run = m.group(0).strip()
            if m.start() == 0:
                # Sentence-initial. Drop the FIRST word only — it is capitalised by
                # grammar — and keep whatever follows. Skipping the whole run here
                # discarded the name with it: "The Bavarian Assembly" yielded
                # nothing at all, so an invented body opening a sentence was never
                # checked. A run that is only its first word is grammar, not a name.
                tokens = run.split()
                if len(tokens) < 2:
                    continue
                run = " ".join(tokens[1:])
            if len(run) >= 2 and run not in out:
                out.append(run)
    return out


def check_sentence(sentence: str, evidence: str, *, language: str | None = None) -> dict:
    """Can every checkable claim in ``sentence`` be found in ``evidence``?

    Returns::

        {
          "supported": True | False,
          "checks": {"numbers": {...}, "names": {...}},
          "unsupported": [...],       # what could not be found
          "method": str, "caveat": str,
        }

    Each check reports ``applied`` (did it run), ``passed`` (True/False/None) and
    a reason. ``None`` is UNMEASURED — nothing to test, or the check does not apply
    to this language — and is never counted as support.

    ``supported`` is False if ANY applied check failed. A sentence where no check
    applied at all is ``supported: True`` with ``checks_applied: []`` — and the
    caller must read that as "nothing objected", not "verified". The payload states
    it; ``checks_applied`` is there precisely so a caller cannot conflate them.
    """
    ev = _fold(evidence or "")
    checks: dict[str, dict] = {}
    unsupported: list[str] = []

    nums = numbers_in(sentence)
    if not nums:
        checks["numbers"] = {
            "applied": False,
            "passed": None,
            "reason": "the sentence states no figure — nothing to check",
        }
    else:
        missing = [n for n in nums if n not in _fold(_normalised_evidence_numbers(evidence))]
        checks["numbers"] = {
            "applied": True,
            "passed": not missing,
            "found": [n for n in nums if n not in missing],
            "missing": missing,
            "reason": (
                "every figure appears in the evidence"
                if not missing
                else f"figure(s) not in the evidence: {', '.join(missing)}"
            ),
        }
        unsupported.extend(missing)

    lang = (language or "").split("-", 1)[0].strip().lower()
    if lang not in CASE_LANGUAGES:
        checks["names"] = {
            "applied": False,
            "passed": None,
            "reason": (
                f"capitalisation carries no entity signal in {lang or 'an unstated language'} — "
                "not checked, and NOT thereby cleared"
            ),
        }
    else:
        runs = capitalised_runs(sentence)
        if not runs:
            checks["names"] = {
                "applied": False,
                "passed": None,
                "reason": "the sentence names nothing — nothing to check",
            }
        else:
            missing = [r for r in runs if _fold(r) not in ev]
            checks["names"] = {
                "applied": True,
                "passed": not missing,
                "found": [r for r in runs if r not in missing],
                "missing": missing,
                "reason": (
                    "every name appears in the evidence"
                    if not missing
                    else f"name(s) not in the evidence: {', '.join(missing)}"
                ),
            }
            unsupported.extend(missing)

    applied = [k for k, v in checks.items() if v["applied"]]
    failed = [k for k in applied if checks[k]["passed"] is False]
    return {
        "supported": not failed,
        "checks": checks,
        "checks_applied": applied,
        "unsupported": unsupported,
        "method": (
            "echo-back grounding: every figure, and every capitalised name where "
            "capitalisation carries entity signal, must appear in the evidence text "
            "the model was given"
        ),
        "caveat": (
            "This catches INVENTED facts — a figure or name that is in the sentence and "
            "not in the evidence. It does NOT catch a sentence built from real figures "
            "and real names arranged into a false claim; nothing mechanical does. "
            "An empty checks_applied means nothing objected, which is not the same as "
            "verified."
        ),
    }


def _normalised_evidence_numbers(evidence: str) -> str:
    """The evidence with its own numbers normalised, so grouping style cannot
    cause a false failure — "1,240" in the sentence must match "1240" in the text."""
    return " ".join(numbers_in(evidence or "")) + " " + (evidence or "")


def run_grounding_selftest() -> dict:
    """Deterministic mechanism proof. No model, no DB, no network.

    Registered in ``src.monitoring.recursive_loop.LOOP_SELFTESTS``.

    SHAPE CONTRACT: ``recursive_loop._selftest_passed`` reads a top-level ``passed``
    BOOL (or a ``summary.failed`` int) and reports None — "shape not recognized",
    never a fabricated green — for anything else.
    """
    cases: list[dict] = []

    def _case(name: str, got, want) -> None:
        cases.append({"name": name, "passed": got == want, "got": got, "want": want})

    ev = "The corpus holds 1,240 articles about the European Commission this week."

    _case(
        "an invented figure is caught",
        check_sentence("Coverage reached 9,912 articles.", ev, language="en")["supported"],
        False,
    )
    _case(
        "a real figure passes across grouping styles",
        check_sentence("Coverage reached 1240 articles.", ev, language="en")["supported"],
        True,
    )
    _case(
        "an invented name is caught",
        check_sentence("It cited the Bavarian Assembly.", ev, language="en")["supported"],
        False,
    )
    _case(
        "a real name passes",
        check_sentence("It cited the European Commission.", ev, language="en")["supported"],
        True,
    )
    _case(
        "a decimal never satisfies a claim about its digits",
        check_sentence("Magnitude 6.1 was recorded.", "a magnitude of 61 was recorded", language="en")[
            "supported"
        ],
        False,
    )
    de = check_sentence("Die Kommission nannte Zahlen.", "etwas anderes", language="de")
    _case("German skips the name check rather than flagging every noun", de["checks"]["names"]["applied"], False)
    _case("and the skip is not a pass", de["checks"]["names"]["passed"], None)
    zh = check_sentence("报道提到了政策。", "别的内容", language="zh")
    _case("a caseless script skips the name check", zh["checks"]["names"]["applied"], False)
    _case(
        "a sentence with nothing checkable reports which checks ran",
        check_sentence("Coverage grew.", ev, language="en")["checks_applied"],
        [],
    )
    _case(
        "a sentence-initial capital is not treated as a name",
        capitalised_runs("Coverage grew sharply."),
        [],
    )
    # ...but the name AFTER it still is. The first cut skipped the whole run when it
    # began at the sentence start, so "The Bavarian Assembly" yielded nothing and an
    # invented body opening a sentence went unchecked. The selftest missed it because
    # its invented-name case sat mid-sentence; this is that gap, closed.
    _case(
        "a name following a sentence-initial word is still checked",
        capitalised_runs("The Bavarian Assembly responded."),
        ["Bavarian Assembly"],
    )
    _case(
        "and an invented one opening a sentence is caught",
        check_sentence("The Bavarian Assembly responded.", ev, language="en")["supported"],
        False,
    )
    _case("grouping separators normalise", normalise_number("1 240"), "1240")
    _case("a decimal mark survives", normalise_number("6.1"), "6.1")
    _case("a thousands dot normalises", normalise_number("1.240"), "1240")

    passed = all(c["passed"] for c in cases)
    return {
        "schema": "oo-bulletin-grounding-selftest-1",
        "cases": cases,
        "passed": passed,
        "passed_count": sum(1 for c in cases if c["passed"]),
        "failed_count": sum(1 for c in cases if not c["passed"]),
        "method": "deterministic assertions over the grounding checks; no model, no DB",
        "caveat": (
            "Proves the checks fire and abstain where they should. It says nothing about "
            "whether any particular model's prose is trustworthy — that is what the "
            "checks are for."
        ),
    }
