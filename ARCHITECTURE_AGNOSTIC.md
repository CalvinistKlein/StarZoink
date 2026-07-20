# Dungeon of the Stars — Engine Architecture (Agnostic Reference)

> **Purpose:** This document describes the *system architecture* of the Dungeon of the Stars
> text-RPG engine from a setting-agnostic perspective. It is written so the project can be
> **refactored or forked** into any other fiction setting (e.g. a **D&D-themed** story engine)
> without rewiring the core loop. Star Wars is one *skin*; the machinery underneath is generic.

---

## 1. What the engine actually is

A **single-page web app** backed by a **Python/Flask** server that drives a multi-model
LLM pipeline against a local **Ollama** instance. The player types commands; the engine
translates them into game actions, mutates world state, retrieves lore, and streams a
narrated response back as a chat-style feed.

The defining idea: **the LLM is not one model doing everything.** The workload is split
into specialized roles, each run on the model best suited (and small enough to fit VRAM):

| Role | Responsibility | Why separate |
|------|----------------|--------------|
| **Parser** | Turn free-text command → structured action JSON (`action_type`, `engine_mutations`, `skill_check`, `movement`, etc.) | Small models reliably emit JSON; a single model is bad at both storytelling and schema-compliance |
| **Director** | Decide which NPCs are physically "in scene" this turn | Keeps the narrator's context small + consistent; enables per-NPC memory |
| **Narrator** | Write the prose the player reads, including `<NAME>` chat-bubble dialogue | This is the "storyteller" — where tone/voice lives |
| **Memory (deferred)** | Consolidate each NPC's running memory from the latest turn | Long-horizon consistency without bloating the prompt |

Plus two support systems:
- **RAG / Guidebook** — a vector store of setting lore the narrator can retrieve for grounding.
- **World State** — a JSON/dict of mutable game facts (credits, wounds, location, ship sector, NPC statuses).

---

## 2. Core request loop (per player command)

```
player command
   │
   ▼
[Parser]  ──► action JSON + engine_mutations
   │
   ▼
[Engine]  applies mutations to World State (credits, wounds, location, items, NPC status)
   │        rolls dice (external dice system) → success/threat/triumph/despair
   ▼
[Director] selects in-scene NPC ids from registry
   │
   ▼
[RAG]     retrieves relevant guidebook passages (setting lore)
   │
   ▼
[Narrator]  writes prose + <NAME> dialogue, conditioned on:
   │           - command, action outcome, dice result
   │           - world state, in-scene NPC brains, retrieved lore
   ▼
[SSE stream]  tokens pushed to browser → rendered as chat feed + colored dialogue bubbles
   │
   ▼
[Memory]  (deferred thread) consolidates each in-scene NPC's memory
[Archivist] appends a one-line summary to the campaign chronicle
```

The browser receives a Server-Sent-Events stream: incremental `token` events for the
typing effect, then a final `done` event carrying the fully colorized `html` + `in_scene`
list. This is what makes the "easy to follow output stream" — the player sees text appear
live, then a finalized, styled block.

---

## 3. Files (roles, not setting)

| File | Role (agnostic) |
|------|-----------------|
| `dungeonofthestars.py` | Flask app, routes, SSE, settings/prompts/models APIs, server entry |
| `game_engine.py` | Orchestrates the loop above; owns World State + dice; applies mutations |
| `llm_agent.py` | Thin Ollama client; one method per role (parse / narrate / summarize); loads `prompts.json` |
| `npc_brains.py` | NPC registry, per-NPC memory store, director selection, memory consolidation |
| `rag_engine.py` | Vector store (ChromaDB) over the guidebook; retrieval for the narrator |
| `dice.py` | Setting-agnostic dice system (success/threat/triumph/despair → outcomes) |
| `prompts.json` | **The skin.** All four role prompts live here, editable live from the UI |
| `config.json` | Endpoint URL + which model fills each role + feature flags |
| `Game_info/` | The guidebook source: `campaign_plot.md`, `locations.md`, `items.md`, `skills.md` |
| `StarWars_*/` | Built RAG index (generated from the guidebook; not hand-edited) |
| `GameData/` | Runtime state: world state, NPC brains, campaign chronicle, history (excluded from git) |

**Key insight for forking:** almost everything setting-specific lives in `prompts.json`,
`Game_info/`, and the RAG index. Swap those three and you have a different game.

---

## 4. The "guidebook" pattern (most important for a D&D fork)

The narrator is **not** expected to know the setting from memory. Instead:

1. A **guidebook** (Markdown files in `Game_info/`) describes the world: factions, locations,
   items, skills, the campaign arc.
2. `rag_engine.py` ingests it into a vector store.
3. Each turn, the Director/Narrator retrieve the few most relevant passages and inject them
   as context.

This is the lever that makes a small model *sound* like it knows the lore: it's retrieved,
not memorized. For a D&D fork you would replace `Game_info/` with:
- `campaign_plot.md` → your adventure hook / chapter structure
- `locations.md` → taverns, dungeons, cities, the wilderness
- `items.md` → magic items, gear, loot tables
- `skills.md` → class features, spell list, rules summary

…then rebuild the RAG index. The narrator suddenly "knows" D&D because the guidebook is in
its context window every turn.

**Recommendation for the D&D build:** feed a *curated* guidebook (not the whole SRD) — keep
it tight so retrieval stays relevant and the prompt stays small. 200–400 curated passages
beats 5,000 noisy ones for a 7–13B narrator.

---

## 5. Why Star Wars needs more mechanical work before gameplay is "ready"

From building and tuning this: the *story* layer is strong, but the *game* layer is thin.
The mechanical gaps that block "ready" gameplay:

1. **Parser reliability on edge commands.** Small parsers handle happy-path orders but
   wobble on novel actions (dynamic travel, arrests, executions, multi-step plans). A
   fine-tuned parser LoRA is the fix, not more prompt text.
2. **State mutations are shallow.** `engine_mutations` covers credits/wounds/strain/items/
   location, but richer simulation (inventory logic, quest flags, faction standing,
   time-of-day) is stubbed. D&D especially needs: spell slots, HP/AC, initiative, conditions.
3. **Dice → narrative bridge is loose.** The dice system produces outcomes, but the
   narrator sometimes ignores them or manufactures its own scene. Needs a hard contract:
   dice result is canon, narrator must reflect it.
4. **No real failure/death loop.** Combat can't actually kill the player or end the run in a
   structured way; consequences are narrated but not enforced.
5. **NPC brains are per-turn, not persistent relationships.** Memory consolidation exists but
   relationship *state* (ally/rival/debt) isn't a first-class world fact yet.

These are **mechanical**, not storytelling, problems. The storyteller is the easy part; the
simulation is the work.

---

## 6. Refactoring path → D&D story engine

To fork this into a D&D-themed engine with a guidebook-fed storyteller:

**Phase 0 — Skin swap (hours)**
- Replace `Game_info/*` with D&D guidebook (adventure, locations, items, classes/spells).
- Rewrite `prompts.json` (parser schema stays; narrator/director/memory text becomes D&D).
- Rebuild RAG index from the new guidebook.
- Result: a Star-Wars-shaped engine telling D&D stories. Functional, but mechanics still SW.

**Phase 1 — Mechanical reskin (days)**
- Extend `engine_mutations` + World State for D&D facts: `hp`, `ac`, `spell_slots`,
  `conditions`, `quest_flags`, `reputation`.
- Replace `dice.py` semantics with D&D resolution (d20 + mods, save/check, crit), keeping the
  same success/threat/triumph/despair → outcome contract the narrator already consumes.
- Tighten the parser↔engine contract so novel D&D actions (cast spell, short rest, stealth
  check) map to mutations reliably.

**Phase 2 — Guidebook-as-rules (the differentiator)**
- Promote the guidebook from *lore retrieval* to *rules retrieval*: the narrator pulls the
  exact spell/class/monster entry it needs mid-turn, so rules are enforced by context, not
  by a hard-coded rules engine.
- Add a "rules check" step: after the parser emits an action, a lightweight validator
  (or the guidebook-retrieval) confirms it's legal before the narrator writes it.

**Phase 3 — Fine-tune (optional, high ceiling)**
- Train a narrator LoRA on curated D&D prose + `<NAME>` bubble format (same pipeline as the
  Star Wars narrator LoRA).
- Train a parser LoRA on (command → D&D action JSON) pairs so novel actions parse cleanly.

---

## 7. Operational notes

- **Multi-model on one Ollama box:** roles split across models to fit VRAM. A 16GB GPU runs
  parser (small) + narrator (~8–13B) + deferred memory comfortably.
- **Editable prompts:** `prompts.json` is hot-reloaded from the UI ("Edit Prompts" modal) —
  no restart to tune voice or contract.
- **Live model switching:** the UI dropdowns populate from the Ollama `/api/tags`; swap the
  narrator mid-session to A/B voice/tone.
- **Streaming UX:** SSE token stream + finalized colorized `done` block = readable, live,
  chat-style output. Dialogue rendered as faction/color-coded bubbles via the `<NAME>` header.
- **State isolation:** only in-scene NPC brains are injected into the narrator prompt each
  turn, keeping context small and consistent.

---

## 8. TL;DR for the fork

> The engine is a **setting-agnostic LLM pipeline**: parse → mutate → retrieve → narrate →
> stream, with a **guidebook** (RAG) grounding the storyteller. Star Wars is just the current
> skin in `prompts.json` + `Game_info/`. To make a D&D version: swap the guidebook + prompts,
> extend the world-state/mutations for D&D facts, keep the dice→outcome contract, and treat
> the guidebook as the rules source. The storytelling is ready; the *mechanics* are the
> remaining build.
