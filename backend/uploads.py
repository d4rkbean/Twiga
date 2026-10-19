"""Reading an uploaded file with a size limit.

`await file.read()` loads the whole upload in memory whatever its size. These
helpers read it in chunks and stop as soon as the limit is exceeded, so an
oversized file never ends up in memory in one piece.
"""

from __future__ import annotations

from fastapi import UploadFile

MEGABYTE = 1024 * 1024
_CHUNK_SIZE = MEGABYTE


async def read_limited(file: UploadFile, max_bytes: int) -> bytes | None:
    """The content of `file`, or None when it is larger than `max_bytes`."""
    chunks = []
    size = 0
    while True:
        chunk = await file.read(_CHUNK_SIZE)
        if not chunk:
            return b"".join(chunks)
        size += len(chunk)
        if size > max_bytes:
            return None
        chunks.append(chunk)
