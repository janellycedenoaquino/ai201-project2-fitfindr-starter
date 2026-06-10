# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

**What it does:**
Searches the 40 mock listings for items matching the user's request. It runs in two stages: first it applies hard filters (price ceiling and size) to drop listings that don't qualify, then it scores the survivors by keyword overlap with the description and returns them ranked best-match first. Pure Python — no LLM call.

**Input parameters:**
- `description` (str): keywords describing the item the user wants (e.g. `"vintage graphic tee"`). Already stripped of price/size by the agent before it reaches this tool.
- `size` (str | None): a size to filter by (e.g. `"M"`, `"small"`, `"US 7"`), or `None` to skip size filtering.
- `max_price` (float | None): an inclusive price ceiling, or `None` to skip price filtering.

**How matching works:**
- **Price filter (hard):** keep a listing only if `price <= max_price`. Skipped if `max_price is None`.
- **Size filter (hard):** keep a listing only if its size matches the request. Matching is normalize → token → wildcard:
  1. *Normalize* the requested size: lowercase, strip, map words to letters (`small`→`s`, `medium`→`m`, `large`→`l`, `extra large`/`x-large`→`xl`).
  2. *Token-match*: split the listing's size on non-alphanumeric characters (so `"S/M"` → `["s","m"]`, `"XL (oversized)"` → `["xl","oversized"]`) and keep the listing if the normalized request equals one of those tokens. (Token-match, not substring, so a request for `S` never matches `XL`/`oversized`/length codes like `L30`.)
  3. *One-size wildcard*: if the listing size contains `one size`, `oversized`, or `adjustable`, it matches any requested size.
  Skipped if `size is None`.
- **Keyword scoring (rank):** on the listings that pass both filters, glue `title` + `style_tags` + `description` into one lowercased text blob. Split the description into words, drop words ≤2 letters, and score each listing by how many of those words appear as a **substring** of its blob (substring so `vintage` matches `vintage-style`). Drop any listing scoring 0.

**What it returns:**
A list of the full matching listing dicts — each with all 11 fields (`id, title, description, category, style_tags, size, condition, price, colors, brand, platform`) — sorted by keyword score, highest first. Ties keep dataset order (stable sort). Returns **all** scoring matches, not a top-N slice; the agent selects `results[0]`.

**What happens if it fails or returns nothing:**
Returns an empty list `[]` — it never raises. The agent checks for the empty list and stops early with a helpful message telling the user what to loosen (size, price, or keywords), rather than calling `suggest_outfit` with no item.

---

### Tool 2: suggest_outfit

**What it does:**
<!-- Describe what this tool does in 1–2 sentences -->

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `new_item` (dict): ...
- `wardrobe` (dict): ...

**What it returns:**
<!-- Describe the return value -->

**What happens if it fails or returns nothing:**
<!-- What should the agent do if the wardrobe is empty or no outfit can be suggested? -->

---

### Tool 3: create_fit_card

**What it does:**
<!-- Describe what this tool does in 1–2 sentences -->

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `outfit` (...): ...

**What it returns:**
<!-- Describe the return value -->

**What happens if it fails or returns nothing:**
<!-- What should the agent do if the outfit data is incomplete? -->

---

### Additional Tools (if any)

<!-- Copy the block above for any tools beyond the required three -->

---

## Planning Loop

**How does your agent decide which tool to call next?**
<!-- Describe the logic your planning loop uses. What does it look at? What conditions change its behavior? How does it know when it's done? -->

---

## State Management

**How does information from one tool get passed to the next?**
<!-- Describe how your agent stores and accesses state within a session. What data is tracked? How is it passed between tool calls? -->

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query | |
| suggest_outfit | Wardrobe is empty | |
| create_fit_card | Outfit input is missing or incomplete | |

---

## Architecture

<!-- Draw a diagram of your agent showing how the components connect:
     User input → Planning Loop → Tools (search_listings, suggest_outfit, create_fit_card)
                                                                          ↕
                                                                   State / Session
     Show what triggers each tool, how state flows between them, and where error paths branch off.
     ASCII art, a Mermaid diagram (https://mermaid.js.org/syntax/flowchart.html), or an embedded
     sketch are all fine. You'll share this diagram with an AI tool when asking it to implement
     the planning loop and each individual tool. -->

---

## AI Tool Plan

<!-- For each part of the implementation below, describe:
     - Which AI tool you plan to use (Claude, Copilot, ChatGPT, etc.)
     - What you'll give it as input (which sections of this planning.md, your agent diagram)
     - What you expect it to produce
     - How you'll verify the output matches your spec before moving on

     "I'll use AI to help me code" is not a plan.
     "I'll give Claude my Tool 1 spec (inputs, return value, failure mode) and ask it to implement
     search_listings() using load_listings() from the data loader — then test it against 3 queries
     before trusting it" is a plan. -->

**Milestone 3 — Individual tool implementations:**

**Milestone 4 — Planning loop and state management:**

---

## A Complete Interaction (Step by Step)

**What FitFindr does (overview):**
FitFindr takes a thrifting request and runs a planning loop over three tools to turn it into a styled, shareable find. The user's query triggers `search_listings`, which filters the 40 mock listings by keywords, size, and price; a non-empty result triggers `suggest_outfit`, which combines the top match with the user's wardrobe to propose outfits; that suggestion triggers `create_fit_card`, which writes a casual caption naming the item, price, and platform. If `search_listings` returns nothing, the agent stops and tells the user what to loosen (size, price, or keywords) instead of calling the next tool with empty input; if the wardrobe is empty, `suggest_outfit` falls back to general styling advice rather than failing.

Write out what a full user interaction looks like from start to finish — tool call by tool call. Use a specific example query.

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1:**
<!-- What does the agent do first? Which tool is called? With what input? -->

**Step 2:**
<!-- What happens next? What was returned from step 1? What tool is called now? -->

**Step 3:**
<!-- Continue until the full interaction is complete -->

**Final output to user:**
<!-- What does the user actually see at the end? -->
