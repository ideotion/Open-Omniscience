"""The shared linear block stripper, and the K*N shape it replaces.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``OPEN.*?CLOSE`` over untrusted markup is a K*N bomb: an opener with no closer
makes the lazy ``.*?`` scan to end-of-document, fail, and restart from the NEXT
opener. The recorded 2026-08-05 lesson fixed it in the HTML path and asked for the
shape to be grepped rather than waited for; it was still live in
``plain_from_wikitext`` in three patterns, on the path every watched-page sync and
every dump ingest runs through.

The load-bearing guard here is the DIFFERENTIAL: the fix is only a fix if it
changes nothing about the output. Everything else measures the cliff.
"""

from __future__ import annotations

import random
import re
import time

import pytest

from src.utils.markup_blocks import strip_blocks, strip_one_block
from src.wiki.corpus import plain_from_wikitext

_REF_OPEN = re.compile(r"<ref[^>]*>", re.IGNORECASE)
_REF_CLOSE = re.compile(r"</ref>", re.IGNORECASE)


def _old_refs(t: str) -> str:
    """The pattern this replaces, kept so the differential has something to be
    different from. Not imported from anywhere -- it no longer exists in src."""
    return re.sub(r"<ref[^>]*>.*?</ref>", " ", t, flags=re.S | re.I)


def _new_refs(t: str) -> str:
    return strip_one_block(t, _REF_OPEN, _REF_CLOSE)


# --------------------------------------------------------------------------- #
# the differential: the output must not move
# --------------------------------------------------------------------------- #

_ATOMS = [
    "word ", "Lorem ipsum. ", "\n", "\n\n", "== Heading ==\n", "* item\n",
    "<ref>", "</ref>", "<ref name=x>", "<REF>", "</REF>", "<ref/>",
    "<!--", "-->", "{|", "|}", "{{tpl}}", "[[Link]]", "|", "<", ">", "-",
    "!", "{", "}", "[https://x label]", "'''bold'''",
]


def _docs(seed: int, n: int):
    rng = random.Random(seed)
    for _ in range(n):
        yield "".join(rng.choice(_ATOMS) for _ in range(rng.randint(1, 60)))


def test_the_linear_scanner_is_byte_identical_to_the_pattern_it_replaces():
    """5,000 documents built from wikitext atoms, both implementations, no drift.

    ANTI-VACUITY: the count of documents the strip actually CHANGED is asserted,
    because a generator that happened to emit no ``<ref>`` at all would make every
    comparison ``x == x`` and the test would pass while proving nothing.
    """
    changed = 0
    for doc in _docs(20260907, 5000):
        old = _old_refs(doc)
        assert old == _new_refs(doc), f"drift on {doc!r}"
        if old != doc:
            changed += 1
    assert changed > 1000, f"only {changed} documents exercised the strip -- fixture too tame"


@pytest.mark.parametrize(
    "doc",
    [
        "", "no markup at all",
        "a<ref>b</ref>c", "a<ref>b</ref>c<ref>d</ref>e",
        # nesting: both take the FIRST closer, so the spans agree
        "a<ref>b<ref>c</ref>d",
        # the unclosed cases -- the whole point, and where the two must still agree
        "a<ref>unclosed b", "a</ref>b", "<ref>x" * 5,
        "<ref name='x'>y</ref>", "<REF>y</REF>", "a<Ref>b</rEf>c",
        # an opener retired mid-document must not swallow what precedes a later one
        "keep me <ref>a</ref> keep me too <ref>never closed and this must survive",
    ],
)
def test_the_boundary_shapes_agree(doc):
    assert _old_refs(doc) == _new_refs(doc)


def test_an_unchanged_document_is_returned_unchanged_and_identical():
    """Callers hold offsets into the body, so a no-op must be a true no-op.

    MUTATION NOTE, recorded so it is not re-chased: the obvious mutants for this
    guard are EQUIVALENT rather than surviving. CPython returns the same object
    for ``str(x)``, ``x[:]`` and ``"".join([x])`` on an exact ``str``, so all
    three keep ``is`` true and this test passes correctly. ``(x + " ")[:-1]`` is
    a genuinely different object and does redden it.
    """
    doc = "plain text with no blocks at all"
    assert strip_one_block(doc, _REF_OPEN, _REF_CLOSE) is doc


def test_a_retired_family_does_not_swallow_the_text_before_a_later_opener():
    """The two-cursor rule, stated as behaviour.

    Advancing the COPY cursor past a retired opener (rather than only the SCAN
    cursor) silently deletes everything between it and the previous copy point --
    the bug a randomised differential caught in the first draft of the HTML
    version, and one no "does it crash" test can see.
    """
    doc = "ALPHA <ref>closed</ref> BRAVO <ref>never closed CHARLIE"
    out = strip_one_block(doc, _REF_OPEN, _REF_CLOSE)
    for survivor in ("ALPHA", "BRAVO", "CHARLIE"):
        assert survivor in out, f"{survivor} was swallowed: {out!r}"
    assert "closed</ref>" not in out


def test_two_families_retire_independently():
    """One exhausted family must not silence another still capable of closing."""
    open_re = re.compile(r"<(ref|note)>")
    closers = {"ref": re.compile(r"</ref>"), "note": re.compile(r"</note>")}
    # NOTE the token: a bare "c" would have been satisfied by the "c" inside
    # "unclosed" -- the non-unique-needle trap, caught by this test failing
    # against correct code.
    doc = "ALPHA<ref>never closed BRAVO<note>NOTEBODY</note>DELTA"
    out = strip_blocks(doc, open_re, lambda m: closers[m.group(1)])
    assert "NOTEBODY" not in out and "</note>" not in out, "the note block should be gone"
    assert "<ref>" in out and "BRAVO" in out and "DELTA" in out


def test_one_family_retires_across_its_spelling_variants():
    """`<ref>` and `<REF name=x>` are one family: retiring must be keyed on the
    CLOSER, or a document alternating spellings pays a scan per opener again."""
    doc = "<ref>a<REF name=x>b<Ref>c"   # no closer anywhere
    out = strip_one_block(doc, _REF_OPEN, _REF_CLOSE)
    assert out == doc


def test_two_closers_sharing_a_source_string_but_not_their_flags_are_two_families():
    """The flags belong in the exhaustion key, and this is why.

    No caller in the tree can exhibit it today -- ``strip_one_block`` passes one
    closer, and the HTML site's two closers have different source strings -- so the
    mutation that drops ``closer.flags`` survives every other test here. That makes
    it a finding about the MUTANT's reachability, not about the guards... except
    that ``strip_blocks`` is a PUBLIC primitive whose contract says families are
    kept separate, and a future caller can reach it in one line. So it is tested
    against the contract rather than against today's callers.
    """
    opener = re.compile(r"<(a|b)>")
    ci = re.compile(r"</x>", re.IGNORECASE)
    cs = re.compile(r"</x>")            # same source, different flags: another family
    # Only `</X>` exists, so the case-SENSITIVE family (b) can never close and the
    # case-INSENSITIVE one (a) can. Sharing one key retires both on b's failure.
    doc = "P<b>never closed Q<a>gone</X>R"
    out = strip_blocks(doc, opener, lambda m: cs if m.group(1) == "b" else ci)
    assert "gone" not in out, (
        "the case-insensitive family can still close on </X> and must not be retired "
        "by its case-sensitive namesake"
    )
    assert "P" in out and "Q" in out and "R" in out and "<b>" in out


def test_retirement_survives_openers_that_are_all_TEXTUALLY_DIFFERENT():
    """The property Q3 exposed, and the one real wikitext actually exhibits.

    Keying exhaustion on the OPENER's text instead of the closer produces
    IDENTICAL OUTPUT -- nothing is removed either way when no closer exists -- so
    no correctness assertion can see it, and a scaling fixture built from ONE
    repeated opener cannot either, because one opener text is one key whichever
    way it is keyed. Real refs carry distinct ``name=`` attributes, so every
    opener is its own key and the retirement stops working exactly where it
    matters. The fixture therefore makes every opener textually unique.
    """
    def doc_of(n_openers: int) -> str:
        return "".join(f"Lorem ipsum dolor sit amet <ref name=n{i}>body " for i in range(n_openers))

    ts = []
    for n in (2000, 8000):
        d = doc_of(n)
        ts.append(max(_time(strip_one_block, d, _REF_OPEN, _REF_CLOSE), 1e-6))
    ratio = ts[1] / ts[0]
    assert ratio < 8, (
        f"4x the openers cost {ratio:.1f}x the time -- exhaustion is keyed on the opener, "
        "so each distinct spelling re-scans the whole document"
    )


# --------------------------------------------------------------------------- #
# the cliff, on the REAL function
# --------------------------------------------------------------------------- #


# Repeats, and the MINIMUM of them, because the thing being timed is small enough
# that the runner can dominate it. Measured 2026-09-11 on a 4-core container: this
# module's 400,000-char case runs ~3 ms, so ONE scheduler preemption lands on one of
# the two measurements and moves the ratio by however long the preemption was. With
# four busy cores alongside, a single timing produced a median ratio of 5.31 and a MAX
# of 17.53 -- above the bar, and above the 15.9x this file cites as the signature of
# the quadratic scan itself, on code that is provably linear. That is the worst thing a
# guard test can do: present, as evidence for its own alarm, a number indistinguishable
# from the real defect. Best-of-3 under the same contention: median 4.15, max 4.61, zero
# failures in 15. The minimum is the run least disturbed by anything else on the box, and
# it changes nothing about WHAT is measured -- an algorithm that really is quadratic is
# quadratic on its best run too, so the guard keeps its teeth.
_TIMING_REPEATS = 3


def _time(fn, *a):
    best = float("inf")
    for _ in range(_TIMING_REPEATS):
        t0 = time.perf_counter()
        fn(*a)
        best = min(best, time.perf_counter() - t0)
    return best


def _scaling(fn, unit: str, small: int = 100_000, factor: int = 4) -> float:
    """How the cost grows when the input grows ``factor``x. ~factor = linear,
    ~factor**2 = a scan per opener.

    A RATIO, not an absolute second count: an absolute bar would be a bet on this
    runner's speed, while the defect is that the two diverge by an order of
    magnitude. Measured before the fix, `<ref>` spam scaled 15.9x for a 4x input.
    """
    ts = []
    for n in (small, small * factor):
        doc = (unit * (n // len(unit) + 1))[:n]
        ts.append(max(_time(fn, doc), 1e-6))
    return ts[1] / ts[0]


@pytest.mark.parametrize(
    "unit",
    [
        "Lorem ipsum dolor sit amet. <ref>a citation ",
        "Lorem ipsum dolor sit amet. {| class=wikitable ",
        "Lorem ipsum dolor sit amet. <!-- a comment ",
    ],
)
def test_an_unclosed_block_opener_no_longer_costs_a_scan_per_opener(unit):
    """The property, at the primitive: LINEAR in the input, not quadratic.

    Driven through ``strip_one_block`` rather than through the whole wiki strip,
    and that is deliberate rather than convenient -- see the test below, which
    records why the end-to-end claim is true for two of the three shapes and not
    yet for the third.
    """
    families = {
        "<ref": (re.compile(r"<ref[^>]*>", re.IGNORECASE), re.compile(r"</ref>", re.IGNORECASE)),
        "{|": (re.compile(r"\{\|"), re.compile(r"\|\}")),
        "<!--": (re.compile(r"<!--"), re.compile(r"-->")),
    }
    key = next(k for k in families if k in unit)
    opener, closer = families[key]
    ratio = _scaling(lambda d: strip_one_block(d, opener, closer), unit)
    assert ratio < 8, f"4x the input cost {ratio:.1f}x the time -- the quadratic scan is back"


def test_the_wiki_strip_is_linear_on_EVERY_shape_that_reaches_it():
    """END-TO-END, and now for all of them (2026-09-09).

    This test used to claim exactly TWO shapes, because ``plain_from_wikitext``
    ran seven more patterns after these blocks and SIX carried the same class in a
    different disguise -- ``OPEN[^X]*CLOSE``, where an opener with no closer makes
    the character class consume to end-of-document and then backtrack. They were
    the expensive half, measured 100,000 -> 200,000 chars of opener-only spam at
    up to 14.9 s -> 59.3 s through the whole strip.

    All six now go through ``markup_blocks.sub_anchored``, and so does the ``<ref
    …>`` block OPENER, which was carrying the shape INSIDE the function written to
    remove it (``strip_blocks`` calls ``.search`` with it) and kept the end-to-end
    ref shape quadratic after the six substitutions were fixed -- found only
    because this test was widened rather than trusted.

    Measured after: 59.282 s -> 0.0137 s on the worst shape, and every one of the
    eight below scales linearly. The comment shape is no longer excluded: its
    downstream ``<[^>]+>`` is linear now too.
    """
    for unit in (
        "Lorem ipsum dolor sit amet. <ref>a citation ",
        "Lorem ipsum dolor sit amet. {| class=wikitable ",
        "Lorem ipsum dolor sit amet. <!-- a comment ",
        "Lorem ipsum dolor sit amet. <ref name=a ",
        "Lorem ipsum dolor sit amet. <a ",
        "Lorem ipsum dolor sit amet. [[File x ",
        "Lorem ipsum dolor sit amet. [[a|b ",
        "Lorem ipsum dolor sit amet. [[a ",
        "Lorem ipsum dolor sit amet. [https://x y ",
        "Lorem ipsum dolor sit amet. [https://x ",
    ):
        ratio = _scaling(plain_from_wikitext, unit, small=50_000)
        assert ratio < 8, (
            f"{unit!r}: 4x the input cost {ratio:.1f}x the time through the whole strip"
        )


def test_the_wiki_strip_still_strips_what_it_always_stripped():
    """The differential above compares one pattern; this pins the whole pipeline's
    OUTPUT, so a change to the order or the replacement string cannot hide."""
    body = (
        "<!--hidden-->Intro '''bold''' text.\n"
        "<ref name=a>a citation</ref>Body about [[Kenya|Kenyan]] elections.\n"
        "{| class=wikitable\n| cell |}\n"
        "{{Infobox|x=1}}[[File:pic.jpg|thumb]]== Heading ==\n"
        "See [https://example.org/x the source]."
    )
    out = plain_from_wikitext(body)
    for gone in ("hidden", "a citation", "cell", "Infobox", "pic.jpg", "'''", "<ref"):
        assert gone not in out, f"{gone!r} survived the strip: {out!r}"
    for kept in ("Intro", "bold", "Kenyan", "elections", "Heading", "the source"):
        assert kept in out, f"{kept!r} was lost by the strip: {out!r}"


def test_the_wiki_strip_contains_no_lazy_block_regex_at_all():
    """The WIRING, as a property rather than a call site.

    Q7 of the mutation matrix reverted the COMMENT strip to its lazy regex and
    nothing reddened: the primitive's own scaling test drives ``strip_one_block``
    directly, and the end-to-end test deliberately excludes the comment shape
    (its downstream ``<[^>]+>`` is quadratic for an unrelated reason). That is the
    recorded "a test of a helper is not a test of its wiring" gap.

    Asserting the three call sites by name would pin today's spelling; asserting
    that the function contains NO ``.*?`` regex at all pins the RULE, catches any
    of the three reverting, and stays true through a rename. Read from the AST's
    string constants, so a comment explaining the rule cannot satisfy it.
    """
    import ast
    import pathlib

    src = pathlib.Path("src/wiki/corpus.py").read_text(encoding="utf-8")
    fn = next(
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.FunctionDef) and n.name == "plain_from_wikitext"
    )
    # SCOPE, and it had to be got right rather than relaxed: the first draft
    # flagged any `.*?` and fired on `^=+\s*(.*?)\s*=+\s*$`, the HEADING strip,
    # which is CORRECT code -- it carries re.M and not re.S, so `.` never crosses a
    # newline and the scan is bounded by one line. The quadratic class is a lazy
    # `.*?` that can span the WHOLE document, which is exactly `.*?` + DOTALL. So
    # the flags are read from the call, not guessed from the pattern's shape.
    # STATED LIMIT: a lazy `.*?` without DOTALL over a single pathologically long
    # line is still super-linear in that line; wikitext lines are bounded in
    # practice and this guard does not claim otherwise.
    def _dotall(call: ast.Call) -> bool:
        flags = next((kw.value for kw in call.keywords if kw.arg == "flags"), None)
        if flags is None and len(call.args) >= 4:
            flags = call.args[3]
        return flags is not None and any(
            isinstance(n, ast.Attribute) and n.attr in ("S", "DOTALL")
            for n in ast.walk(flags)
        )

    offenders = [
        n.args[0].value
        for n in ast.walk(fn)
        if isinstance(n, ast.Call)
        and getattr(getattr(n.func, "value", None), "id", "") == "re"
        and getattr(n.func, "attr", "") in ("sub", "compile", "search", "findall")
        and n.args
        and isinstance(n.args[0], ast.Constant)
        and isinstance(n.args[0].value, str)
        and ".*?" in n.args[0].value
        and _dotall(n)
    ]
    assert not offenders, (
        f"plain_from_wikitext carries a lazy-any block regex again: {offenders}. "
        "An OPEN.*?CLOSE over untrusted markup costs a scan per opener; use "
        "src.utils.markup_blocks.strip_blocks."
    )
    calls = sum(
        1 for n in ast.walk(fn)
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "strip_one_block"
    )
    assert calls == 3, f"expected the three block families to go through the scanner, found {calls}"


# --------------------------------------------------------------------------- #
# the guard on the guard
# --------------------------------------------------------------------------- #
def test_the_scaling_harness_still_catches_a_genuinely_quadratic_scan():
    """ANTI-VACUITY for ``_time``'s repeats, which are otherwise free to delete.

    ``_time`` takes the MINIMUM of ``_TIMING_REPEATS`` runs rather than timing once,
    because the timed work is ~3 ms and a single scheduler preemption on a busy runner
    moved the ratio past the bar -- to a measured max of 17.53 on provably linear code,
    which is ABOVE the 15.9x this file cites as the quadratic signature (2026-09-11).

    The obvious worry about a minimum is that it flatters: take enough runs and
    everything looks fast. It does not, because the defect is not a slow CONSTANT, it is
    a slow SHAPE -- an algorithm that re-scans the document per opener does so on its
    best run too, and the ratio between two sizes is what this file asserts. Measured
    both ways, quiet and under four busy cores: linear 0/9 over the bar in each
    condition, quadratic 5/5 over it in each, minimum ratio 10.72.

    So this test fails if the repeats are removed (they are the fix) OR if the harness
    stops being able to see a quadratic (it would then be asserting nothing at all).
    """
    assert _TIMING_REPEATS >= 3, (
        "_time takes the minimum of its repeats to survive a busy runner; dropping "
        "below 3 restores the false 'the quadratic scan is back' this fixed"
    )

    opener, closer = re.compile(r"\{\|"), re.compile(r"\|\}")

    def a_scan_per_opener(doc: str) -> int:
        """Exactly the defect the module exists to remove: search to end-of-document
        once per opener, instead of resuming the scan where the last one ended."""
        return sum(1 for m in opener.finditer(doc) if closer.search(doc, m.end()))

    ratio = _scaling(a_scan_per_opener, "Lorem ipsum dolor sit amet. {| class=wikitable ",
                     small=20_000)
    assert ratio >= 8, (
        f"a deliberately quadratic scan measured {ratio:.1f}x for 4x the input and would "
        "have PASSED the bar -- the scaling harness has stopped measuring anything"
    )
