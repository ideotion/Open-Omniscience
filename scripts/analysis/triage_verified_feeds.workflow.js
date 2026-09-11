// Triage of feed-VERIFIED candidate sources -- the only model-spending stage of the candidate
// pipeline (Open Omniscience, 2026-09-10). Paste into the Workflow tool with:
//
//   args = { batches: ["data/candidate_feeds/triage/batch_0001.json", ...],   // from triage_batches.py prepare
//            canaries: "data/candidate_feeds/triage/canaries.json",
//            vocabulary: "data/candidate_feeds/triage/vocabulary.json",
//            model: "haiku", escalate_model: "sonnet", effort: "low" }
//
// Each agent READS its batch file itself (40 rows: domain, name, homepage title, description,
// recent headlines, country, language, the Wikidata type) and WRITES its answers to
// <batch>.result.json, returning only a small summary. Nothing large passes through the
// orchestrator's context, which is where a naive design spends its credit. Two hand-known
// CANARY rows ride every batch: a batch that gets a canary wrong is re-run once on the
// escalation model and, if still wrong, marked untrusted -- its rows are then reviewed by a
// human, never merged. Closed vocabularies throughout; a value outside them is rejected in
// plain code, never coerced.

export const meta = {
  name: 'triage-verified-feeds',
  description: 'Classify feed-verified candidate sources (journalism or not, language, topics) in cheap batches with canaries',
  phases: [
    { title: 'Triage', detail: 'one cheap agent per batch of ~40 rows; canaries in every batch' },
    { title: 'Escalate', detail: 'batches that failed a canary, once, on the stronger model' },
  ],
}

const BATCHES = args.batches
const MODEL = args.model || 'haiku'
const ESCALATE = args.escalate_model || 'sonnet'
const EFFORT = args.effort || 'low'

const KINDS = ['news', 'magazine', 'broadcaster', 'wire-agency', 'investigative', 'fact-checker',
  'academic', 'trade-or-corporate', 'institution', 'religious', 'personal-blog', 'aggregator', 'other']

const SUMMARY = {
  type: 'object',
  required: ['batch', 'answered', 'canary_ok', 'written'],
  properties: {
    batch: { type: 'string' },
    answered: { type: 'integer' },
    canary_ok: { type: 'boolean' },
    written: { type: 'string' },
    note: { type: 'string' },
  },
}

function prompt(batchPath, model) {
  return [
    `Read the JSON file ${batchPath} (a list of candidate websites) and the canary file ${args.canaries}`,
    `and the topic vocabulary ${args.vocabulary}. Classify EVERY row, including the two canary rows`,
    `that are mixed into the batch, then WRITE a JSON file at ${batchPath.replace(/\.json$/, '.result.json')}`,
    `containing {"rows": [...]} with one object per input row, and return only the summary.`,
    ``,
    `Each output row: {"domain": <echo the input domain exactly>, "journalism": true|false,`,
    `"kind": one of ${JSON.stringify(KINDS)}, "language": ISO 639-1 code of the HEADLINES' language`,
    `or "unknown", "topics": at most 3 strings taken ONLY from the vocabulary file (or []),`,
    `"confidence": "high"|"medium"|"low", "note": one short sentence when confidence is not high}.`,
    ``,
    `journalism = true only for an outlet that publishes REPORTING: a newspaper, news site,`,
    `magazine, broadcaster, wire agency, investigative or fact-checking outlet. A ministry, a`,
    `company, a university, a school, a church, a club, an academic journal, a directory, an`,
    `aggregator that republishes others, or a personal blog is journalism = false. Judge from the`,
    `row's own evidence (name, homepage title, description, recent headlines, the country and type`,
    `it came with) and from what you reliably know about well-known outlets. When the evidence is`,
    `thin, answer with confidence "low" -- never guess a topic or a language. Do not browse or fetch`,
    `anything: the evidence in the file is the evidence. Every input domain must appear exactly`,
    `once in the output; do not add rows.`,
    ``,
    `The summary you return: batch (the input path), answered (rows written), canary_ok (true if`,
    `you believe both canaries were classified per their expected values in the canary file),`,
    `written (the result path).`,
  ].join('\n')
}

phase('Triage')
const first = await pipeline(
  BATCHES,
  (b, _item, i) => agent(prompt(b, MODEL), {
    model: MODEL, effort: EFFORT, schema: SUMMARY, phase: 'Triage',
    label: `triage ${i + 1}/${BATCHES.length}`,
  }),
)

// Which batches to escalate: a null (agent died), a short answer, or a canary the agent itself
// reports as wrong. The result files are validated for real by triage_batches.py merge, which
// re-checks the canaries from the expected values and the vocabulary in plain code -- this
// stage's self-report only decides what is worth a second, dearer look.
const suspect = []
first.forEach((s, i) => {
  if (!s || !s.canary_ok || !s.answered) suspect.push(i)
})
log(`triage: ${BATCHES.length} batches, ${suspect.length} to escalate`)

phase('Escalate')
const second = await pipeline(
  suspect,
  (i) => agent(prompt(BATCHES[i], ESCALATE), {
    model: ESCALATE, effort: 'medium', schema: SUMMARY, phase: 'Escalate',
    label: `escalate ${i + 1}`,
  }),
)

const untrusted = []
second.forEach((s, k) => {
  const i = suspect[k]
  if (!s || !s.canary_ok || !s.answered) untrusted.push(BATCHES[i])
})
log(`escalate: ${suspect.length} re-run, ${untrusted.length} still untrusted (human review)`)

return {
  batches: BATCHES.length,
  escalated: suspect.length,
  untrusted,
  answered: first.filter(Boolean).reduce((n, s) => n + (s.answered || 0), 0),
  next: 'run triage_batches.py merge -- it re-validates every result file in plain code',
}
