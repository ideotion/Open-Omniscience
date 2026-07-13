// Source-metadata enrichment workflow — fan out batches to web-enabled subagents.
//
// Open Omniscience — GPL-3.0-or-later.
//
// Each subagent classifies ONE batch of sources and returns schema-validated rows,
// so every agent spends its OWN tool-call budget on its OWN ~40 sources (the reason
// fan-out beats a single session for thousands of sources). Output is the merged
// row array in the same shape scripts/merge_enrichment_results.py consumes — write
// it to a .yaml/.json file, then run that merge script (dry-run first) to fold the
// rows into configs/sources.yml additively.
//
// Invoke with args = the under-enriched sources, e.g.:
//   args: [{domain, name, country, language}, ...]   (the input_*.txt rows, parsed)
// Optional args.batchSize (default 40). The script chunks, fans out, and returns
// { rows: [...], batches: N }. It does NOT write files or touch the repo.
//
// Requires explicit opt-in to the Workflow tool (ultracode / "run a workflow").

export const meta = {
  name: 'enrich-sources',
  description: 'Classify under-enriched sources via web-enabled subagents (one batch each)',
  phases: [{ title: 'Classify', detail: 'one subagent per batch, web-search verified' }],
}

const ROW = {
  type: 'object',
  additionalProperties: false,
  required: ['domain', 'source_type', 'topics', 'confidence'],
  properties: {
    domain: { type: 'string' },
    source_type: { type: 'string' },
    ownership: { type: 'string' },
    lean: { type: 'string' },
    topics: { type: 'array', items: { type: 'string' } },
    country: { type: 'string' },
    language: { type: 'string' },
    coverage_scope: { type: 'string' },
    confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
    note: { type: 'string' },
  },
}
const BATCH_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['rows'],
  properties: { rows: { type: 'array', items: ROW } },
}

const RULES = `You classify news/information SOURCES for an offline research catalog.
NEVER fabricate: if unsure of a field, omit it and lower confidence. A wrong tag is
worse than a missing one. Tool budget is limited — answer well-known outlets from
your own knowledge; use web search ONLY to verify an uncertain source, at most one
search per source, no multi-page browsing. Return ALL rows in one structured result.

Fields (orthogonal — keep separate):
- source_type (one): news, wire-agency, magazine, broadcaster, investigative,
  academic-research, scientific-journal, government-primary, igo, ngo-civil-society,
  think-tank, fact-checker, data-portal, blog, religious, financial-data.
- ownership (one, omit if unsure): independent, state-owned, public-broadcaster,
  state-media, corporate, party-affiliated, nonprofit, cooperative, wire-agency.
- lean (omit unless a widely-cited stance exists; most rows: omit): lean-left,
  lean-center-left, center, lean-center-right, lean-right.
- topics (1-4): politics, economy, business, finance, markets, science, technology,
  ai, health, medicine, climate, energy, environment, agriculture, space, defense,
  security, cybersecurity, human-rights, justice, law, migration, education, culture,
  sports, media, religion, local-news, regional, general (or a precise lower-hyphen tag).
- country (ISO-2, only if input shows '?' and you are sure), language (ISO-639-1),
  coverage_scope (local|national|regional|global).
- confidence: high|medium|low. note: <=12 words or "".
If a domain is dead/unidentifiable: {source_type:"news", confidence:"low",
note:"unidentified"} and nothing else. Echo each domain verbatim — it is the join key.`

const sources = Array.isArray(args) ? args : (args && args.sources) || []
const size = (args && args.batchSize) || 40
if (!sources.length) {
  log('No sources passed in args. Pass args: [{domain,name,country,language}, ...]')
  return { rows: [], batches: 0 }
}

const batches = []
for (let i = 0; i < sources.length; i += size) batches.push(sources.slice(i, i + size))
log(`Fanning out ${sources.length} sources across ${batches.length} batch(es) of <=${size}.`)

const results = await parallel(
  batches.map((batch, bi) => () => {
    const table = batch
      .map((s) => `${s.domain} | ${s.name || '?'} | ${s.country || '?'} | ${s.language || '?'}`)
      .join('\n')
    return agent(
      `${RULES}\n\nINPUT (domain | name | country | language):\n${table}`,
      { label: `classify:batch-${bi + 1}`, phase: 'Classify', schema: BATCH_SCHEMA }
    ).then((r) => (r && r.rows) || [])
  })
)

const rows = results.filter(Boolean).flat()
log(`Collected ${rows.length} classified rows from ${batches.length} batch(es).`)
return { rows, batches: batches.length }
