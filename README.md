# Open Omniscience

**An Open-Source, Ethical, Global Intelligence Platform for Investigative Journalism**

---

**Author:** [Ideotion](https://github.com/ideotion)
**Version:** 0.4 (working core — alpha)
**License:** [GNU GPLv3](LICENSE)

---

## Status — v0.4: the trustworthy core works

This release rebuilds the project around a small, **genuinely working and tested**
spine. See **[docs/QUICKSTART.md](docs/QUICKSTART.md)** to run it.

**What works now (tested end-to-end):**
- ✅ Add sources; **ethically ingest** an RSS feed or a single URL — robots.txt
  respected **fail-closed**, per-host rate limiting, one fetch path, no raw bypass.
- ✅ Robust article extraction (trafilatura); nothing stored if there's no real body.
- ✅ Unified SQLite store with **provenance** (source, URL, canonical, content hash,
  fetch time) and content-hash / canonical-URL **deduplication**.
- ✅ **Boolean full-text search** (SQLite FTS5): real `AND`/`OR`/`NOT`, `"phrases"`,
  parentheses with correct precedence — fully parameterized.
- ✅ CSV/JSON export; a dependency-free, offline web UI at `127.0.0.1:8000`.
- ✅ Single `pyproject.toml`, Python 3.13, clean install, full test suite green.

**Deferred to later phases (see [docs/ACTION_PLAN.md](docs/ACTION_PLAN.md)):**
local LLM analysis via Ollama (Phase 2); one financial/commodity vertical with
correlation (Phase 3); email + monitoring (Phase 4); signed chain-of-custody
reporting (Phase 5).

**Honesty note:** several previously-advertised "analysis" components (deepfake,
propaganda, cognitive-bias, bot detection) were **fabricated** — returning
hardcoded or heuristic scores while claiming real detection — and have been
**quarantined** (`quarantine/`, see [docs/SALVAGE_MAP.md](docs/SALVAGE_MAP.md))
rather than shipped as if they worked.

---

## 🌟 Mission

Open Omniscience is an **ethically oriented**, **open-source**, and **portable** global intelligence platform designed to aggregate raw news information from diverse worldwide sources into a **unified, highly searchable, and auditable database**. Its primary function is to **empower investigative journalism** by enabling users to:

- Cross-reference disparate pieces of information.
- Identify **complex patterns, disinformation schemes, or emerging trends** across geopolitical boundaries.
- Preserve **data integrity and provenance** for accountability.
- **NEW:** Analyze, translate, and synthesize content using **local LLM capabilities**

This project is a **Debian-based Linux application** built on Python, leveraging robust crawling capabilities for **ethical scraping**, **duplicate detection**, **data management**, and now **AI-powered analysis**.

---

## 🚀 Getting Started

This is a **local-first, single-user** app for a **Qubes OS Debian AppVM** on
**Python 3.13**, bound to loopback only. Full instructions: **[docs/QUICKSTART.md](docs/QUICKSTART.md)**.

**One command (then double-click to run):**
```bash
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/main/scripts/bootstrap.sh | bash
```
It clones the repo and runs `./install.sh`, a small menu where you pick **Core**
(scrape/store/search/export), optional **Analysis tools**, and optional **Local LLM
tools** (Ollama + a model) — re-run it any time to add more. It then creates an
**Open Omniscience** launcher in your apps menu and on the Desktop; double-click it
to start the app and open the browser. *(Inspect the tiny
[bootstrap](scripts/bootstrap.sh) before piping any script to a shell, or clone and
run `./install.sh` yourself.)*

```bash
# Local dev (any Linux with Python 3.13):
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e ".[analysis,dev]"
pytest -q
open-omniscience          # serves http://127.0.0.1:8000 (auto-seeds ~1,780 sources)
```

On Qubes: `sudo ./install.sh --template` (in the TemplateVM, then reboot the AppVM)
→ `./install.sh`.

The loop: pick/add a source → **ingest** an RSS feed or URL (ethical: robots.txt
fail-closed, rate-limited) → **search** with Boolean operators (`AND`/`OR`/`NOT`,
phrases, parentheses) → **export** CSV/JSON → optionally **summarize** locally via
Ollama and export a **signed, verifiable evidence bundle**.

## 📚 Documentation

- [QUICKSTART](docs/QUICKSTART.md) — install + the end-to-end loop
- [PRODUCT_SYNTHESIS](docs/PRODUCT_SYNTHESIS.md) — what the app is and isn't
- [ACTION_PLAN](docs/ACTION_PLAN.md) — phased build plan + status
- [PILLAR_INTENT_MAP](docs/PILLAR_INTENT_MAP.md) — where each original "pillar" lives now
- [AUDIT_2026-06](docs/AUDIT_2026-06.md) / [QUALITY_CHECKUP](docs/QUALITY_CHECKUP.md) — honest state
- [SALVAGE_MAP](docs/SALVAGE_MAP.md) — keep/fix/quarantine record

## 🔒 Security model

Single local user, loopback-only (`127.0.0.1`), no accounts/RBAC. No telemetry; no
data leaves the machine (LLM is local via Ollama). Outbound only during scraping,
and only through the ethical, robots-respecting fetcher.

## 📜 License

[GNU GPLv3](LICENSE).

---

*© 2026 Ideotion — built for investigative journalism, honestly.*
