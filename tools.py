"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()

# Single LLM model for both Groq-backed tools (Tools 2 & 3).
MODEL = "llama-3.3-70b-versatile"


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# ── shared helpers ────────────────────────────────────────────────────────────

# Map common word/spelled-out sizes onto the letter codes used in the dataset.
_SIZE_WORD_MAP = {
    "extra small": "xs", "x-small": "xs", "xsmall": "xs",
    "small": "s",
    "medium": "m",
    "large": "l",
    "extra large": "xl", "x-large": "xl", "xlarge": "xl",
}
# Listing sizes containing any of these are treated as fitting any request.
_WILDCARD_MARKERS = ("one size", "oversized", "adjustable")
# Order outfit "slots" are presented to the model in suggest_outfit.
_CATEGORY_ORDER = ["tops", "bottoms", "outerwear", "shoes", "accessories"]


def _normalize_size(size: str) -> str:
    """Lowercase, strip, and map spelled-out sizes (small → s) to letter codes."""
    s = size.strip().lower()
    return _SIZE_WORD_MAP.get(s, s)


def _size_matches(requested: str, listing_size: str) -> bool:
    """True if a normalized request matches a listing size by token or wildcard."""
    listing_lower = listing_size.lower()
    if any(marker in listing_lower for marker in _WILDCARD_MARKERS):
        return True
    tokens = [t for t in re.split(r"[^a-z0-9]+", listing_lower) if t]
    return requested in tokens


def _fmt_price(price) -> str:
    """Render a price without a trailing .0 (18.0 → '18', 18.5 → '18.5')."""
    try:
        return f"{float(price):g}"
    except (TypeError, ValueError):
        return str(price)


def _format_item_for_styling(item: dict) -> str:
    """Styling-relevant fields of a listing for suggest_outfit's prompt."""
    return (
        f"- Title: {item.get('title', '')}\n"
        f"- Category: {item.get('category', '')}\n"
        f"- Colors: {', '.join(item.get('colors', []))}\n"
        f"- Style tags: {', '.join(item.get('style_tags', []))}\n"
        f"- Description: {item.get('description', '')}"
    )


def _format_wardrobe(items: list[dict]) -> str:
    """Wardrobe items grouped by category (the outfit 'slots'), id omitted."""
    by_cat: dict[str, list[dict]] = {}
    for it in items:
        by_cat.setdefault(it.get("category", "other"), []).append(it)

    ordered = [c for c in _CATEGORY_ORDER if c in by_cat]
    ordered += [c for c in by_cat if c not in _CATEGORY_ORDER]

    lines: list[str] = []
    for cat in ordered:
        lines.append(f"{cat.upper()}:")
        for it in by_cat[cat]:
            parts = [it.get("name", "")]
            if it.get("colors"):
                parts.append(f"colors: {', '.join(it['colors'])}")
            if it.get("style_tags"):
                parts.append(f"tags: {', '.join(it['style_tags'])}")
            if it.get("notes"):  # omitted when null/empty
                parts.append(f"notes: {it['notes']}")
            lines.append("  - " + " | ".join(parts))
    return "\n".join(lines)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    listings = load_listings()

    # Keyword tokens: lowercased, drop filler words of 2 chars or fewer.
    words = [w for w in description.lower().split() if len(w) > 2]
    requested_size = _normalize_size(size) if size else None

    # Stage 1: hard filters (price + size). Stage 2: keyword-score survivors.
    scored: list[tuple[int, dict]] = []
    for listing in listings:
        if max_price is not None and listing["price"] > max_price:
            continue
        if requested_size is not None and not _size_matches(
            requested_size, listing["size"]
        ):
            continue

        blob = " ".join(
            [
                listing.get("title", ""),
                " ".join(listing.get("style_tags", [])),
                listing.get("description", ""),
            ]
        ).lower()
        score = sum(1 for w in words if w in blob)
        if score == 0:  # no relevant keyword overlap — drop it
            continue
        scored.append((score, listing))

    # Stable sort, highest score first; ties keep dataset order.
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [listing for _, listing in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    items = wardrobe.get("items", []) if wardrobe else []
    item_block = _format_item_for_styling(new_item)

    system = (
        "You are FitFindr's stylist — a sharp, casual thrift expert who helps "
        "people style secondhand finds. Keep it short, specific, and friendly."
    )

    if items:
        wardrobe_block = _format_wardrobe(items)
        user = (
            f"Here's a secondhand item I'm thinking of buying:\n{item_block}\n\n"
            f"Here's what's already in my closet, grouped by category:\n"
            f"{wardrobe_block}\n\n"
            "Suggest 1-2 complete outfits built around the new item. Rules:\n"
            "- Reference my existing pieces BY NAME.\n"
            "- Build a full look: the new item fills its category slot, pull the "
            "rest from my closet.\n"
            "- Include one concrete styling move per outfit (cuff the sleeves, "
            "tuck the front, layer it open, etc.).\n"
            "- Keep it short and casual. Plain text only — no markdown."
        )
    else:
        # Empty wardrobe is a branch, not an error: give general advice instead.
        user = (
            f"Here's a secondhand item I'm thinking of buying:\n{item_block}\n\n"
            "I don't have any other pieces saved yet, so give me general styling "
            "guidance for this item:\n"
            "- What kinds of pieces pair well with it.\n"
            "- The vibe and occasions it suits.\n"
            "- 1-2 example looks described generically (e.g. \"pair with "
            "high-waisted denim + white sneakers\").\n"
            "Keep it short and casual. Plain text only — no markdown."
        )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.7,  # creative but grounded in the real pieces
        )
        return response.choices[0].message.content.strip()
    except Exception:
        # Never raise — keep the agent alive with a non-empty string.
        return "Couldn't generate outfit ideas right now — try again in a moment."


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    # Named failure mode: no outfit to caption — guard BEFORE any LLM call.
    if not outfit or not outfit.strip():
        return "Can't make a fit card without an outfit — run suggest_outfit first."

    item_block = (
        f"- Name: {new_item.get('title', '')}\n"
        f"- Price: ${_fmt_price(new_item.get('price'))}\n"
        f"- Platform: {new_item.get('platform', '')}\n"
        f"- Style tags: {', '.join(new_item.get('style_tags', []))}"
    )

    system = (
        "You write first-person captions for thrift / OOTD posts — casual, "
        "authentic, lowercase-leaning, an emoji or two is fine. Never sound "
        "like a product description."
    )
    user = (
        "I just thrifted this and want a caption for my post.\n\n"
        f"Item:\n{item_block}\n\n"
        f"The outfit I styled it in:\n{outfit}\n\n"
        "Write a 2-4 sentence caption that:\n"
        "- Sounds like a real person posting their own find (first person, casual).\n"
        "- Works in the item name, price, and platform naturally — once each.\n"
        "- Captures the vibe in specific terms (not \"cute outfit\").\n"
        "Plain text only."
    )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.95,  # run hot — varied captions are a requirement here
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return "Couldn't generate a fit card right now — try again in a moment."
