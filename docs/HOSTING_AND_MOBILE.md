# Hosting & mobile — options, costs, and the ethics tension

> **Status:** a decision memo, not a committed direction. It exists to let a clear-eyed
> choice be made. Read the tension in §1 *first* — it is the whole point.

This memo answers a real question: **how do we put Open Omniscience on a phone?** The
obvious path — rent a server (e.g. OVH), run the app in the cloud, hand each user a remote
GUI — is technically easy and ethically expensive. This document lays out the full
spectrum honestly, with rough costs, concrete steps, and a recommendation that keeps the
project's promises.

---

## 1. The tension (say it plainly)

The app's entire safety model is **local-first, single-user, no-server, no-telemetry**.
[`GOVERNANCE.md`](GOVERNANCE.md) makes that a **red line**:

> *No central server, accounts, or telemetry — absent by construction, not configurable.*

A centralized, hosted, multi-user service does not bend that line; it **deletes** it. The
consequences are not abstract:

- **You become the custodian of other people's corpora.** A journalist's source list,
  search history, and saved evidence now live on *your* rented box. That is exactly the
  thing the app was built so that *no one* could hold.
- **You become a single point of coercion.** A subpoena, a hosting-provider takedown, a
  state letter, or a server seizure now compromises *every* user at once. Today, seizing
  one laptop compromises one user. That asymmetry is the product.
- **You inherit legal and moral liability** for what others collect and do with the tool —
  jurisdiction, data-protection law, content liability, lawful-intercept demands.
- **Telemetry becomes possible** (server logs are telemetry by default), so the "nothing
  leaves the machine" guarantee can no longer be *proven by architecture*, only promised.

None of this means "never put it on a phone." It means: **the phone should run the user's
own instance, not borrow yours.** Everything below is organised around that principle.

---

## 2. The spectrum of options

Five architectures, from most-aligned to least. "Aligned" = how well it preserves the
red lines.

| # | Option | Where data lives | Who pays / hosts | Ethics | Effort |
|---|--------|------------------|------------------|--------|--------|
| A | **Mobile-local** (app runs *on* the phone) | the phone | the user (device) | ✅ fully aligned | high |
| B | **Self-host one-click** (user rents their own VPS) | user's VPS | the user | ✅ aligned | medium |
| C | **Bring-your-own-home** (phone → user's own always-on machine over a private tunnel) | user's home PC | the user (already owns) | ✅ aligned | low–medium |
| D | **Per-user isolated instances you host** | your server, siloed per user | **you** | ⚠️ partial | high |
| E | **Centralized multi-user SaaS** | your server, shared DB | **you** | ❌ breaks red lines | medium |

The path you described — rent OVH, run in the cloud, delegate the GUI — is **D or E**.
Those are the two that cost *you* money that scales with users, and the two that erode the
ethics. A, B and C cost you ~nothing per user and keep the promises. That is the crux of
the funding worry: **the expensive options are the unethical ones.**

---

## 3. Recommended path

**Primary: B (self-host one-click) + C (bring-your-own-home), with A (mobile-local) as the
long-term north star.**

This keeps the project **fully FOSS and free to give away** without exposing you to
unbounded hosting cost or to becoming a custodian/target. You ship *software and recipes*;
each user supplies the *hardware and the trust boundary*. A phone is then just a **thin
client to an instance the user controls** — which is exactly the local-first model,
stretched over a private network the user owns.

Concretely, the phone experience is delivered by making the existing GUI a good
**installable PWA** (it is already a dependency-free static front-end talking to a local
API — most of the work is done), reachable over a **private tunnel** (Tailscale/WireGuard)
or a **per-user deploy** the user rents in two clicks.

If you later want a true "download from the app store and it just works" experience with
**no** server at all, that is **Option A**, and §6 sketches how.

---

## 4. Costs (rough, 2026 — verify before committing)

Prices are approximate and region/promo-dependent; treat them as orders of magnitude.

### What drives cost
The app's spine (FastAPI + SQLite + ethical fetch) is **light** — it runs comfortably in
~1 GB RAM. Two things make it heavy:
1. **Ingestion bursts** (network + CPU during a scrape) — spiky, not sustained.
2. **The optional local LLM (Ollama).** A 7–8B model wants ~6–8 GB RAM and is slow on CPU;
   usable speed wants a GPU. **This is the cost driver if hosted.** Most of the app works
   fine without it — keep the LLM optional and *off* on shared hosting.

### Option B/D — a VPS (e.g. OVH), per instance
| Tier | Spec (≈) | Good for | ≈ Monthly |
|------|----------|----------|-----------|
| Starter VPS | 1 vCPU, 2 GB, 40 GB SSD | spine only, light ingest, no LLM | **€4–7** |
| Standard VPS | 2 vCPU, 4 GB, 80 GB SSD | comfortable single user, Wikipedia baselines | **€10–15** |
| Memory VPS | 4 vCPU, 8–16 GB | small CPU-only LLM, heavier corpora | **€20–35** |
| + GPU (if you insist on hosted LLM) | entry GPU instance | usable LLM | **€120–400+** |

- **Object storage** (optional, for Wikipedia dumps / backups): OVH/S3-style ~**€5/TB/mo**.
- **Bandwidth:** OVH VPS bandwidth is typically generous/unmetered at these tiers; verify.

### What Option D actually costs *you* (the part to fear)
Per-user isolated instances mean cost ≈ **(number of active users) × (a VPS tier)**.
- 10 users on starter VPSes ≈ **€40–70/mo**.
- 100 users on standard VPSes ≈ **€1,000–1,500/mo**.
- Add anyone wanting the LLM and it balloons.
This is **unbounded, recurring, and grows with success** — the worst shape of cost for a
solo maintainer already spending heavily elsewhere. *Success becomes a bill.*

### Option C — bring-your-own-home
- **Your cost: ~€0.** The user runs the app on a machine they already own (an old laptop, a
  Raspberry Pi ~€60 one-off, a home server) and reaches it from the phone over a free
  private tunnel (Tailscale free tier; or self-hosted WireGuard).

### Option A — mobile-local
- **Your cost: ~€0 ongoing** (just a one-time app-store developer fee if you publish:
  Google ~$25 once, Apple ~$99/yr). The user's phone is the server.

**Bottom line on affordability:** the only paths that cost you money are D and E. If the
worry is "I can't afford it," the answer is happy: **don't host. Ship software.** A, B and
C let you go full FOSS for free.

---

## 5. Steps for the recommended path (B + C), phased

### Phase 0 — make the front-end a first-class phone client (small, do regardless)
The GUI is already static, dependency-free, and bound to a local API — ideal for this.
1. Add a **web app manifest** (`manifest.webmanifest`: name, icons, `display: standalone`,
   theme color) and link it from `index.html`.
2. Add a minimal **service worker** that caches the static shell for offline launch (the
   *shell* only — never user data; data stays in the API/DB it talks to).
3. Verify the existing **responsive** layout (the sidebar already collapses < 860 px) and
   the new **a11y** affordances on a real phone; fix tap targets if needed.
4. Result: "Add to Home Screen" gives an app-like icon and full-screen launch — no store
   needed.

### Phase 1 — bring-your-own-home (Option C), lowest friction
1. Document a **Tailscale/WireGuard quick-start**: install the tunnel on the home machine
   and the phone, both join the user's private net.
2. Bind the app to the tunnel interface (it currently binds `127.0.0.1`; add an opt-in
   `OO_BIND` for the tailnet IP **only**, never `0.0.0.0` without a warning).
3. Add a clear **security note**: enabling a non-loopback bind widens the trust boundary;
   require the tunnel, document the risk honestly (consistent with how Safety mode is
   documented).
4. The phone opens `http://<home-host>:<port>` (the PWA from Phase 0) — done.

### Phase 2 — self-host one-click (Option B)
1. Ship a hardened **`Dockerfile` + `docker-compose.yml`** (the repo already targets a
   clean single-process app; containerize the spine, make the LLM an opt-in profile).
2. Provide **one-click deploy templates** for providers that support them (a `deploy`
   button / cloud-init script for OVH, Hetzner, a Render/Fly blueprint). The user clicks,
   *their* account is billed, *they* hold the data and the keys.
3. Add **first-boot guidance** in the deploy: set a passphrase, enable HTTPS (Caddy/Traefik
   auto-TLS), turn on the Safety features (encrypted backup, Protected fetch).
4. **You host nothing.** You maintain the image and the templates.

### Phase 3 (optional, long horizon) — mobile-local (Option A)
See §6. Only worth it if "store install, zero setup, no other machine" becomes a hard
requirement.

---

## 6. The genuinely-hard option (A): running on the phone itself

Three realistic routes, hardest tradeoffs noted:
- **Termux (Android):** Python + the app run in a Linux userland on the phone; the PWA
  points at `127.0.0.1`. Works today with packaging effort; rough UX; Android may sleep the
  process. Good for power users now, not for the app store.
- **Capacitor/Tauri wrapper:** wrap the existing static GUI as a native shell. Easy for the
  *UI*; the hard part is the **Python backend** — either bundle a Python runtime (heavy,
  fragile on iOS especially) or **port the spine** to something embeddable.
- **Port the spine to a mobile-native runtime** (the honest long game): the core is small
  (SQLite + HTTP fetch + a few pure-Python signal primitives). A clean reimplementation of
  just the spine in a mobile-friendly stack, reusing the *static* GUI verbatim, is the only
  route to a true store app with no server and no Linux userland. Biggest effort; best
  alignment. Keep `src/signals/` pure precisely so this stays possible.

iOS is the real wall (no general background daemons, no easy embedded Python). Android via
Termux/Capacitor is reachable sooner.

---

## 7. FOSS funding without going broke

Going **full FOSS is the right call** and it is *cheap* — if you give away **software**,
not **hosting**. Models that fund the work without per-user liability:

- **Donations / sponsorship:** GitHub Sponsors, Open Collective, Liberapay. Fund *your
  time*, not a server fleet.
- **Grants:** digital-rights and press-freedom funders are a natural fit (e.g. NLnet/NGI,
  OTF-style funds, press-freedom foundations). A local-first tool for at-risk journalists
  is squarely in scope; the no-server posture is a *selling point* to them.
- **Optional paid convenience that doesn't compromise ethics:** a *managed deploy helper*
  (you sell setup/support, the user still owns the box and data), or signed mobile builds.
  Never sell hosting of their corpora.
- **What to avoid:** a free hosted service. It is an unbounded, growing cost, a liability
  magnet, and a betrayal of the architecture. "Free hosting for everyone" is the one
  generous-sounding choice that can sink both the budget and the mission.

**The one-line decision:** *Give away the software for free; never host the users' data.*
That is both the affordable path and the ethical one — they are, happily, the same path.

---

## 8. Recommendation summary

1. **Do now (cheap, aligned):** make the GUI a PWA (manifest + offline shell) — §5 Phase 0.
2. **Ship next (≈€0 to you):** bring-your-own-home over a private tunnel — §5 Phase 1.
3. **Then (≈€0 to you):** one-click self-host templates; users rent their *own* box — §5
   Phase 2.
4. **Resist:** hosting users' corpora yourself (Options D/E). It is the expensive *and*
   unethical quadrant.
5. **Long game (if needed):** a true on-device build (Option A), kept feasible by keeping
   the spine small and pure.

Fund the *work* (sponsors/grants), not a server. Then "on a phone, for free, full FOSS"
is achievable without breaking the promise that made the app worth building.
