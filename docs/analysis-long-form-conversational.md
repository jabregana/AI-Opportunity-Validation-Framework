# Long-form conversational memory: where the proxy fits, where it doesn't, and what to actually build

## What "long-form conversational memory" means as a product category

Long-form conversational memory is the infrastructure that turns ongoing back-and-forth chat (with an AI assistant, a support agent, or another user) into a queryable history of facts about the participants, their preferences, the entities they discussed, and the state of their world. The category contains a few different shapes:

1. **Personal assistant memory.** A user talks to an AI assistant over weeks or months. The assistant needs to remember user preferences, recurring topics, ongoing projects, mentioned people and companies.
2. **Customer support memory.** Multi-session ticket threads where the customer's account state, prior issues, and history with the product are referenced across calls.
3. **Sales CRM augmentation.** Notes from sales conversations get auto-extracted; the system remembers which prospects are at which stage, which entities (companies, decision-makers) were mentioned, what was promised.
4. **Healthcare patient interactions.** Visit notes, symptoms, medications, prior conditions linked across appointments.
5. **Internal company chat memory.** Slack/Teams conversations where projects, teams, customers, products get referenced under varying short-hand names.

All five share a structural property: **the same conceptual entities recur across sessions under varying surface forms**, and the value of the memory depends on linking those references coherently.

## What we know from the v0.5.x findings about how the proxy performs here

The project has produced 18 findings on the proxy's behavior. Three are directly load-bearing for the long-form conversational use case:

### Findings that point AWAY from long-form conversational

- **LongMemEval-S regression (`docs/finding-longmemeval-regression.md`)** — every proxy variant regressed against b-raw baseline on this benchmark. The metric was question-answer clustering; the proxy is not a sentence-level clustering tool.
- **Co-reference doesn't help (`docs/finding-coref-doesnt-help.md`)** — an upstream LLM-based co-reference resolver regressed (-0.024 F1) when added before the proxy. The LLM does co-reference internally; the proxy doesn't extend cleanly into pronoun-heavy text.
- **Conversational lift is smaller magnitude (`docs/finding-conversational-llm.md`)** — on synthetic multi-turn dialogues the lift was +0.04 to +0.18 F1 across 1B-14B local models, versus +0.23 to +0.55 on single-sentence. Co-reference, context disambiguation, and conversational LLM behavior all eat into the proxy's value.

### Findings that point TOWARD long-form conversational

- **Live Mem0 with wrapper (`docs/finding-mem0-live-wrapper.md`)** — memory count unchanged but content shifted dramatically toward canonical names: "Alphabet Inc" mentions went from 0 stored memories to 3; "Microsoft Corp" 1→5; "Tesla Inc" 1→5. **This is exactly the long-form memory use case** — across many ingestions, the wrapper ensures references to the same entity accumulate under one canonical, so downstream queries by canonical name find more results.
- **Opus had the LARGEST conversational lift (+0.27 F1) (`docs/finding-conversational-llm.md`)** — counter to the single-sentence pattern. The mechanism: bigger LLMs faithfully echo more surface variants per entity in dialogue, so the proxy has more raw material to canonicalize. Larger frontier models running multi-turn conversations are exactly where the proxy's lift is biggest.
- **Real Twitter data confirms the pattern (`docs/finding-real-dataset.md`)** — -25% surface variants in LLM output on naturally-occurring (non-conversational) financial text. The mechanism generalizes off synthetic data.

## The honest reframing

The previous LongMemEval test compared the proxy to b-raw on QUESTION-ANSWER clustering. That metric is wrong. The proxy is not a Q/A retrieval engine. The proxy is a **write-path entity canonicalizer that makes the downstream memory store accumulate references under one canonical per entity across many sessions**.

The right metric is not "does the proxy beat b-raw on B-cubed F1 of question-answer pairs". It is "after N sessions ingest into Mem0/Graphiti/Cognee, can downstream queries for canonical entity names retrieve more relevant memories?"

That metric is what the live-Mem0 finding shows: 0→3, 1→5, 1→5 for the three multi-alias entities after just 30 utterances. Scale that across thousands of sessions and the gap widens.

## Three product opportunities specific to long-form conversational

### Opportunity 1 — "Memory consolidator" SaaS for personal-assistant builders

Companies building consumer or SMB AI assistants on top of Mem0/Cognee/Graphiti hit the same problem: their user mentions "my company" across 50 sessions and the memory store ends up with 50 fragmented references because the user said "Acme", "Acme Corp", "Acme Inc", "we", "us", "my employer". The wrapped proxy + a curated alias map (auto-learned from user history + manually managed for common cases) sells as middleware: "drop us in front of your Mem0 and your memory store becomes 10x more queryable for free."

**Concrete sales pitch**: "Your assistant says it remembers the user, but when you query the memory store for 'Acme Corp' you get 1 of the 50 references because they're stored under 50 different surface forms. Wrap with us and that becomes 50/50."

### Opportunity 2 — "Domain alias maps as a service" for vertical verticals

The biggest commercializable insight from the open-world alias finding: 87% of the proxy's value comes from the static `mention_map`, not the embedding fallback. The PROXY is open-source middleware. The VALUE is curated alias maps for specific verticals:

- **Financial chat / trading assistants**: 500+ tickers, 200+ funds, 100+ brokerages, central banks, indices. Maintained quarterly as M&A happens.
- **Pharma / healthcare**: brand name to generic name mappings (~10k drugs), code-to-condition (ICD-10), provider directory canonicalization.
- **B2B SaaS**: customer name normalization across product variants ("Salesforce" vs "SFDC" vs "Salesforce.com"), competitor mapping.
- **Legal**: case law citation normalization, statute references, party names.

The recurring revenue is in the data, not the code. Sell the alias maps as a subscription, the proxy as the integration layer.

### Opportunity 3 — "Memory quality auditor" tooling

Most teams deploying Mem0/Cognee/Graphiti don't know how fragmented their memory store is. There's no built-in metric for "fraction of entity references stored under non-canonical surface forms." A diagnostic tool that:

1. Reads a snapshot of the memory store
2. Runs an embedder + NER to identify entity mentions
3. Reports fragmentation per entity (how many surface forms refer to each canonical)
4. Suggests an alias map to fix it (and offers to maintain it via your wrapper)

This is a "land" move that demonstrates the value before selling the wrapper subscription. Same shape as how observability tools (Datadog, Sentry) land — diagnose first, then sell the fix.

## What the multi-session test should measure

The right test for the long-form conversational use case is NOT "does the proxy beat baseline on within-session entity extraction" (we already showed it does, modestly). The right test is **cross-session canonical retention**: after K simulated sessions, does the proxy's wrapped Mem0 store give you better retrieval when you query by canonical name?

A concrete test setup:

1. Generate K sessions of conversation about the same N entities.
2. Each session uses different aliases (Session 1 says "AAPL", Session 5 says "Apple Inc", Session 12 says "Apple Computer").
3. Ingest each session into Mem0 with and without the wrapper.
4. After all K sessions, query Mem0 for each canonical entity name.
5. Measure: with wrapper, do queries for canonical names find more relevant memories?

This is what `experiments/mem0_multi_session_bench.py` (next) measures.

## Honest limits of the long-form opportunity

The proxy is not a:
- Co-reference resolver (the LLM does that — confirmed by the coref-doesnt-help finding).
- Sentence-level retrieval system (LongMemEval-style Q/A is the wrong shape).
- Conversation summarizer (Mem0 already extracts facts).
- Long-context attention mechanism (this is the LLM's job).

The proxy is a **deterministic canonicalizer of entity surface forms on the write path**. In long-form conversational memory specifically, that translates to: ensuring the dozens or thousands of mentions of the same conceptual entity across sessions stay linked, so downstream queries by canonical name actually return all the relevant history.

That is a real and quantifiable wedge, but it lives at the data-layer level, not at the conversation-quality level. The commercialization opportunities flow from that data-layer placement: middleware for memory frameworks, vertical alias maps, memory-store auditing.
