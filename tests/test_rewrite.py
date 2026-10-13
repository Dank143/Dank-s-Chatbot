import pytest
from app.search.llm_processing import _rewrite_query

pytestmark = pytest.mark.asyncio

async def test_rewrite_query_basic():
    res = await _rewrite_query("who is the author of mistborn")
    
    assert isinstance(res, dict)
    assert "query" in res
    assert "intent" in res
    assert "entity" in res
    
    # We don't assert exact values because it's LLM-generated, but we verify it found something reasonable
    assert res["intent"] in ["wiki", "general", "documentation", "opinion", "dictionary"]
    assert "mistborn" in res["query"].lower() or "author" in res["query"].lower()
    assert "mistborn" in res["entity"].lower() or "author" in res["entity"].lower()

async def test_rewrite_query_with_context():
    context = "User: Who wrote Mistborn?\nAssistant: Brandon Sanderson."
    res = await _rewrite_query("what other books did he write?", context)
    
    assert isinstance(res, dict)
    assert "brandon sanderson" in res["query"].lower()
