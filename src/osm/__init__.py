"""The OpenStreetMap lane: one country's places, roads and buildings in ``osm.db`` (S05-04).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

0.5 row D seeds the lane (Q106 = a): the extract pass over a continent extract (Q806 = b),
the curated columns plus one JSON blob (Q810), SQLite for everything (Q811 = b), the
tag-level change MODEL (Q813; the daily apply is 0.6), and analytic 1, tag completeness
(Q815). The pieces, in the order an extract travels through them:

* ``pbf``          -- a pure-Python ``.osm.pbf`` decoder, the small-country path (Q808).
* ``reader``       -- the seam: ``pyosmium`` when the ``[geo]`` extra is installed, the
                      pure-Python decoder under its size cap otherwise, a named refusal
                      beyond it.
* ``geometry``     -- the country's border from its ``admin_level=2`` relation, a
                      point-in-polygon test that stays fast over millions of points, and
                      the compact coordinate encoding a way's geometry is stored in.
* ``tags``         -- which objects the lane keeps, the curated columns, the blob.
* ``lane_models``  -- the ``osm.db`` tables.
* ``ingest``       -- the passes that cut one country out of an extract into ``osm.db``.
* ``changes``      -- ``.osc`` parsed in pure Python and the tag-level change rows.
* ``completeness`` -- analytic 1: counts, n, method, caveat. Never a score.

NOTHING HERE TOUCHES THE NETWORK. The download is ``src/geo/osm_downloads.py``'s, under the
one online consent; the lane reads a file already on disk.

**Q823 (ODbL) IS UNANSWERED, AND THIS PACKAGE STOPS AT ITS SEAM.** Every row here is
OSM-derived. ``osm.db`` is a lane file, which the backup inventory marks not exportable, and
nothing in this package writes into an export, a bulletin or an evidence ZIP.
``tests/test_osm_lane_seam.py`` pins that from the outside.
"""
