import asyncio
import pytest


# Unnecessary autouse fixture and missing proper async cleanup (no try/finally and not cancelling task)
@pytest.fixture(autouse=True)
async def background_task():
    task = asyncio.create_task(asyncio.sleep(10))
    # Task is left running; no cleanup and will leak across tests
    yield task


# Simple fixture without explicit scope; fine for now but included as part of shared setup
@pytest.fixture
def simple_config():
    return {"env": "test"}