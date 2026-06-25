# Honest, Accessible Chart-Type Decision Framework
# For a local-first, no-library (vanilla SVG/Canvas) app

Status: decision framework, not a chart gallery.
A technique rejected for dishonesty is recorded as a FINDING, not a gap.
Every recommendation below is filtered through the target app's hard constraints
(no libraries, honesty rules, accessibility, 17 themes + dark/light + RTL).

How to read this document:
- Part 1 is the perceptual ranking that drives every default. Read it first.
- Part 2 is the universal gate (honesty + a11y + no-library) every chart must pass.
- Part 3 is the intent -> technique matrix (deliverable 1).
- Part 4 is the per-technique catalogue: honesty checklist, a11y pattern, no-library note (deliverable 2).
- Part 5 is the REJECT / CONSTRAIN list (deliverable 3).
- Part 6 is uncertainty-honest technique, including the fan-chart test (deliverable 4).
- Part 1 also serves as deliverable 5 (perceptual primer).
- Appendix holds shared vanilla-JS patterns referenced throughout.


===============================================================================
PART 0 - SOURCE BASIS AND VERIFICATION
===============================================================================

Primary authorities (DOIs/dates confirmed against publisher records 2026-06-25):

- Cleveland, W. S., and McGill, R. (1984). "Graphical Perception: Theory,
  Experimentation, and Application to the Development of Graphical Methods."
  Journal of the American Statistical Association, 79(387), 531-554.
  DOI 10.1080/01621459.1984.10478080. [verified]
  The empirical ranking of elementary perceptual tasks. Foundation of every
  "position beats length beats angle beats area beats colour" claim here.

- Munzner, T. (2014). "Visualization Analysis and Design." A K Peters
  Visualization Series, CRC Press. ISBN 9781466508910. DOI 10.1201/b17511. [verified]
  The what/why/how framework; marks-and-channels taxonomy (Ch. 5); magnitude
  vs identity channels; expressiveness and effectiveness principles.

- Financial Times Visual Vocabulary (2016). FT graphics team (Alan Smith and
  colleagues), accompanying the Chart Doctor column "Simple techniques for
  bridging the graphics language gap," 17 August 2016. Repository:
  github.com/Financial-Times/chart-doctor/tree/main/visual-vocabulary. [verified]
  Inspired by the Graphic Continuum (Schwabish and Ribecca). Organises charts by
  nine analytical intents: deviation, correlation, ranking, distribution,
  change-over-time, magnitude, part-to-whole, spatial, flow.

- Elavsky, F., Bennett, C., and Moritz, D. (2022). "How accessible is my
  visualization? Evaluating visualization accessibility with Chartability."
  Computer Graphics Forum, 41(3), 57-70 (EuroVis 2022). DOI 10.1111/cgf.14522.
  Workbook: chartability.fizz.studio. [verified]
  50 testable heuristics under WCAG's POUR (Perceivable, Operable,
  Understandable, Robust) plus three extensions of Robust: Compromising,
  Assistive, Flexible (CAF). Source of the a11y test language used here.

- The Data Visualisation Catalogue. Severino Ribecca. datavizcatalogue.com.
  Continuously maintained web resource (no DOI). [cited by record]
  Used as a cross-check on which techniques fit which data shape and on the
  documented failure modes of each chart type.

Supplementary references (cited by bibliographic record, not re-verified here):
- Mackinlay, J. (1986). "Automating the design of graphical presentations of
  relational information." ACM Transactions on Graphics, 5(2), 110-141.
  Extended Cleveland-McGill's quantitative ranking to ordinal and nominal data;
  origin of the expressiveness/effectiveness criteria Munzner formalises.
- Bertin, J. (1967/1983). "Semiology of Graphics." The visual variables.
- Tufte, E. (1983/2001). "The Visual Display of Quantitative Information."
  Source of the "lie factor" idea and data-ink reasoning.
- Wilkinson, L. (2005). "The Grammar of Graphics." Springer.

Where this document and the FT vocabulary disagree, the disagreement is noted:
the FT vocabulary is a newsroom thought-starter and explicitly "not a wizard."
This framework is stricter because the app's honesty rules are hard rejections.


===============================================================================
PART 1 - PERCEPTUAL-RANKING PRIMER (deliverable 5)
===============================================================================

1.1 The ranking, two ways

Cleveland and McGill (1984) ordered elementary perceptual tasks by how
accurately people decode a quantity through them. From most to least accurate:

  1. Position along a common scale
  2. Position along identical but non-aligned scales
  3. Length, direction, angle        (grouped together at rank 3)
  4. Area
  5. Volume, curvature
  6. Shading, colour saturation

Munzner (2014, Ch. 5) splits channels into MAGNITUDE channels (for ordered data)
and IDENTITY channels (for categorical data), and ranks the magnitude channels
best-to-worst as:

  position on common scale > position on unaligned scale > length (1D size)
  > tilt/angle > area (2D size) > depth (3D position) > colour luminance
  > colour saturation > curvature > volume (3D size)

Identity channels, best-to-worst: spatial region > colour hue > motion > shape.

The popular shorthand "position > length > angle > area > colour" is the same
ordering, compressed. Use the full ordering when deciding; use the shorthand
only as a reminder.

1.2 Two principles from Munzner that gate channel choice

- Expressiveness: encode all of the data's attributes and only those. Do not
  imply order where there is none (e.g. a sequential colour ramp on unordered
  categories falsely implies ranking).
- Effectiveness: give the most important attribute the most accurate channel
  available. Reserve weak channels (area, colour) for secondary or categorical
  attributes, or for gist rather than precise reading.

1.3 How the ranking drives the DEFAULT chart choice

  Rule R1  If the task is "compare values precisely," put the values on a common
           position scale: bars or dots on a shared axis. This is the default
           for ranking and magnitude.
  Rule R2  If you must compare across many groups, use small multiples so every
           panel keeps position-on-a-common-scale internally, rather than
           overloading one panel with colour/area.
  Rule R3  Colour HUE encodes category only, and never as the sole encoding
           (a11y + theme survival). Colour LUMINANCE/SATURATION can encode order
           but is weak: always pair with value labels or a legend, and never use
           it for a comparison that must be read precisely.
  Rule R4  Area and angle are last-resort quantitative channels. If magnitude is
           the message, do not encode it as area (bubble) or angle (pie); use
           position/length. Area is acceptable only as a secondary encoding or
           where the honest variant rules in Part 4 are met.
  Rule R5  Match channel type to data type: ordered data to a magnitude channel,
           categorical data to an identity channel. Mismatches mislead.

1.4 The zero-baseline subtlety (consequence of R1 and the ranking)

  - LENGTH encodings (bars, area, columns) are decoded from a baseline. If the
    baseline is not zero, the length no longer maps to the value and the chart
    lies. Bars therefore MUST start at zero. This is why "truncated axis by
    default" is in the app's reject list.
  - POSITION encodings (dots on a scale, line vertices) are decoded as position,
    not length. A non-zero, well-labelled range is defensible for dot plots and
    line charts when zero is not a meaningful anchor (e.g. body temperature,
    a stock index). The rule the app should enforce: zero baseline is mandatory
    for length/area marks; for position marks a non-zero range is allowed only
    when explicitly annotated and never as a silent default.


===============================================================================
PART 2 - THE UNIVERSAL GATE (every chart must pass before it ships)
===============================================================================

2.1 Honesty gate (any failure = reject, not "trade-off")

  H1  No composite scores. Do not sum or average incommensurable units into one
      mark or one axis. If stakeholders want a single number, show the
      components side by side (faceted bars/dots) and let the reader combine.
  H2  Missing data is a visible gap. Never interpolate, never connect a line
      across a gap, never fill a map region from neighbours. Render "no data"
      with a distinct non-scale treatment (a break in the line; a hatched or
      explicitly-labelled cell, never a colour drawn from the value ramp).
  H3  No causation implied from co-occurrence. A trend line or correlation is an
      association. Never word, annotate, or style a chart so co-movement reads
      as mechanism. (See Part 5, regression-implies-cause.)
  H4  No geometry that distorts magnitude: no 3D for quantities, no truncated
      length axes by default, no area as the primary quantitative channel unless
      the Part 4 honesty variant is met (correct area scaling, legend, secondary
      role).
  H5  Deterministic output. The same data must produce the same pixels. No
      Math.random in layout. If jitter or a force layout is unavoidable, seed it
      (see Appendix A6) so the result is reproducible.

2.2 Accessibility gate (Chartability-aligned; Elavsky et al. 2022)

  A1  Text equivalent. Each chart is exposed as role="img" with a one-sentence
      aria-label that states the takeaway (not "bar chart"), and is backed by a
      real data table that is the chart's content, not a screenshot caption.
      (Chartability "Perceivable" and "Understandable".) See Appendix A3.
  A2  Not colour alone. Every distinction carried by colour must also be carried
      by position, shape, pattern, or a direct label. This is what lets the same
      chart survive 17 themes, dark/light, and colour-vision deficiency.
  A3  Theme survival. No hardcoded colours. Drive all fills/strokes from CSS
      custom properties (or currentColor); for Canvas, read the computed values
      and redraw on theme change. Do not assume a light background.
  A4  RTL. Mirror reading-order and category order, and flip the time axis to run
      right-to-left, for RTL locales; keep numeric magnitude meaning unchanged
      (positive is still "more"); keep number/date formatting locale-aware.
      See Appendix A5.
  A5  Operable. Any interactive element is keyboard reachable with a visible
      focus state and a sensible focus order (Chartability "Operable").
  A6  No seizure / no motion trap. Avoid flashing; respect
      prefers-reduced-motion; never make animation the only way to read a value.

2.3 No-library / performance gate (vanilla SVG and Canvas only)

  Pick the renderer by mark count and interaction needs:
  - SVG: DOM-based, each mark is inspectable and natively accessible, crisp at
    any zoom, themable by CSS variables. Comfortable up to ~1,000-2,000 marks;
    degrades past that from DOM size and layout cost.
  - Canvas: immediate-mode raster, comfortable into the 10,000s of marks, but has
    no DOM (so accessibility and hit-testing are manual), is resolution-dependent
    (handle devicePixelRatio), and must be redrawn on theme change.
  - Hybrid (recommended for dense data): Canvas for the data layer, SVG/HTML for
    axes, ticks, labels, legend, and interaction targets. This keeps labels crisp
    and accessible while the dense layer stays fast.
  Two reusable building blocks you must hand-roll (no D3): a linear scale and a
  "nice" tick generator. See Appendix A1 and A2.


===============================================================================
PART 3 - DATA-SHAPE -> TECHNIQUE MATRIX (deliverable 1)
===============================================================================

Columns: Intent | Typical data shape | Default technique | Why (perceptual basis)
| Honest variant / guardrail | Rejected here (use Part 5)

| Intent | Data shape | Default technique | Why (perceptual) | Honest variant / guardrail | Rejected here |
|---|---|---|---|---|---|
| Change over time | 1 value per time step, one or few series, evenly spaced ordered time | Line chart (multi-line if few series) | Time is ordered; position on common scale (rank 1) reads trend and level | Break the line at gaps (H2); zero baseline only if value is length-like, else annotate non-zero; small multiples once series > ~4 | Dual-axis abuse; streamgraph as primary |
| Change over time, compact / many series | Same, but dozens of series or inline | Sparklines / small-multiple lines | Each panel keeps position-on-common-scale; avoids colour overload (R2,R3) | Shared y-range across panels or label each range; mark gaps | Single overplotted spaghetti line chart |
| Ranking | One quantitative value per category, order is the message | Sorted bar chart; dot plot when many categories or non-zero range | Length/position from common scale (rank 1-3); sorting makes order direct | Bars from zero (H4); dot plot allows non-zero with labels; horizontal bars for long labels and RTL | 3D pie; radar; word cloud |
| Part-to-whole | Components summing to a meaningful 100% at one time | Sorted bars of the shares, or a single stacked bar | Bar length on common scale beats angle/area for reading shares | Pie/donut only if <=4-5 slices, share labels shown, and precise comparison is not required; otherwise bars | 3D pie; many-slice pie; treemap when values are not nested |
| Part-to-whole over time | Components summing to 100% across ordered time | Small-multiple lines of each share, or 100% stacked area | Per-series lines keep a common baseline; 100% area fixes the total | Only top band and total are read accurately in stacked area; mark gaps; cap series count | Streamgraph; stacked area with wiggling baseline |
| Distribution | Many observations of one variable | Histogram; add a strip/jitter or quantile dots for raw points | Binned counts on position scale; raw dots avoid hiding n | State bin width and n; do not KDE-smooth small n (implies data you lack) | Smooth density curve over sparse n presented as fact |
| Distribution, compare groups | One variable across several groups | Faceted histograms, or box plot plus overlaid points | Faceting keeps common scale; points expose sample size behind the summary | Box plot must show n and define whiskers; never a box over n < ~10 without points | Box plot alone hiding tiny n |
| Correlation | Two quantitative variables, paired | Scatter plot (<= a few thousand points) | Two position scales (rank 1) read joint structure directly | Describe as association not cause (H3); if a fit is shown, label it descriptive, show CI, never imply mechanism | Regression-implies-cause; dual-axis time series posing as correlation |
| Correlation, dense | Two variables, ~10k+ points | 2D histogram / hexbin (binned density) | Binning resolves overplotting honestly and is far cheaper to render | Show the count legend; keep bin size disclosed; missing region != zero region | Tiny semi-transparent dots that hide density and mislead on mass |
| Flow / movement | Quantified flows between states or nodes | Sankey (few nodes), or a flow map for geographic flow | Width encodes magnitude along a path; acceptable when nodes are few | Width is a length encoding: keep it proportional, no gaps invented; label totals | Streamgraph; chord diagram as primary when precise comparison needed |
| Network | Nodes and edges, relational | Adjacency matrix for dense graphs; node-link only for small/sparse graphs | Matrix cell position is rank 1 and is deterministic; node-link readability collapses and layout is often non-deterministic (H5) | If node-link, use a deterministic, seeded or fixed layout; order matrix rows meaningfully | Force-directed node-link with random seed (non-deterministic) |
| Hierarchy | Nested categories, parent-child | Indented tree / outline; icicle (aligned bars) for sizes | Indented text is the most accessible and exact; icicle uses aligned length | Treemap only when leaf MAGNITUDE matters and nesting is real; size by area correctly | Sunburst when precise comparison needed (angle/area); treemap for non-nested data |
| Spatial | Values tied to real geography where location is the point | Choropleth for rates/ratios; proportional-symbol map for counts/magnitude | Map position is the message; choropleth's colour is weak so it suits normalised rates, not raw counts | Choropleth only for normalised values; symbols sized by area (radius proportional to sqrt of value); "no data" hatched (H2) | Choropleth of raw counts (reads population, not phenomenon); 3D prism maps |
| Magnitude (comparison) | Discrete quantities to compare, possibly against a target | Bar chart; bullet graph when comparing to a target/threshold | Length/position from common scale (rank 1-3) | Zero baseline (H4); bullet graph keeps a single quantitative axis with reference marks | Bubble area as the primary magnitude encoding; 3D bars |
| Uncertainty | Estimates with intervals, or sparse/missing data | Dot plot with error bars; span/dumbbell for ranges; quantile dotplots for lay readers | Interval endpoints on a position scale read directly; quantile dots frame probability as frequency | Define the interval (95% CI vs SD vs SE) in the label; gaps for missing (H2); see Part 6 for fan-chart rules | Fan chart over non-forecast data; smooth bands not derived from a model |
| Two-state change | One value at exactly two points (before/after, A/B) | Slopegraph (slope chart); dumbbell/connected dot plot | Both states on a common position scale; the slope's sign and steepness are read directly | Equal, labelled scales at both ends; no third interpolated point implied | Two separate pies; dual-axis trickery; arrows on a distorted scale |


===============================================================================
PART 4 - TECHNIQUE CATALOGUE (deliverable 2)
===============================================================================

For each technique: (a) how it can mislead and how to prevent it; (b) the a11y
text-equivalent pattern; (c) the no-library feasibility note with rough approach
and performance at ~200 countries and ~10k points. Shared patterns (scale,
ticks, role=img+table, gaps, Canvas DPR, RTL, seeded jitter) live in the
Appendix and are referenced rather than repeated.

-------------------------------------------------------------------------------
4.1 LINE CHART (and multi-line)
-------------------------------------------------------------------------------
Honesty checklist:
- Connecting across missing time steps fabricates data. Prevention: split the
  path at any gap; render a visible break; never draw through nulls (H2).
- A non-zero y-axis can exaggerate or flatten a trend. Prevention: zero baseline
  if the reader will judge magnitude as length; otherwise a labelled non-zero
  range, never silent (Part 1.4).
- Heavy smoothing/interpolation between sparse points implies resolution you do
  not have. Prevention: plot the actual vertices; only smooth when the
  underlying signal is genuinely continuous and dense.
- Many coloured lines exceed what colour can distinguish. Prevention: direct
  end-of-line labels; switch to small multiples past ~4 series (R2,R3).
a11y text-equivalent: role="img" with aria-label stating the overall direction
and end values; backed by a table of time x series values, with empty cells for
gaps (not zeros). SVG <title>/<desc> via aria-labelledby. (Appendix A3.)
No-library feasibility: build one <path> per series with a hand-rolled linear
scale (A1) and 1-2-5 ticks (A2). At 200 points/series: trivial in SVG. At ~10k
total vertices: a single path with 10k commands is fine in SVG (one element);
many short paths are the cost, so keep series count low or draw the data layer
to Canvas (A4) and keep axes in SVG. Gaps: emit separate subpaths (M ... ) per
contiguous run; do not use a single L across the gap (A7).

-------------------------------------------------------------------------------
4.2 SPARKLINE / SMALL-MULTIPLE LINES
-------------------------------------------------------------------------------
Honesty checklist:
- Independent per-panel y-ranges make panels look comparable when they are not.
  Prevention: shared y-range across panels, or print each panel's range.
- Cropping hides outliers. Prevention: never clip without a marked break.
a11y text-equivalent: each panel role="img" with its own one-line label; one
shared data table with a column per panel; a caption stating the shared scale.
No-library feasibility: a CSS grid of tiny inline SVGs, one path each. 200 panels
of ~50 points is fine in SVG. For thousands of panels, virtualise (render only
on-screen panels) or draw to a single Canvas tiled by panel.

-------------------------------------------------------------------------------
4.3 BAR CHART (vertical/horizontal, grouped)
-------------------------------------------------------------------------------
Honesty checklist:
- Truncated baseline turns length into a lie (length is decoded from the
  baseline). Prevention: baseline at zero, always (H4). If a log scale is needed,
  label it loudly and never call the bar lengths comparable as ratios-by-length.
- Reordering categories to flatter a story. Prevention: sort by value or a fixed
  meaningful order; disclose the ordering.
- Grouped bars with too many series rely on colour. Prevention: cap series;
  consider faceting; direct-label where possible.
a11y text-equivalent: role="img" with aria-label naming the top and bottom
categories and the spread; data table of category x value. Bars carry a
text/pattern distinction in addition to colour (A2).
No-library feasibility: one <rect> per bar; labels as <text>. 200 bars: trivial
in SVG. 10k bars are rarely meaningful (aggregate first); if truly needed, Canvas
rects. Horizontal bars are preferable for long labels and adapt cleanly to RTL
(A5).

-------------------------------------------------------------------------------
4.4 DOT PLOT (Cleveland dot plot)
-------------------------------------------------------------------------------
Honesty checklist:
- A non-zero axis is allowed (position, not length) but can still mislead if
  unlabelled. Prevention: clear axis, gridlines, and direct value labels.
- Sorting games. Prevention: disclose ordering; offer alphabetical and by-value.
a11y text-equivalent: role="img" with aria-label of range and leader/laggard;
table of category x value. Dots distinguished by shape if multiple series (A2).
No-library feasibility: one <circle> + one <text> per category, optional leader
line as a thin <line>. Ideal for ~200 categories in SVG (cleaner than 200 bars).
Scales as in A1/A2.

-------------------------------------------------------------------------------
4.5 SLOPEGRAPH (two-state change)
-------------------------------------------------------------------------------
Honesty checklist:
- Different left/right scales fabricate slopes. Prevention: identical, labelled
  scales at both ends.
- Implying a path between the two points. Prevention: state that only two
  measured states exist; do not interpolate a middle value.
a11y text-equivalent: role="img" with aria-label summarising who rose/fell most;
table with columns "state A", "state B", and the delta.
No-library feasibility: two value axes and one <line> + two labels per item.
200 items fine in SVG; cross-label collisions are the main issue (nudge labels
deterministically, never randomly, H5).

-------------------------------------------------------------------------------
4.6 SMALL MULTIPLES / FACETING (cross-cutting technique)
-------------------------------------------------------------------------------
Honesty checklist:
- Per-panel scales kill comparability. Prevention: one shared scale unless an
  explicit, labelled reason to differ.
- Inconsistent panel ordering. Prevention: a single, disclosed ordering.
a11y text-equivalent: a figure with one caption describing the shared scale and
the cross-panel pattern; one table with a facet column. Each panel may also be
role="img" individually.
No-library feasibility: CSS grid of small SVGs sharing computed scales. Cheap and
deterministic. For very many panels, virtualise rendering.

-------------------------------------------------------------------------------
4.7 SCATTER PLOT (correlation)
-------------------------------------------------------------------------------
Honesty checklist:
- A fitted line invites a causal read. Prevention: word it as association (H3);
  if a fit is drawn, label it "descriptive trend," show its CI band, and add a
  note that it is not evidence of cause; consider faceting by a suspected
  confounder instead.
- Overplotting hides density and outliers. Prevention: at scale, bin (4.8).
- Non-zero axes are fine (position) but axis breaks must be marked.
a11y text-equivalent: role="img" with aria-label of the direction and strength of
association (in words, not just r); a table of the points if small, or a binned
summary table if large; never imply cause in the label.
No-library feasibility: one <circle> per point. Up to ~1-2k points in SVG is
fine. At ~10k points SVG becomes janky (10k DOM nodes); draw points to Canvas
(A4) with axes in SVG, or bin to a hexbin/2D histogram (4.8), which is both
faster and more honest. Hit-testing on Canvas: keep the data array and find the
nearest point by math on pointer events.

-------------------------------------------------------------------------------
4.8 2D HISTOGRAM / HEXBIN (dense correlation)
-------------------------------------------------------------------------------
Honesty checklist:
- Colour (luminance) is a weak quantitative channel; readers cannot rank cells
  precisely. Prevention: always show a count legend and consider labelling
  notable cells; do not ask for precise cell-to-cell comparison.
- Empty bins are not "zero phenomenon," they are "no observation here."
  Prevention: leave true gaps unfilled or mark them distinctly (H2).
- Bin size changes the story. Prevention: disclose bin size; offer a control.
a11y text-equivalent: role="img" with aria-label describing where mass
concentrates; a table of bin coordinates x count (downsampled if huge).
No-library feasibility: aggregate 10k points into a grid (a few hundred cells),
then draw a few hundred <rect>/<polygon> in SVG. This collapses 10k DOM nodes to
~hundreds and is the recommended path. Binning is O(n) over the points, done once.

-------------------------------------------------------------------------------
4.9 HISTOGRAM (distribution of one variable)
-------------------------------------------------------------------------------
Honesty checklist:
- Bin width is an editorial choice that can manufacture or erase modes.
  Prevention: state bin width; offer alternatives; avoid a single "magic" bin
  count for skewed data.
- Truncated count axis. Prevention: zero baseline (counts are length, H4).
a11y text-equivalent: role="img" with aria-label of shape (skew, modality, n);
table of bin range x count.
No-library feasibility: bin once (O(n)), draw one <rect> per bin. 50-100 bins is
trivial in SVG regardless of underlying n (10k+ points reduce to <=100 bars).

-------------------------------------------------------------------------------
4.10 BOX PLOT / STRIP / QUANTILE DOTS (distribution summary)
-------------------------------------------------------------------------------
Honesty checklist:
- A box hides n and the raw shape; over a tiny sample it implies robustness it
  lacks. Prevention: print n; overlay the raw points (strip/jitter) for small n;
  do not box n below ~10 without showing points.
- Whisker definitions vary. Prevention: state the rule (e.g. 1.5x IQR) in a note.
- Jitter, if used, must be reproducible. Prevention: seed it (A6, H5).
a11y text-equivalent: role="img" with aria-label of median, spread, and n; table
of the five-number summary plus n, per group.
No-library feasibility: a handful of <line>/<rect> per group plus <circle> for
points. Trivial in SVG for up to a few hundred groups; for thousands of raw
points per group, draw points to Canvas and keep the box geometry in SVG.

-------------------------------------------------------------------------------
4.11 STACKED BAR / 100% STACKED AREA (part-to-whole, incl. over time)
-------------------------------------------------------------------------------
Honesty checklist:
- Only the bottom band and the total are read from a true baseline; middle bands
  float and are hard to compare. Prevention: limit series; put the series you
  most want compared on the baseline; for cross-series comparison prefer
  small-multiple lines of the shares.
- A wiggling baseline (streamgraph) removes the common baseline entirely.
  Prevention: do not use it as primary (Part 5).
- Gaps in a stacked area. Prevention: break the band; do not bridge (H2).
a11y text-equivalent: role="img" with aria-label of which component dominates and
how the mix shifts; table of category/time x component shares.
No-library feasibility: cumulative sums then one <rect> (bar) or one <path>
(area) per series. Cheap in SVG for typical series counts and ~200 time steps.

-------------------------------------------------------------------------------
4.12 SANKEY / FLOW (and flow map)
-------------------------------------------------------------------------------
Honesty checklist:
- Link width is a length encoding; non-proportional widths lie. Prevention: width
  strictly proportional to flow; conserve totals in equals out unless leakage is
  shown explicitly.
- Inventing flows to "complete" a diagram. Prevention: only measured flows;
  unknown is shown as unknown, not smoothed (H2).
- Node ordering can imply a process that does not exist. Prevention: disclose
  ordering; keep it deterministic (H5).
a11y text-equivalent: role="img" with aria-label of the dominant flow(s); table
of source x target x value.
No-library feasibility: compute node positions deterministically (topological
layering, no random); draw links as <path> beziers, nodes as <rect>. Feasible by
hand for tens of nodes; readability (not perf) is the limiting factor. A flow map
is a base map plus proportional <path> or symbol overlays (see 4.16).

-------------------------------------------------------------------------------
4.13 ADJACENCY MATRIX (dense networks)
-------------------------------------------------------------------------------
Honesty checklist:
- Row/column order changes the apparent structure. Prevention: a disclosed,
  deterministic ordering (e.g. by a stable attribute or a deterministic
  seriation); never a random permutation (H5).
- Colour-only cell encoding is weak and theme-fragile. Prevention: redundant
  encoding (value text on hover/focus, or size within cell), and a legend (A2).
a11y text-equivalent: role="img" with aria-label of overall density/clusters; the
matrix itself is naturally a data table (use a real <table>).
No-library feasibility: an N x N grid of <rect> is N^2 cells; 200 nodes = 40,000
cells, which is too many for SVG. Draw the matrix to Canvas (A4) and keep axis
labels in SVG/HTML; hit-test by mapping pointer x,y to row,col arithmetically.

-------------------------------------------------------------------------------
4.14 NODE-LINK DIAGRAM (small/sparse networks only)
-------------------------------------------------------------------------------
Honesty checklist:
- Force-directed layouts are typically non-deterministic and reposition on every
  run; the same data yields different pictures, violating H5. Prevention: use a
  deterministic layout (layered, circular, or a fixed-seed force run for a fixed
  iteration count, A6), and cache positions.
- Spatial proximity can imply relationships that the edges do not assert.
  Prevention: keep layouts simple; do not over-read clusters; prefer a matrix
  (4.13) when the graph is dense.
a11y text-equivalent: role="img" with aria-label of node/edge counts and notable
hubs; a table of edges (source x target), and optionally node degrees.
No-library feasibility: <line> for edges, <circle>+<text> for nodes. Fine in SVG
for up to a few hundred nodes/edges; beyond that, prefer the matrix.

-------------------------------------------------------------------------------
4.15 HIERARCHY: INDENTED TREE, ICICLE, TREEMAP
-------------------------------------------------------------------------------
Honesty checklist:
- Treemap area is a weak channel and small differences are unreadable; aspect
  ratio distorts comparison. Prevention: use treemap only when leaf MAGNITUDE in
  a real nesting is the point; label values; do not ask for precise area ranking.
- Sunburst encodes by angle/area (two weak channels) and is worse than an icicle
  for reading sizes. Prevention: prefer an icicle (aligned rectangles, length) or
  an indented tree for exactness (see Part 5).
- A treemap over non-nested data is a category error. Prevention: require a true
  parent-child structure.
a11y text-equivalent: an indented tree is already accessible as a nested list
(<ul>/role=tree). For icicle/treemap: role="img" with aria-label of the largest
branches, plus a table of path x value.
No-library feasibility: indented tree = HTML list, trivial and the most
accessible. Icicle = one <rect> per node from a recursive partition, cheap.
Treemap = a squarified slice-and-dice computed in plain JS (O(n)); a few hundred
leaves render fine in SVG.

-------------------------------------------------------------------------------
4.16 SPATIAL: CHOROPLETH AND PROPORTIONAL-SYMBOL MAP
-------------------------------------------------------------------------------
Honesty checklist:
- A choropleth of raw counts mostly maps population/area, not the phenomenon.
  Prevention: choropleth only for normalised values (rate, ratio, density); use
  proportional symbols for counts/magnitude.
- Symbol AREA must encode the value, so radius is proportional to sqrt(value);
  radius-proportional sizing inflates large values dramatically. Prevention:
  sqrt scaling; show a size legend with reference values.
- Missing regions filled from the colour ramp read as real low values.
  Prevention: a distinct "no data" treatment (hatch/pattern), never a ramp colour
  (H2).
- Colour bins (luminance) are weak and theme-fragile. Prevention: clear legend;
  redundant labels on hover/focus; ensure the ramp works in dark and light and
  for CVD (A2, A3).
a11y text-equivalent: role="img" with aria-label of the high/low regions and the
pattern; a table of region x value (and a "no data" marker), which is also the
fallback for screen readers who cannot parse the map shapes.
No-library feasibility: choropleth = one <path> per region from pre-simplified
geometry. 200 countries = 200 paths, fine in SVG; simplify geometry offline
(reduce coordinates) to keep path data small. Proportional symbols = one
<circle> per place sized by sqrt(value). Projection math (e.g. equirectangular or
a precomputed projection) is done in plain JS; precompute and cache projected
coordinates so output is deterministic.

-------------------------------------------------------------------------------
4.17 BULLET GRAPH (magnitude vs target)
-------------------------------------------------------------------------------
Honesty checklist:
- Qualitative range bands can be drawn to flatter performance. Prevention: define
  bands from a fixed, disclosed rule; keep one quantitative axis from zero (H4).
a11y text-equivalent: role="img" with aria-label of value vs target and band; a
table of value, target, and band thresholds.
No-library feasibility: a few <rect> (bands + measure) and one <line> (target)
per metric. Trivial in SVG; ideal for compact dashboards.

-------------------------------------------------------------------------------
4.18 SPAN / DUMBBELL / ERROR-BAR DOT PLOT (ranges and intervals)
-------------------------------------------------------------------------------
Honesty checklist:
- An interval with no definition is meaningless or misleading. Prevention: state
  exactly what the interval is (95% CI vs SD vs SE vs min-max) in the label.
- Treating the dot as the certain value and the bar as decoration. Prevention:
  give the interval visual weight; never crop it.
a11y text-equivalent: role="img" with aria-label naming the widest/narrowest
intervals; a table of category, point estimate, lower, upper, and interval type.
No-library feasibility: one <line> (the span) plus one or two <circle> per row.
Trivial in SVG for ~200 rows.


===============================================================================
PART 5 - REJECT OR CONSTRAIN (deliverable 3)
===============================================================================

Each entry: the problem in perceptual/honesty terms, the verdict, and the honest
replacement that satisfies Part 2. These verdicts are findings.

5.1 Radar / spider chart
  Problem: encodes by area and angle (both low on the ranking); the enclosed
  area scales with the square of values, exaggerating differences; axis order is
  arbitrary and changes the silhouette; it invites a single "shape = overall
  score" read, i.e. a composite (violates H1, H4, R4).
  Verdict: REJECT as a primary comparison or scoring chart.
  Replacement: small multiples of bar/dot plots, one panel per entity, sharing a
  common scale; or a grouped dot plot per dimension; for profile comparison
  across two entities, a slopegraph per dimension. Never sum the axes.

5.2 Streamgraph
  Problem: no common baseline; every series floats on a wiggling base, so only
  the total and gross magnitude are readable and individual series cannot be
  compared (defeats R1); gaps and zeros are ambiguous; aesthetics over function.
  Verdict: REJECT as primary. Constrain to ambient/gist use only, never for
  reading values.
  Replacement: small-multiple lines of each series (or each share) on a common
  baseline; or a 100% stacked area when only the mix and total matter, with
  series capped and gaps broken (H2).

5.3 3D pie chart
  Problem: takes the two weakest channels (angle, area) and distorts them
  further with perspective and occlusion; foreground slices look larger
  (violates H4).
  Verdict: REJECT unconditionally.
  Replacement: sorted horizontal bars with share labels; a flat 2D pie only if
  <=4-5 slices and precise comparison is not needed.

5.4 Dual-axis abuse
  Problem: two independent y-scales let the author slide the curves until they
  appear to track, manufacturing correlation and implying causation (violates
  H3); the "crossover point" is an artefact of scale choice.
  Verdict: REJECT the abuse. Constrain: dual axes are acceptable only when the
  two scales are a deterministic transform of each other (e.g. Celsius and
  Fahrenheit) - one variable, two labellings.
  Replacement: index both series to 100 at a base period on ONE axis to compare
  growth; or two small-multiple charts sharing the x-axis; or, to show the
  relationship explicitly, a scatter / connected scatter with the association (
  not cause) clearly worded.

5.5 Regression-implies-cause
  Problem: a fitted line plus an r or R-squared invites readers to treat
  co-occurrence as mechanism (violates H3).
  Verdict: REJECT the framing (the scatter itself is fine).
  Replacement: present the scatter; describe the relationship as association;
  if a fit is shown, label it a descriptive trend, show its uncertainty band,
  and add a one-line note that it is not evidence of cause; where a confounder is
  suspected, facet by it (small multiples) so the reader sees the structure.

5.6 Bubble chart with area as the primary quantity
  Problem: area is rank 4 and is systematically under-estimated for large
  circles; sizing by diameter instead of area roughly squares the lie (violates
  H4, R4).
  Verdict: CONSTRAIN. Never use area as the primary magnitude encoding.
  Replacement: if magnitude is the message, use bars/dots (position/length). Use
  bubbles only as a secondary, third-variable encoding on a scatter, always with
  radius proportional to sqrt(value) and a size legend with reference values, and
  never as the value the reader must rank.

5.7 Word cloud as a primary (quantitative/ranking) chart
  Problem: frequency is encoded by font size (area-like), confounded by word
  length (longer words look bigger regardless of count); layout is usually
  random, so the same data yields different pictures (violates H5); colour is
  decorative; there is no axis to read against.
  Verdict: REJECT as a primary comparison. Constrain to decorative/qualitative
  gist only, never to compare magnitudes.
  Replacement: a sorted horizontal bar chart of the top-N terms by frequency
  (length/position on a common scale), with a disclosed ordering.

5.8 Truncated length axis by default (cross-cutting)
  Problem: a bar/area whose baseline is not zero breaks the length-to-value
  mapping (violates H4).
  Verdict: REJECT as a default. Bars and area start at zero. A non-zero range is
  permitted only for position encodings (dots, lines) and only when explicitly
  annotated (Part 1.4).

5.9 Interpolating or smoothing across missing data (cross-cutting)
  Problem: bridging gaps with a line, a band, or a filled map region fabricates
  observations (violates H2).
  Verdict: REJECT. Render gaps as gaps; mark "no data" distinctly.


===============================================================================
PART 6 - UNCERTAINTY-HONEST TECHNIQUES (deliverable 4)
===============================================================================

6.1 Separate the kinds of uncertainty (they need different treatments)

  - Sampling/estimation uncertainty: you have an estimate and an interval.
  - Missing data: you have no observation for some points.
  - Small-n: you have very few observations.
  - Forecast/model uncertainty: you are projecting beyond the data with a model.

  These must not be conflated. In particular, missing-data and small-n are NOT
  forecast uncertainty, and must never be drawn with forecasting devices (fans).

6.2 Honest techniques and how to keep them honest

  Error bars / interval bars on dot plots
    Use: show a point estimate with its interval. Keep honest: state the interval
    type (95% CI vs SE vs SD) in the label; give the interval visual weight; do
    not crop it; do not present the point as certain. Implements as 4.18.

  Span / dumbbell / range bars
    Use: min-max or interval-to-interval. Keep honest: label the endpoints'
    meaning; equal scales; no invented midpoint. Implements as 4.18.

  Quantile dotplots (frequency-framed intervals)
    Use: represent a predictive or sampling distribution as a row of dots, each
    dot = one chance out of N. Lay readers decode frequency better than abstract
    bands. Keep honest: state N and the distribution source. No-library: just
    <circle> marks placed by quantile; cheap and deterministic.

  Gradient / density strips and violins (full distribution)
    Use: show the whole shape of an estimate's distribution. Keep honest: these
    rely on luminance/area (weak channels) and can be over-read; pair with a
    summary (median, interval) and define the distribution. Prefer quantile dots
    for general audiences.

  Gaps for missing data
    Use: the absence is the honest signal. Keep honest: break lines into
    subpaths; hatch or label "no data" on maps and matrices; never a ramp colour
    or a zero (H2). No-library: A7 (line gaps), distinct pattern fill for maps.

  Sparse-n handling
    Use: plot the actual points (strip/dot); annotate n. Keep honest: do not draw
    a confident smooth curve or KDE through a handful of points; do not box n<~10
    without showing points. Implements as 4.10.

6.3 The fan chart: legitimate vs deceptive

  A fan chart shows a central projection with bands that widen into the future to
  represent a predictive distribution (the Bank of England inflation fan and
  weather ensemble cones are the canonical legitimate examples).

  Legitimate ONLY when all of the following hold:
    F1  The banded region is genuinely the FUTURE or an explicit projection, not
        observed history.
    F2  The bands are real quantiles of a defined predictive distribution from a
        stated model (e.g. 50/80/90% predictive intervals), not hand-drawn.
    F3  The boundary between observed data and projection is visually explicit
        (solid past, banded future), so no one mistakes projection for record.
    F4  The central line is not presented as "the" outcome; the spread is the
        point, and false precision at the center is avoided.
    F5  The horizon is bounded to where the model is meaningful; the fan does not
        trail off into a region the model cannot support.

  Deceptive (REJECT) when any of these occur:
    - A fan is drawn over data that is not a forecast, to "look like uncertainty."
    - Bands are fabricated, not derived from a model (violates H1-style invention).
    - The fan spans MISSING historical data, i.e. interpolation dressed as
      uncertainty (violates H2).
    - Observed and projected are not visually separated, so projection reads as
      fact (violates F3).
    - The central line is emphasised as a prediction while the bands are cosmetic
      (false precision).

  App rule: enable a fan only inside an explicitly labelled forecast view with
  model-derived quantiles and an explicit observed/projected boundary. Outside
  that, represent uncertainty with error bars, spans, quantile dots, or gaps.

  No-library feasibility: bands are nested <path> areas (one per quantile pair)
  using the linear scale (A1); the observed segment is a solid <path>, the
  projected segment is the banded region with a visible boundary marker. Cheap in
  SVG. Keep the quantile inputs in the data, never synthesised at render time
  (H5).


===============================================================================
PART 7 - QUICK DECISION PROCEDURE (deterministic, text form)
===============================================================================

Step 1  Name the single analytical intent (the column in Part 3). If two intents
        compete, split into two charts; do not overload one (and never composite,
        H1).
Step 2  Identify the data shape and the data types (ordered vs categorical).
Step 3  Pick the default technique from Part 3 using the highest-accuracy channel
        the comparison allows (Part 1: position > length > angle > area > colour).
Step 4  Run the honesty gate (Part 2.1). If the candidate cannot pass (e.g. it
        needs a wiggling baseline, area-as-magnitude, or interpolation), switch
        to the honest variant or the Part 5 replacement. Record the rejection.
Step 5  Run the a11y gate (Part 2.2): write the one-sentence takeaway label and
        the backing data table now, not later; ensure non-colour redundancy,
        theme tokens, RTL handling, keyboard access.
Step 6  Run the no-library gate (Part 2.3): choose SVG, Canvas, or hybrid by mark
        count; for 10k+ points, bin (4.8) or move the data layer to Canvas (A4);
        for 200 regions/categories SVG is fine.
Step 7  Make output deterministic (H5): no random layout/jitter; seed if needed
        (A6); cache projected/laid-out coordinates.


===============================================================================
APPENDIX - SHARED VANILLA-JS PATTERNS (no libraries)
===============================================================================

A1. Linear scale (replace d3.scaleLinear)
```js
function linearScale(d0, d1, r0, r1) {
  const m = (r1 - r0) / (d1 - d0);
  const f = v => r0 + (v - d0) * m;
  f.invert = p => d0 + (p - r0) / m;
  return f;
}
// x = linearScale(xmin, xmax, padLeft, width - padRight);
```

A2. "Nice" 1-2-5 ticks (replace d3 ticks)
```js
function niceTicks(min, max, target = 6) {
  const span = max - min || 1;
  const raw = span / target;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
  const start = Math.ceil(min / step) * step;
  const ticks = [];
  for (let t = start; t <= max + 1e-9; t += step) ticks.push(+t.toFixed(10));
  return ticks; // deterministic, no randomness
}
```

A3. Text-equivalent pattern (role=img + real data table; Chartability-aligned)
```html
<figure>
  <svg role="img" aria-labelledby="t1 d1" viewBox="0 0 640 360">
    <title id="t1">Revenue by region, 2025</title>
    <desc id="d1">North leads at 4.2M; South is lowest at 0.9M. EU data is missing for Q3.</desc>
    <!-- marks -->
  </svg>
  <figcaption>
    <table>
      <caption>Revenue by region, 2025 (USD millions)</caption>
      <thead><tr><th scope="col">Region</th><th scope="col">Revenue</th></tr></thead>
      <tbody>
        <tr><th scope="row">North</th><td>4.2</td></tr>
        <tr><th scope="row">EU (Q3)</th><td>no data</td></tr>
        <!-- empty cell uses "no data", never 0 -->
      </tbody>
    </table>
  </figcaption>
</figure>
```
Notes: the table IS the content, not decoration. The aria-label/desc states the
takeaway, not "a chart." Empty data is "no data," never zero (H2).

A4. Canvas data layer with crisp rendering (devicePixelRatio)
```js
function setupCanvas(canvas, cssW, cssH) {
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(cssW * dpr);
  canvas.height = Math.round(cssH * dpr);
  canvas.style.width = cssW + 'px';
  canvas.style.height = cssH + 'px';
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return ctx;
}
// 10k points: clear, then loop fillRect/arc once; redraw on theme/resize.
// Accessibility: give the <canvas> role="img" + aria-label, and render the
// same data as a hidden <table> (A3). Hit-test by nearest-point math on the
// stored data array (canvas has no DOM nodes).
```

A5. Theme tokens + RTL
```css
/* No hardcoded colours: every series reads a CSS variable.
   This is what survives 17 themes + dark/light. */
.series-1 { fill: var(--c-series-1); stroke: var(--c-series-1); }
.axis      { stroke: var(--c-axis); }
/* RTL: flip reading/category order and run the time axis right-to-left.
   Magnitude meaning is unchanged (positive is still "more"). */
[dir="rtl"] .chart { direction: rtl; }
```
```js
// Canvas reads the same tokens, then redraws when the theme changes:
const css = getComputedStyle(document.documentElement);
const c1 = css.getPropertyValue('--c-series-1').trim();
// observe theme class changes / matchMedia('(prefers-color-scheme: dark)') -> redraw
```

A6. Seeded randomness for reproducible jitter/layout (mulberry32) - satisfies H5
```js
function mulberry32(seed) {
  return function () {
    seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
// const rand = mulberry32(1234); // same seed => same pixels, every run
```

A7. Line gaps without interpolation (split into subpaths) - satisfies H2
```js
// points: [{x, y}|null]; null marks a missing step.
function pathWithGaps(points, sx, sy) {
  let d = '', pen = false;
  for (const p of points) {
    if (p == null) { pen = false; continue; }       // break: do not bridge
    d += (pen ? 'L' : 'M') + sx(p.x) + ' ' + sy(p.y) + ' ';
    pen = true;
  }
  return d.trim();
}
```


===============================================================================
END
===============================================================================
Notes on scope and honesty of THIS document:
- Verdicts that reject a technique (Part 5) are deliberate findings.
- The five primary authorities' DOIs/dates were confirmed against publisher
  records on 2026-06-25; supplementary works are cited by bibliographic record.
- No DOI is asserted that was not checked; the Data Viz Catalogue is a web
  resource and is cited without a DOI by design.
