import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, MagicMock

from routers.uploads import upload_file


def uploaded(content_type, content, name="photo.png"):
    file = MagicMock()
    file.content_type = content_type
    file.filename = name
    file.read = AsyncMock(return_value=content)
    return file


@pytest.mark.asyncio
async def test_rejects_unknown_type():
    with pytest.raises(HTTPException) as exc:
        await upload_file(file=uploaded("text/plain", b"hi"), current_user=MagicMock())

    assert exc.value.status_code == 400
    assert exc.value.detail == "incorrect type file"


@pytest.mark.asyncio
async def test_rejects_oversized_file(monkeypatch):
    monkeypatch.setattr("routers.uploads.MAX_FILE_SIZE", 4)

    with pytest.raises(HTTPException) as exc:
        await upload_file(
            file=uploaded("image/png", b"12345"),
            current_user=MagicMock(),
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "very big file"


@pytest.mark.asyncio
async def test_saves_allowed_file(monkeypatch, tmp_path):
    monkeypatch.setattr("routers.uploads.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr("routers.uploads.uuid.uuid4", lambda: "fixed-id")

    saved = await upload_file(
        file=uploaded("image/png", b"png", name="shot.png"),
        current_user=MagicMock(),
    )

    assert saved["name"] == "shot.png"
    assert saved["url"] == "/files/fixed-id.png"
    assert saved["size"] == 3
    assert saved["type"] == "image/png"
    assert (tmp_path / "fixed-id.png").read_bytes() == b"png"
