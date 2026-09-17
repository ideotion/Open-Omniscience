# `tests/fixtures/wiki/` — provenance

**Everything in this directory is wholly synthetic.** No byte of it is derived from
Wikipedia, Wikimedia, or any other external source, so **no attribution obligation
attaches to it** and nothing here touches the ODbL / CC BY-SA questions that govern
real lane data. That is a property of how it was made, not a claim about how it
looks: `oowiki.json` is written by `scripts/make_wiki_fixture.py`, which contains
every title, body, editor name and timestamp as a literal.

**The edition code is `oo`, which is not an ISO 639 language code**, so it can never
name a real Wikipedia edition. A defect that let a fixture address escape into a live
fetch would therefore ask for a host that does not exist, rather than for somebody
else's server.

**It is deterministic.** The generator reads no clock and uses no randomness; the
timestamps are offsets from a fixed epoch. Re-running it produces a byte-identical
file, which is what lets a test pin the fixture's own digest —

```
sha256  3e4750e6fb89fb9901d2f7289da23d6728728b03d650194a8b26b9c33545a11b
bytes   59721
```

Regenerate with `python scripts/make_wiki_fixture.py`; the script prints the digest
it wrote, and `tests/test_versioned_models.py` fails if the committed file and the
generator have drifted apart — and if THIS note's digest goes stale, which is the
way a provenance record stops being a record and becomes a claim.

## What each page is FOR

The fixture is shaped one property per page, so a failing test names the property
rather than "the fixture":

| page | exercises |
|---|---|
| `Fixture Alpha` | create → two edits: the ordinary baseline → change → revision → Article round trip, and a point-in-time read that must return the middle version |
| `Fixture Beta` | an edit that is reverted to a byte-identical body: a NEW revid with the SAME text, which must store as `unchanged` rather than as an empty diff |
| `Fixture Gamma` | a page deleted after two edits: the delete arrives as a log event, `fetch_version` answers "no such item", and the history stays |
| `Fixture Delta` | a deliberately large body, so a byte budget has something worth refusing and the deferral is a real measurement |
| `Fixture Epsilon` | edits far older than any retention window a client is asked to serve — which is what makes the `retention` gap happen instead of being faked |

## How it is served

`src/testing/wiki_fixture.py`'s `FixtureWikiClient` answers the same methods
`src.wiki.client.WikiClient` answers, from this file, and opens no socket. Its
`max_recentchanges` is the retention window: setting it small is how a test produces
a genuine gap. Its `as_of` lets one file serve several "days" without a second
fixture.
