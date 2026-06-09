"""
ISO 3166-1 alpha-2 country codes — the neutral denominator for coverage.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Plain two-letter codes only (no names, no classification) used purely to measure
how many distinct countries/territories the source catalog covers and which are
still missing. The generator also iterates these codes to query Wikidata per
country. This is reference data, not an editorial statement about any place.
"""

from __future__ import annotations

# ISO 3166-1 alpha-2 (officially assigned codes), lowercased. Kept as a
# whitespace-separated string (split at import) so it stays compact and neutral.
_CODES = """
    ad ae af ag ai al am ao aq ar as at au aw ax az
    ba bb bd be bf bg bh bi bj bl bm bn bo bq br bs bt bv bw by bz
    ca cc cd cf cg ch ci ck cl cm cn co cr cu cv cw cx cy cz
    de dj dk dm do dz
    ec ee eg eh er es et
    fi fj fk fm fo fr
    ga gb gd ge gf gg gh gi gl gm gn gp gq gr gs gt gu gw gy
    hk hm hn hr ht hu
    id ie il im in io iq ir is it
    je jm jo jp
    ke kg kh ki km kn kp kr kw ky kz
    la lb lc li lk lr ls lt lu lv ly
    ma mc md me mf mg mh mk ml mm mn mo mp mq mr ms mt mu mv mw mx my mz
    na nc ne nf ng ni nl no np nr nu nz
    om
    pa pe pf pg ph pk pl pm pn pr ps pt pw py
    qa
    re ro rs ru rw
    sa sb sc sd se sg sh si sj sk sl sm sn so sr ss st sv sx sy sz
    tc td tf tg th tj tk tl tm tn to tr tt tv tw tz
    ua ug um us uy uz
    va vc ve vg vi vn vu
    wf ws
    ye yt
    za zm zw
    """

ISO_3166_1_ALPHA2: frozenset[str] = frozenset(_CODES.split())
