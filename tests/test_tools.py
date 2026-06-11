"""
tests/test_tools.py

Isolation tests for the three FitFindr tools (Milestone 3) — at least one per
failure mode. Tool 1 (search_listings) is pure Python and tested directly.
Tools 2 & 3 call Groq, so their LLM calls are monkeypatched: the suite stays
deterministic and offline while still exercising each branch / guard.

Run:  pytest tests/
"""

import tools
from tools import search_listings, suggest_outfit, create_fit_card
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe


# ── fake Groq client (so LLM tools run offline & deterministically) ───────────

class _FakeGroqClient:
    """Stands in for groq.Groq — .chat.completions.create returns canned text."""

    def __init__(self, content="Pair it with high-waisted denim + white sneakers."):
        self._content = content
        self.chat = self  # chat.completions.create(...) → self.completions.create

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        message = type("Msg", (), {"content": self._content})()
        choice = type("Choice", (), {"message": message})()
        return type("Resp", (), {"choices": [choice]})()


# ── Tool 1: search_listings (deterministic, no LLM) ───────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_empty_results():
    # Failure mode: nothing matches → [] (no exception).
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)


def test_search_drops_zero_keyword_score():
    # Passes filters but no keyword overlap → dropped (empty list, no error).
    results = search_listings("xylophone trombone", size=None, max_price=None)
    assert results == []


def test_search_size_token_match_not_substring():
    # "s" must NOT greedily match length codes like "W30 L30" — token match only.
    results = search_listings("vintage", size="s", max_price=None)
    ids = {item["id"] for item in results}
    assert "lst_001" not in ids  # Vintage Levi's, size "W30 L30" — wrong size


def test_search_sorted_top_match_is_stable():
    # Three graphic tees tie on score; stable sort keeps dataset order → lst_002.
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert results[0]["id"] == "lst_002"


# ── Tool 2: suggest_outfit (LLM mocked) ───────────────────────────────────────

def test_suggest_outfit_empty_wardrobe(monkeypatch):
    # Failure mode: empty wardrobe must not crash — returns a non-empty string.
    monkeypatch.setattr(tools, "_get_groq_client", lambda: _FakeGroqClient())
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    out = suggest_outfit(item, get_empty_wardrobe())
    assert isinstance(out, str) and out.strip() != ""


def test_suggest_outfit_with_wardrobe(monkeypatch):
    monkeypatch.setattr(tools, "_get_groq_client", lambda: _FakeGroqClient())
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    out = suggest_outfit(item, get_example_wardrobe())
    assert isinstance(out, str) and out.strip() != ""


def test_suggest_outfit_api_failure_is_graceful(monkeypatch):
    # API failure → non-empty apologetic string, never raises.
    def boom():
        raise RuntimeError("no network")

    monkeypatch.setattr(tools, "_get_groq_client", boom)
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    out = suggest_outfit(item, get_example_wardrobe())
    assert isinstance(out, str) and out.strip() != ""


# ── Tool 3: create_fit_card (guard is LLM-free) ───────────────────────────────

def test_create_fit_card_empty_outfit_guard():
    # Failure mode: empty outfit returns an error string WITHOUT calling the LLM.
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    msg = create_fit_card("", item)
    assert isinstance(msg, str)
    assert "outfit" in msg.lower()


def test_create_fit_card_whitespace_outfit_guard():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    msg = create_fit_card("   \n  ", item)
    assert isinstance(msg, str) and msg.strip() != ""


def test_create_fit_card_happy_path(monkeypatch):
    monkeypatch.setattr(
        tools, "_get_groq_client",
        lambda: _FakeGroqClient("thrifted this tee off depop for $18 🦋"),
    )
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    out = create_fit_card("Tuck it into baggy jeans + chunky sneakers.", item)
    assert isinstance(out, str) and out.strip() != ""
