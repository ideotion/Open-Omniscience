"""
Structured price extraction from a market page, by explicit rule.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The single honesty rule of this module: produce a number ONLY when the operator's
explicit locator (CSS selector, optionally narrowed by an attribute and/or a
capture-group regex) lands on a real, parseable figure. Every other case -- no
such element, missing attribute, regex miss, unparseable text -- returns a
``PriceExtraction`` whose ``value`` is ``None`` and whose ``reason`` says exactly
what happened. Nothing is guessed, inferred, or defaulted into existence
(PRODUCT_SYNTHESIS §3.5 "No fabricated numbers").

Number parsing handles the common money formats (thousands separators, US/EU
decimal marks, currency symbols, trailing units/percent). Where a string is
genuinely ambiguous (a lone ``1.234`` / ``1,234``) it follows one documented
convention rather than silently maybe-wrong magic; operators disambiguate with
``value_regex`` and can preview the result with the rule "run now" action.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

# Matches a numeric token possibly containing grouping/decimal separators or
# (non-breaking) spaces used as thousands separators.
_NUM_RE = re.compile(r"[-+]?\d[\d\s .,]*\d|[-+]?\d")


@dataclass
class PriceExtraction:
    """Outcome of applying a rule to a page. ``value`` is None on any failure."""

    value: float | None
    matched_text: str | None
    reason: str  # "ok" or a human-readable explanation of the failure

    @property
    def ok(self) -> bool:
        return self.value is not None


def parse_number(text: str | None) -> float | None:
    """Parse the first numeric figure out of ``text``, or return None.

    Conventions (documented, deterministic):
      * spaces / non-breaking spaces inside a number are grouping separators;
      * if both ``.`` and ``,`` appear, the *last* one is the decimal mark;
      * a lone ``,`` with exactly three trailing digits is a thousands separator
        (``1,234`` -> 1234); otherwise it is a decimal mark (``12,5`` -> 12.5);
      * repeated ``.`` are grouping (``1.234.567`` -> 1234567); a lone ``.`` is a
        decimal mark (``1.234`` -> 1.234).
    """
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    m = _NUM_RE.search(s)
    if not m:
        return None
    token = m.group(0).replace(" ", "").replace(" ", "")

    sign = ""
    if token[:1] in "+-":
        sign = "-" if token[0] == "-" else ""
        token = token[1:]
    if not token:
        return None

    has_dot, has_comma = "." in token, "," in token
    if has_dot and has_comma:
        if token.rfind(".") > token.rfind(","):
            token = token.replace(",", "")  # 1,234.56 -> 1234.56
        else:
            token = token.replace(".", "").replace(",", ".")  # 1.234,56 -> 1234.56
    elif has_comma:
        parts = token.split(",")
        if len(parts) == 2 and len(parts[1]) != 3:
            token = parts[0] + "." + parts[1]  # 12,5 -> 12.5
        else:
            token = token.replace(",", "")  # 1,234 / 1,234,567 -> grouping
    elif has_dot and token.count(".") > 1:
        token = token.replace(".", "")  # 1.234.567 -> grouping; a lone dot is decimal

    try:
        return float(sign + token)
    except ValueError:
        return None


def extract_price(
    html: str,
    *,
    selector: str,
    attribute: str | None = None,
    value_regex: str | None = None,
) -> PriceExtraction:
    """Locate and parse a price in ``html`` using an explicit rule.

    Returns a :class:`PriceExtraction`; ``value`` is None (with a ``reason``) for
    every miss, so callers can record an honest failure instead of a fake price.
    """
    if not html or not html.strip():
        return PriceExtraction(None, None, "empty page")
    soup = BeautifulSoup(html, "html.parser")
    try:
        el = soup.select_one(selector)
    except Exception as exc:  # noqa: BLE001 - bad CSS selector from operator input
        return PriceExtraction(None, None, f"invalid CSS selector: {exc}")
    if el is None:
        return PriceExtraction(None, None, "selector matched no element on the page")

    if attribute:
        raw = el.get(attribute)
        if raw is None:
            return PriceExtraction(None, None, f"element has no attribute {attribute!r}")
        raw = " ".join(raw) if isinstance(raw, list) else str(raw)
    else:
        raw = el.get_text(" ", strip=True)

    text = raw
    if value_regex:
        try:
            m = re.search(value_regex, raw)
        except re.error as exc:
            return PriceExtraction(None, raw, f"invalid value_regex: {exc}")
        if not m:
            return PriceExtraction(None, raw, "value_regex did not match the element text")
        text = m.group(m.lastindex) if m.lastindex else m.group(0)

    value = parse_number(text)
    if value is None:
        return PriceExtraction(None, raw, f"no parseable number in {text!r}")
    return PriceExtraction(value, raw, "ok")
