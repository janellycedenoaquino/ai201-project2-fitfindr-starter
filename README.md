# FitFindr 🛍️

A multi-tool AI agent that finds secondhand clothing listings and figures out how to wear them. You describe what you're after in plain language — *"vintage graphic tee under $30, size M"* — and FitFindr searches a mock dataset of 40 listings, picks the best match, styles it against your existing wardrobe, and writes a shareable caption for the find.

It's built around a **planning loop** that decides which tool to call based on what each previous tool returned (not a fixed pipeline), with a **session dict** carrying state between tools and per-tool **error handling** so one failure never crashes the agent.

---

## Setup & running

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file in the repo root with a free Groq key from [console.groq.com](https://console.groq.com):

```
GROQ_API_KEY=your_key_here
```

| Command | What it does |
|---|---|
| `python app.py` | Launch the Gradio UI (opens a localhost URL printed in the terminal) |
| `python agent.py` | CLI smoke test — happy path + no-results path |
| `pytest tests/` | Run the tool test suite (offline; LLM calls are mocked) |
| `python utils/data_loader.py` | Verify the data loads |

---

## Architecture

```
app.py (Gradio UI) ──> agent.run_agent(query, wardrobe) ──> tools.py (3 tools)
                              │
                       session dict (state)
```

One interaction flows: **parse the query → `search_listings` → (branch: empty? stop) → `suggest_outfit` → `create_fit_card`**. Every step reads its inputs from a single `session` dict and writes its outputs back into it. A full flowchart (with the error branches) is in [`planning.md`](planning.md#architecture).

---

## Tool inventory

All three tools live in [`tools.py`](tools.py) as pure functions — each independently testable, each owning one failure mode (failures return a sentinel/message, never raise).

### 1. `search_listings(description, size, max_price) -> list[dict]`

| | |
|---|---|
| **Inputs** | `description (str)` — keywords for the item; `size (str \| None)` — size filter or `None` to skip; `max_price (float \| None)` — inclusive price ceiling or `None` to skip |
| **Output** | `list[dict]` — full matching listing dicts (all 11 fields), sorted by relevance (best first); `[]` if nothing matches |
| **Purpose** | Search the mock dataset. Runs two stages: **hard filters** (price + size) drop disqualified listings, then **keyword scoring** ranks the survivors. Pure Python — no LLM. |

How matching works: price keeps `price <= max_price`. Size uses **normalize → token-match → one-size wildcard** (`"small"`→`s`; split listing size on non-alphanumerics so a request for `S` matches `S/M` but *not* `XL (oversized)` or `W30 L30`). Keyword scoring globs `title + style_tags + description`, drops query words ≤2 letters, and counts substring matches (so `vintage` matches `vintage-style`). Ties keep dataset order (stable sort).

### 2. `suggest_outfit(new_item, wardrobe) -> str`

| | |
|---|---|
| **Inputs** | `new_item (dict)` — the listing to style (only `title`, `category`, `colors`, `style_tags`, `description` are sent to the model); `wardrobe (dict)` — `{"items": [...]}`, may be empty |
| **Output** | `str` — 1–2 outfit ideas (non-empty on every path) |
| **Purpose** | Style the found item against the user's closet. **Calls Groq** (`llama-3.3-70b-versatile`). With a wardrobe, it builds complete looks referencing the user's pieces **by name**; with an empty wardrobe, it returns general styling advice. |

The wardrobe is formatted **grouped by category** (TOPS / BOTTOMS / SHOES / …) so the model sees the outfit "slots" and completes the look around the new item. Temperature ≈ 0.7 — creative but grounded, so it doesn't invent items the user doesn't own.

### 3. `create_fit_card(outfit, new_item) -> str`

| | |
|---|---|
| **Inputs** | `outfit (str)` — the suggestion from `suggest_outfit`; `new_item (dict)` — the listing (only `title`, `price`, `platform`, `style_tags` are sent) |
| **Output** | `str` — a 2–4 sentence shareable caption (or an error string if `outfit` is empty) |
| **Purpose** | Write a casual, OOTD-style caption naming the item, price, and platform once each. **Calls Groq** at a **high temperature (≈ 0.95)** so it reads differently every time. |

---

## How the planning loop works

[`run_agent()`](agent.py) runs the tools in order but **branches on what each returns** — it is not a fixed pipeline:

1. **Initialize** a fresh `session` (the single source of truth).
2. **Parse** the query with regex into `description / size / max_price` → `session["parsed"]`.
3. **Search** with those params → `session["search_results"]`.
   - **Branch (early exit):** if results are empty, set `session["error"]` to a message naming what to loosen and **return immediately** — `suggest_outfit` is *never* called on an empty result. This is the conditional that makes it a planning loop.
4. **Select** `session["selected_item"] = results[0]` (top-ranked).
5. **Suggest outfit** → `session["outfit_suggestion"]`.
   - **Light guard:** if the suggestion comes back empty, set `error` and skip the fit card.
6. **Create fit card** → `session["fit_card"]`.
7. **Return** the session.

The behavior differs by input: an impossible query stops after step 3 with an error; a good query runs all three tools. Callers (`app.py`) check `session["error"]` first.

## State management

A single `session` dict (`_new_session`) is the **one source of truth** for an interaction. Each step **reads its inputs from the session and writes its outputs back** — no loose variables, no re-prompting:

```
query → (parse) → parsed → (search) → search_results → (select) → selected_item
      → (suggest) → outfit_suggestion → (caption) → fit_card
```

Fields: `query`, `parsed`, `search_results`, `selected_item`, `wardrobe`, `outfit_suggestion`, `fit_card`, `error`. State passes **by reference** — `selected_item is search_results[0]` is `True`, so the exact dict found by `search_listings` is what flows into `suggest_outfit` and `create_fit_card` without re-entry. `error` gates the flow: when it's set, the output fields stay `None`.

## Error handling

Each tool owns its failure mode and returns a useful value instead of raising. Concrete examples from testing:

| Tool | Failure mode | Behavior (real output) |
|---|---|---|
| `search_listings` | No match | `search_listings('designer ballgown', 'XXS', 5)` → `[]`. The agent then sets: *"No matches for 'designer ballgown' in size XXS under $5. Try removing the size or price filter, or using broader keywords."* |
| `suggest_outfit` | Empty wardrobe | Returns general styling advice (e.g. *"…pairs well with high-waisted pants or skirts, distressed denim… Try it with high-waisted denim and white sneakers…"*) instead of crashing. |
| `create_fit_card` | Empty `outfit` | Guards before any LLM call: `create_fit_card('', item)` → *"Can't make a fit card without an outfit — run suggest_outfit first."* |
| `suggest_outfit` / `create_fit_card` | LLM/API error | Wrapped in `try/except` → returns a plain apologetic string, never raises. |

Screenshots of these triggered failures are in [`docs/screenshots/`](docs/screenshots/).

## Spec reflection

- **One way the spec helped:** the "planning.md before any code" requirement forced design decisions *before* implementation. Specifying the size filter on paper surfaced that a naive substring match would return `XL (oversized)` items for an `S` request — so I designed the token-match approach up front instead of discovering the bug after coding.
- **One way the implementation diverged:** the regex query parser can't separate the *shopping target* from *conversational wardrobe context*. For a query like *"a vintage graphic tee… I mostly wear baggy jeans and chunky sneakers,"* the parser keys on the item keywords only; the wardrobe comes from the UI's wardrobe selector, not the query text. I accepted this because the real app input is a focused query + an explicit wardrobe choice, and an LLM parse (the alternative) would add latency and non-determinism to every request.

## AI usage

I built this with **Claude Code**, designing each section of `planning.md` first and then generating implementation against that spec. Two specific instances:

1. **Size matching (revised the AI's first answer).** I gave Claude the Tool 1 spec and it initially proposed case-insensitive **substring** matching for size. I rejected it: substring would hand someone an `XL (oversized)` item when they asked for `S`. I directed it to a **token-match + normalization + one-size wildcard** approach instead, and locked it in with a regression test (`test_search_size_token_match_not_substring`).
2. **Planning loop (reviewed before trusting).** I gave Claude the Planning Loop + State Management sections and the Mermaid diagram and asked it to implement `run_agent()`. I verified it **branched on the empty-search result and returned early** (rather than calling all three tools unconditionally) and that state passed **by reference** (`selected_item is search_results[0]`) before accepting it.

I also overrode the query-parsing approach: Claude offered an LLM-based parse as an option; I chose **regex** to avoid an extra API call per query (lower latency, deterministic, unit-testable), since Groq is already required by Tools 2 and 3.

## Future work (not implemented)

Candidate stretch features, deliberately deferred to keep the core agent focused:
- **Price-comparison tool** — judge whether a listing's price is fair vs. comparable items.
- **Retry with fallback** — on no results, auto-loosen the size/price filter and tell the user what changed.
- **Synonym/abbreviation expansion** in search (`t`→`tee`, `jorts`→`shorts`).
- **Style-profile memory** across sessions.

## Project structure

```
├── app.py              # Gradio UI + handle_query()
├── agent.py            # run_agent() planning loop + regex query parser
├── tools.py            # the 3 tools + Groq client + shared helpers
├── tests/test_tools.py # one test per failure mode (LLM mocked)
├── conftest.py         # puts repo root on sys.path for pytest
├── planning.md         # full design spec + architecture diagram
├── data/               # listings.json (40) + wardrobe_schema.json
├── utils/data_loader.py
└── docs/screenshots/   # triggered-failure evidence
```