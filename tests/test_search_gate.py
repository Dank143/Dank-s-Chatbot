import pytest
from app.search.gate import should_search

pytestmark = pytest.mark.asyncio

async def test_should_search_kelsier():
    res = await should_search("Who is Kelsier from Mistborn?")
    assert res is True

async def test_should_not_search_gravity():
    res = await should_search("Explain how gravity works")
    assert res is False
