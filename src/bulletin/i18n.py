"""
The bulletin's own translation layer — server-side, because the document is text.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY NOT THE FRONTEND ENGINE. ``i18n.js`` translates the DOM: it walks text nodes
and matches each against a locale key. A bulletin is a Markdown or HTML FILE that
leaves this machine — there is no DOM to walk and no browser to walk it — so the
sentences have to be resolved where they are composed.

THE KEY IS THE ENGLISH SENTENCE, exactly as the DOM walker's is. That choice is
what let this ship at all: the nine modules that COMPUTE an edition store their
method and caveat prose as plain strings in the record, and the renderer prints
them. Keying on the English text means every one of those becomes translatable by
wrapping the PRINT site, with no change to the producers and no second copy of the
prose to keep in step.

FOUR RULES, each of which exists because its absence would publish something
untrue:

* **English is byte-identical.** ``lang="en"`` returns the input unchanged. The
  document an operator has today cannot change because a translation layer was
  added under it.
* **A missing translation is English AND is recorded.** Never a machine guess,
  never an empty string, never a key rendered raw. ``report()`` names every gap,
  which is what the bulletin-language diagnostic hands back.
* **A translation whose placeholders differ from the template is REFUSED.** A
  frame that loses ``{days}``, or gains a ``{jours}`` nothing will fill, renders a
  literal brace to a reader. English is used and the entry is reported as an
  error, because a broken frame is worse than an absent one.
* **An entry identical to its English is counted apart.** A catalog that copies
  the source language would otherwise report full coverage — a fabricated pass on
  work nobody did. Some identities are legitimate (a proper noun, a unit), so
  they are counted rather than rejected, and the count is published.

WHAT IS NEVER TRANSLATED: the corpus. A source's own title, an author, a
publisher's words, a keyword extracted from someone else's text — those are DATA.
Translating an article is a model's job, it is offered as phase 2, and it is
labelled AI-derived wherever it appears. This layer moves only the sentences this
app wrote itself.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

#: Where a catalog lives. One flat JSON object per locale: English → translation.
CATALOG_DIR = Path(__file__).resolve().parents[2] / "configs" / "bulletin_i18n"

#: The twelve the UI ships. A request outside this set is honoured if a catalog
#: exists (nothing here forbids a thirteenth) but the diagnostic reports over these.
UI_LANGS: tuple[str, ...] = (
    "en", "fr", "de", "es", "pt", "ru", "ar", "zh", "ja", "hi", "bn", "id",
)

_PLACEHOLDER = re.compile(r"\{(\w+)\}")

# (mtime, size, catalog) per language file, so an operator editing a catalog sees
# it on the next render without a restart, and a render never re-reads unchanged.
_CACHE: dict[str, tuple[float, int, dict[str, str]]] = {}


def catalog_path(lang: str) -> Path:
    return CATALOG_DIR / f"{_norm(lang)}.json"


def _norm(lang: Any) -> str:
    """A bare language code. ``fr-CA`` and ``FR`` are French.

    The house convention is store-raw / normalise-on-read, and a locale that
    arrives with a region subtag must not silently miss a catalog that exists.
    """
    s = str(lang or "en").strip().lower().replace("_", "-")
    return s.split("-", 1)[0] or "en"


def load_catalog(lang: str) -> dict[str, str]:
    """The catalog for ``lang``, or an empty one. Never raises.

    A missing file is the normal state of an unstarted locale, and a malformed one
    is an operator's editing mistake — neither may take a document down. Both come
    back empty, and the report says the catalog was empty, so a reader of the
    diagnostic can tell "nobody has translated this yet" from "it is translated".
    """
    code = _norm(lang)
    if code == "en":
        return {}
    path = catalog_path(code)
    try:
        st = path.stat()
    except OSError:
        _CACHE.pop(code, None)
        return {}
    hit = _CACHE.get(code)
    if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
        return hit[2]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {
        str(k): str(v)
        for k, v in (raw.items() if isinstance(raw, dict) else [])
        if isinstance(k, str) and isinstance(v, str) and v.strip()
    }
    _CACHE[code] = (st.st_mtime, st.st_size, out)
    return out


class _Missing(dict):
    """A format mapping that leaves an unknown placeholder visibly unresolved.

    A ``KeyError`` here would abort a whole render over one sentence. Leaving the
    brace makes the fault visible in the output AND catchable: the diagnostic's
    render-integrity pass fails a document that still contains ``{word}``, so this
    degrades loudly rather than quietly dropping a value.
    """

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


class Translator:
    """Resolve this app's own sentences into one language, and record the gaps.

    Stateful ON PURPOSE. A render asks for a few hundred sentences and the
    interesting output is not only the text — it is which sentences had no
    translation, which had a broken one, and how much of the document that is. A
    caller renders with one instance and then reads ``report()``.
    """

    def __init__(self, lang: str = "en") -> None:
        self.requested = str(lang or "en")
        self.lang = _norm(lang)
        self.catalog = load_catalog(self.lang)
        self._seen: dict[str, None] = {}
        self._hit: dict[str, None] = {}
        self._same: dict[str, None] = {}
        self._rejected: dict[str, str] = {}
        self._unresolved: dict[str, None] = {}
        # Every hole name any frame declared. The integrity check needs exactly this
        # set: a brace in the output whose name is one of OURS is a value that never
        # arrived, while a brace a source happened to publish is not our bug. Derived
        # from the frames themselves rather than from the output, because a set built
        # from the output would contain every brace in it and could exclude nothing.
        self._holes: set[str] = set()

    # -- resolution ------------------------------------------------------- #

    @property
    def is_english(self) -> bool:
        return self.lang == "en"

    def t(self, text: Any) -> str:
        """One whole sentence, keyed on itself. English in, chosen language out."""
        s = "" if text is None else str(text)
        if not s.strip():
            return s
        self._seen.setdefault(s, None)
        if self.is_english:
            return s
        got = self.catalog.get(s)
        if got is None:
            return s
        if got == s:
            self._same.setdefault(s, None)
            return s
        self._hit.setdefault(s, None)
        return got

    def f(self, template: str, /, **values: Any) -> str:
        """A sentence FRAME with ``{named}`` holes, translated then filled.

        The frame is keyable because it is fixed; the values are data and are
        interpolated after translation, so a number never reaches a catalog and a
        translator never has to guess what will land in a hole.
        """
        self._seen.setdefault(template, None)
        self._holes.update(_PLACEHOLDER.findall(template))
        frame = template
        if not self.is_english:
            got = self.catalog.get(template)
            if got is not None:
                if got == template:
                    self._same.setdefault(template, None)
                elif set(_PLACEHOLDER.findall(got)) != set(_PLACEHOLDER.findall(template)):
                    self._rejected[template] = (
                        "placeholders differ: expected "
                        f"{sorted(set(_PLACEHOLDER.findall(template)))}, "
                        f"got {sorted(set(_PLACEHOLDER.findall(got)))}"
                    )
                else:
                    self._hit.setdefault(template, None)
                    frame = got
        try:
            return frame.format_map(_Missing(values))
        except (IndexError, ValueError) as exc:  # a malformed frame, e.g. a lone "{"
            self._rejected.setdefault(template, f"{type(exc).__name__}: {exc}")
            self._unresolved.setdefault(template, None)
            return template

    # -- what happened ---------------------------------------------------- #

    def frame_holes(self) -> set[str]:
        """The hole names every frame this render declared."""
        return set(self._holes)

    def report(self) -> dict:
        """Everything the diagnostic needs, and nothing derived from a guess.

        ``coverage`` deliberately counts only entries that DIFFER from English, so
        a catalog full of copied English cannot report itself complete. The
        identical ones are published beside it under their own name.
        """
        seen = list(self._seen)
        translated = [s for s in seen if s in self._hit]
        identical = [s for s in seen if s in self._same]
        rejected = {s: r for s, r in self._rejected.items()}
        missing = [
            s for s in seen if s not in self._hit and s not in self._same and s not in rejected
        ]
        n = len(seen)
        if self.is_english:
            # English is the SOURCE. Every sentence is already in the requested
            # language, so there is nothing missing and no ratio to report — and the
            # naive arithmetic below would say "0 of 166 translated, coverage 0%",
            # which reads as an unstarted locale rather than as the source language.
            # Not-applicable is the honest third state; the count of sentences seen is
            # still published, because that IS what the document asks for and it is the
            # denominator every other locale is measured against.
            return {
                "language": "en",
                "requested": self.requested,
                "catalog_path": None,
                "catalog_entries": 0,
                "catalog_present": True,
                "strings_seen": n,
                "translated": n,
                "identical_to_english": 0,
                "rejected": 0,
                "missing": 0,
                "coverage": None,
                "missing_strings": [],
                "identical_strings": [],
                "rejected_strings": [],
                "method": (
                    "English is the source language: the renderer's sentences are written "
                    "in it, so nothing is translated and nothing is missing. The count of "
                    "sentences is the denominator every other locale is measured against."
                ),
            }
        return {
            "language": self.lang,
            "requested": self.requested,
            "catalog_path": str(catalog_path(self.lang)) if not self.is_english else None,
            "catalog_entries": len(self.catalog),
            "catalog_present": bool(self.catalog) or self.is_english,
            "strings_seen": n,
            "translated": len(translated),
            "identical_to_english": len(identical),
            "rejected": len(rejected),
            "missing": len(missing),
            # A share, stated as a share: one number, its numerator and its
            # denominator all published so a reader never has to trust the ratio.
            "coverage": (len(translated) / n) if n else None,
            "missing_strings": missing,
            "identical_strings": identical,
            "rejected_strings": [{"text": s, "reason": r} for s, r in rejected.items()],
            "method": (
                "Every sentence this app composes is keyed on its own English text. "
                "Coverage counts entries that differ from the English; an entry copied "
                "from the English is counted separately, and one whose placeholders do "
                "not match its frame is refused and rendered in English."
            ),
        }

    def disclosure(self) -> str | None:
        """The line a mixed-language document owes its reader, or nothing.

        A French document whose caveats are in English is not broken — the caveats
        are simply untranslated — but a reader cannot tell that from a deliberate
        quotation unless the document says so. English documents get no line: there
        is nothing to disclose, and adding one would change every existing edition.
        """
        if self.is_english:
            return None
        # Read the report BEFORE composing the line, so the line's own frame is not
        # counted in the total it reports. Otherwise a fully-translated document would
        # announce a shortfall of exactly one — itself.
        r = self.report()
        n, done = r["strings_seen"], r["translated"]
        if not n:
            return None
        # Numbers are grouped in the English style everywhere, and in French "72,225"
        # reads as seventy-two point two two five — a MISREADING rather than a style
        # nit, so the convention is stated. Locale-aware grouping is a separate change:
        # it belongs to the app-wide shared formatter, and guessing per locale (a dot
        # for German, lakh grouping for Hindi) would trade one misreading for another.
        numbers = " " + self.t(
            "Numbers keep their English grouping: a comma separates thousands and a "
            "full stop marks the decimal."
        )
        if done >= n and not r["rejected"]:
            return self.f(
                "This edition was written in {language}. Words quoted from sources — "
                "titles, authors, keywords — stay in their own language.",
                language=self.language_name(),
            ) + numbers
        return self.f(
            "This edition was requested in {language}: {done} of {total} sentences this "
            "app writes have a {language} translation and the rest are printed in "
            "English. Words quoted from sources — titles, authors, keywords — stay in "
            "their own language, and translating an article itself is a separate, "
            "model-assisted step that is offered rather than assumed.",
            language=self.language_name(),
            done=f"{done:,}",
            total=f"{n:,}",
        ) + numbers

    def language_name(self) -> str:
        """The language's own name for itself, per the flags-are-not-languages rule."""
        return _AUTONYM.get(self.lang, self.lang)


#: The native name, which is the identifier (UI invariant #15 — a flag is a visual
#: convention, the autonym is what names a language).
_AUTONYM: dict[str, str] = {
    "en": "English",
    "fr": "Français",
    "de": "Deutsch",
    "es": "Español",
    "pt": "Português",
    "ru": "Русский",
    "ar": "العربية",
    "zh": "中文",
    "ja": "日本語",
    "hi": "हिन्दी",
    "bn": "বাংলা",
    "id": "Bahasa Indonesia",
}


def available_languages() -> list[str]:
    """Which locales have a catalog on disk, English always included."""
    out = ["en"]
    for code in UI_LANGS:
        if code != "en" and load_catalog(code):
            out.append(code)
    return out
