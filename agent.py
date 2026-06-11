"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import re

from tools import search_listings, suggest_outfit, create_fit_card


# ── query parsing (rule-based, no LLM) ──────────────────────────────────────────

# Conversational filler dropped from the description so Tool 1's substring
# keyword search doesn't misfire (e.g. "for" substring-matching "platform").
_STOP_WORDS = {
    "i", "im", "i'm", "a", "an", "the", "for", "looking", "look", "want",
    "wanted", "need", "find", "finding", "me", "some", "something", "to",
    "in", "of", "my", "please", "show", "get", "searching", "search", "buy",
    "would", "like", "thats", "out", "there", "is", "are", "and",
}

# Known size tokens used to spot a bare size in the query when there is no
# explicit "size X" phrase. Letter codes + spelled-out forms.
_SIZE_TOKENS = {
    "xxs", "xs", "s", "m", "l", "xl", "xxl",
    "small", "medium", "large",
}

# Price patterns, tried in order; group 1 captures the numeric ceiling.
_PRICE_PATTERNS = [
    r"under\s*\$?\s*(\d+(?:\.\d+)?)",
    r"below\s*\$?\s*(\d+(?:\.\d+)?)",
    r"less\s+than\s*\$?\s*(\d+(?:\.\d+)?)",
    r"max(?:imum)?\s*\$?\s*(\d+(?:\.\d+)?)",
    r"\$\s*(\d+(?:\.\d+)?)",
    r"(\d+(?:\.\d+)?)\s*dollars?",
]


def _parse_query(query: str) -> dict:
    """
    Extract description / size / max_price from a raw query using regex only.

    Returns a dict ready to splat into search_listings(): keys description (str),
    size (str | None), max_price (float | None). No LLM call — deterministic,
    unit-testable, and zero added latency.
    """
    text = query.lower()
    max_price = None
    size = None

    # --- price: first matching pattern wins, then strip its phrase from text ---
    for pat in _PRICE_PATTERNS:
        m = re.search(pat, text)
        if m:
            max_price = float(m.group(1))
            text = text[: m.start()] + " " + text[m.end():]
            break

    # --- size: explicit "size X" / "sz X" phrase, then strip it ---
    m = re.search(r"\b(?:size|sz)\s+([a-z0-9]+)\b", text)
    if m:
        size = m.group(1).upper()
        text = text[: m.start()] + " " + text[m.end():]

    # --- description: drop stop words, leftover bare size token, stray numbers ---
    kept: list[str] = []
    for tok in re.findall(r"[a-z0-9']+", text):
        if tok in _STOP_WORDS:
            continue
        if size is None and tok in _SIZE_TOKENS:
            size = tok.upper()  # bare size token, no "size" keyword present
            continue
        if tok.isdigit():
            continue  # leftover number that isn't a keyword
        kept.append(tok)

    return {"description": " ".join(kept), "size": size, "max_price": max_price}


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
    }


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.

    TODO — implement this function using the planning loop you designed in planning.md:

        Step 1: Initialize the session with _new_session().

        Step 2: Parse the user's query to extract a description, size, and
                max_price. You can use regex, string splitting, or ask the LLM
                to parse it — document your choice in planning.md.
                Store the result in session["parsed"].

        Step 3: Call search_listings() with the parsed parameters.
                Store results in session["search_results"].
                If no results: set session["error"] to a helpful message and
                return the session early. Do NOT proceed to suggest_outfit
                with empty input.

        Step 4: Select the item to use (e.g., the top result).
                Store it in session["selected_item"].

        Step 5: Call suggest_outfit() with the selected item and wardrobe.
                Store the result in session["outfit_suggestion"].

        Step 6: Call create_fit_card() with the outfit suggestion and selected item.
                Store the result in session["fit_card"].

        Step 7: Return the session.

    Before writing code, complete the Planning Loop and State Management sections
    of planning.md — your implementation should match what you described there.
    """
    # Step 1: fresh session — the single source of truth for this interaction.
    session = _new_session(query, wardrobe)

    # Step 2: parse the raw query into description / size / max_price (regex).
    session["parsed"] = _parse_query(query)

    # Step 3: search. The one real branch point — empty results end the run
    # early so suggest_outfit is never called with no item.
    results = search_listings(**session["parsed"])
    session["search_results"] = results
    if not results:
        parsed = session["parsed"]
        constraints = []
        if parsed["size"]:
            constraints.append(f"size {parsed['size']}")
        if parsed["max_price"] is not None:
            constraints.append(f"under ${parsed['max_price']:g}")
        where = (" in " + " ".join(constraints)) if constraints else ""
        target = parsed["description"] or query
        session["error"] = (
            f"No matches for '{target}'{where}. "
            "Try removing the size or price filter, or using broader keywords."
        )
        return session

    # Step 4: select the top-ranked match (search_listings returns sorted).
    session["selected_item"] = results[0]

    # Step 5: suggest an outfit (handles empty wardrobe internally).
    session["outfit_suggestion"] = suggest_outfit(results[0], wardrobe)

    # Step 6: light guard — skip the fit card if the outfit came back empty.
    outfit = session["outfit_suggestion"]
    if not outfit or not outfit.strip():
        session["error"] = (
            "Found a match but couldn't generate an outfit suggestion — "
            "try again in a moment."
        )
        return session
    session["fit_card"] = create_fit_card(outfit, results[0])

    # Step 7: done.
    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
