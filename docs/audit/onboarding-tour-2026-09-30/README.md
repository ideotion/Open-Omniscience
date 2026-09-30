# The onboarding tour and the signed-evidence review, click-through — 2026-09-30 (S05-11 S5, gate 0.5 row K)

Chromium (Playwright, `/opt/pw-browsers/chromium-1194`) against a real server started with
`OO_DB_PLAINTEXT=1 OO_AUTOSEED=0 OO_NO_SCHEDULER=1` on a data folder `seed.py` prepared: six invented
articles from three invented sources (every host is `.invalid`), **no evidence key**, so the review starts in
the "no key yet" state. Stamped **Chromium-verified (remote sandbox) · awaiting human UX pass**.

**The walk goes offline on purpose and checks it.** It engages airplane mode through
`POST /api/system/network` and reads it back before the first page, and the browser aborts every request that
is not to the loopback server.

| Check | Result |
|---|---|
| Never starts by itself | `#tour` is closed after boot |
| Entry points | Settings → General «Take the tour», Help & docs «Take the tour» and the command palette's «Take the tour» each open step 1; Skip and Esc close it |
| Full depth | 14 steps: the top bar, the twelve tabs in the sidebar's order, the depth; each tab step carries «Open <tab>», which opens the tab and closes the tour |
| Essentials | 5 steps: the top bar, Home, Feed, «10 more tabs» (all ten named in the sidebar's order) and the depth; «Show them in the sidebar» opens the sidebar's «Show more» row; the last step's button lands on the depth setting |
| It changes nothing | Walked end to end with no button pressed, the depth, the whole of `localStorage` and the sidebar read the same before and after; pressing «Open Explore» only navigates (the network coachmark key `oo_net_coach_v1` is the one key that appears, the tab's own) |
| Arabic and 375 px | `dir=rtl`; every step and button in Arabic, no `undefined`/`NaN`/`{placeholder}`, no Latin left; the dialog inside the viewport (18 px to spare at 375 px), no horizontal page scroll, no overlapping text |
| Evidence review | Empty Search box: the same refusal toast as before, no dialog. With a query: «Articles: 6 · Sources: 3», what the file holds (with the item fields taken from the server's own list), the plaintext line and the signing-key line, both visible on the page, not in a hover; «Save the signed bundle» |
| Looking creates nothing | The evidence key file does not exist after the review opened, and exists only after Save |
| Save | The download `evidence-bundle-2026-09-30.json` holds the 6 articles; the message names the file and its size, lists the three members, prints the signing key (equal to the bundle's `public_key`) and says how to check the file offline |
| Second open | With a key on disk the review says the file «is signed with this install's evidence key», that the same key links every bundle, and shows the key that will sign |
| Arabic, 375 px, language change while open | Right-to-left; the field names isolated as a left-to-right run; a language change while the dialog is open redraws it; no overlap, no page scroll |
| Whole walk | **0 page errors, 0 responses ≥ 400, 0 non-loopback requests**; airplane mode still on at the end |

`report.json` holds every value read; `seed.py` and `walk.py` reproduce it (`OO_WALK_BASE`, `OO_WALK_OUT`,
`OO_WALK_KEY`). The one Latin word left in the Arabic review, `title`, is an item field name, shown as code.

**Found and fixed by this walk, before it was recorded:** the list of item fields inside an Arabic sentence was
reordered around its commas; it is an isolated left-to-right run now.

**Found by the Opus review of the diff, fixed before the PR:** a save still in flight when the dialog was
closed or reopened on another selection would still download and mark the new selection saved (now dropped);
the review did not say that the file carries the reader's query as the case name (now in the list and the
caveat); it did not show the key that will sign (now shown); `existing_public_key_hex` could regenerate a key
if the file vanished between two calls (now reads and parses only); the tour listed the OPEN tab as waiting
behind «Show more» at Essentials (the sidebar keeps it listed); the plan loaded every matching article's text
just to count (now a COUNT); a stale plan's failure toasted over the newer review.
