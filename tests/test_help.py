import pytest
from unittest.mock import AsyncMock, MagicMock

from routers.broker import help_command, router


@pytest.mark.asyncio
async def test_help_publishes_to_queue(monkeypatch):
    publish = AsyncMock()
    monkeypatch.setattr(router.broker, "publish", publish)

    result = await help_command("lil", "не открывается чат", user=MagicMock())

    assert result == {"data": "ok"}
    text = publish.await_args.args[0]
    assert "lil" in text
    assert "не открывается чат" in text
    assert publish.await_args.kwargs["queue"] == "help"