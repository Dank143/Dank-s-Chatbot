import pytest
from app.routers.messages import _generate_title

pytestmark = pytest.mark.asyncio

async def test_generate_title_basic():
    res = await _generate_title("Can you help me write a python script to parse a CSV file?")
    
    assert isinstance(res, str)
    assert len(res.split()) >= 3
    assert len(res.split()) <= 15 # Allow up to 15 to account for fallback truncation
    
    # Check if the title is relevant
    assert "python" in res.lower() or "csv" in res.lower() or "parse" in res.lower()

async def test_generate_title_fallback():
    # Provide an extremely short or weird prompt that might fall back, though the LLM might still title it
    res = await _generate_title("Hello")
    assert isinstance(res, str)
    assert len(res) > 0
