## 2026-10-13 — a threshold derived from a cadence is wrong wherever the cadence is a phase: decide per event, with the consumer's own rule (PR #1379)

The forward clock step was first recorded from 600 s, with a derivation written beside the constant: "a gap needs 605 s of wall advance between two ticks on the worst alignment, the tick takes 5 s of it, so 600 s of step is the
smallest that can turn up as a gap". It read as proof and a test swept "every alignment" against the gap rule. The independent read found it false in one probe: ticks do not sit on a 5 s grid that lines up with the
five-minute buckets. The last tick of a bucket can be at any phase in it and a tick can come late (the loop does other work in the same iteration), so a step of 595.5 s at offset 299.9, 596 s at 299.5, 599 s at 297, and 585 s
on a tick 20 s late each opened a listed 600 s gap with nothing recorded, the exact symptom the change exists to remove. The sweep missed it because its offsets and its tick interval were multiples of the thing it
assumed (`range(0, 300, 5)`), so the test could only confirm the grid it was written on.

A second near-miss had the same cause. The first fold of the read made the sweep's expected value read the module's own floor constant, so a floor changed from 1 s to 2 s would have moved the expectation with it: the mutant survived
until a test used the literals 0.9 and 1.1. A third: the mutant "the method drops the list-eviction clause" reported survived, because the runner's `-k` filter did not select the one test that guards the clause; a survivor is
first a question about the filter.

The rules:
1. **A constant derived from a cadence is a claim about the cadence's phase, jitter and lateness, not only its period.** If the smallest triggering value depends on where in its window an event falls, no constant says it. Decide
   per event, with the SAME function the consumer uses (here `_opens_gap`, shared by the gap list and the tick, so the two cannot disagree), and write in the constant's comment why no constant can say it, naming the aligned
   case the old derivation was true for.
2. **Sweep off the grid.** Offsets in sub-second steps, intervals that are not the nominal period (late ticks, stalls), and sizes either side of every boundary but never exactly on one (a float sum lands either side); compute the
   expected value from the arithmetic written out in the test, not from the module's helper or constant, and pin each constant once by a literal.
3. **Not measured is not zero.** A counter that cannot be taken (no boot-time clock on the platform, a file of a build that did not count) is `null` until a tick has had the means to compare, then 0; the method says so.
4. **Never mix an injected clock with a real reading.** A real clock beside an injected wall clock invents a step the size of their difference, so an injected `now`/`mono` without the third clock means "no reading"; and read a second
   clock on BOTH sides of the first, using the pair only when the two readings are close, or a pause between the reads is a step of its own length.
5. **Say what a mark does not claim.** A step under the minimum inside a gap the process's absence opened anyway is left unrecorded on purpose (the gap is down time first); the member's method lists that case beside the others so a
   reader of an unmarked gap knows what it can still be.
