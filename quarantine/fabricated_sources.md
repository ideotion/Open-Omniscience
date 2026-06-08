# Quarantined catalog entries — suspected fabricated sources

Per the project's honesty rule ("every entry is a real outlet … nothing is
fabricated"), entries that fail an objective fabrication signature are removed
from `configs/sources.yml` and recorded here (kept in git history) rather than
shipped as if they were real outlets.

## 2026-06 — six religion/history placeholder entries

**Signature (all six matched):** the `domain` is templated directly from the
source `name` (a generic descriptive concept, not a real publication), `rss_url`
is empty, and tags are generic (`history`/`ancient_history` + `en`).

**Reachability check (2026-06-08, `curl -L -m6`):**

| name | domain | result |
|---|---|---|
| African Traditional Religions | africantraditionalreligions.com | no server (000) |
| Islam in Africa | islaminafrica.com | no server (000) |
| Christianity in Africa | christianityinafrica.com | no server (000) |
| Ancient Egyptian Religion | ancientegyptianreligion.com | no server (000) |
| Roman Religion | romanreligion.com | 403 (parked-page signature) |
| Greek Religion | greekreligion.com | 403 (parked-page signature) |

The first four do not resolve at all; the two `403`s carry the same templated /
empty-RSS / generic-concept signature and would never yield a real article.
None is a genuine news or research outlet.

**Kept (real, do not confuse with the above):** `muslimheritage.org` (a real
organisation — flagged by the same name→domain heuristic but verified real),
and all religion-topic entries backed by a real publisher / working feed
(Brill's *Journal of Religion in Africa*, *Journal of Islamic Studies*,
*Hinduism Today*, *Tricycle*, *The Hindu*, etc.).

**To restore any entry:** confirm it is a real outlet with a reachable site (and
ideally a feed), then re-add it to `configs/sources.yml` with honest metadata.
