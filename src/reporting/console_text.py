"""Text from a bundle, made safe to print on a console beside a verdict (row 199).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The offline verifiers print fields a bundle supplies (a case name, an item id, a reason that quotes one) next to
their own ``VERIFIED`` line. Printed raw, a tampered bundle whose case name holds a newline and the text
``VERIFIED       : True`` draws a fake verdict above the real ``False`` one; a carriage return, an ANSI escape, a
Unicode line or paragraph separator or a bidi override can do the same by moving the cursor, erasing, or reordering
what is shown. So every character that is not plain printable text is written as its escape, and the backslash
itself is doubled, so an escape the bundle wrote as text cannot pass for one this function made. Standard library
only, because the verifiers are meant to run without the app.
"""

from __future__ import annotations

import unicodedata

# Cc: C0/C1 controls (newline, CR, ESC, DEL...); Cf: format characters (bidi overrides, zero-width joiners);
# Zl/Zp: U+2028/U+2029; Cs: lone surrogates; Co/Cn: private use and unassigned, which a console may draw as anything.
_UNSAFE_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp", "Cs", "Co", "Cn"})


def console_safe(value: object) -> str:
    """``str(value)`` with every non-printing character escaped and backslashes doubled; one line, always."""
    out = []
    for ch in str(value):
        if ch == "\\":
            out.append("\\\\")
        elif unicodedata.category(ch) in _UNSAFE_CATEGORIES:
            code = ord(ch)
            out.append(
                f"\\x{code:02x}"
                if code < 0x100
                else f"\\u{code:04x}"
                if code < 0x10000
                else f"\\U{code:08x}"
            )
        else:
            out.append(ch)
    return "".join(out)
