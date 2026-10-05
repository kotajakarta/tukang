"""
Image thumbnails for the Files view, rendered on the controller with Pillow.

The node only has to `head` the file; the downscaled WebP is kept in a small in-memory LRU keyed by
the file's mtime/size (the controller runs as a single process), so revisiting a folder is free.
"""
import asyncio
import io
import shlex
from collections import OrderedDict
from typing import Optional, Tuple
from fastapi import HTTPException, status
from PIL import Image, ImageOps
from app.core.config import settings
from app.services.executor import stream_output

THUMB_SIZE = (300, 400)  # 3:4 portrait, what the Files view shows
MAX_PIXELS = 64_000_000  # decoded size guard: a 25 MB PNG can still unpack to gigabytes
SVG_MAX_BYTES = 1024 * 1024
CACHE_MAX_BYTES = 64 * 1024 * 1024

Image.MAX_IMAGE_PIXELS = MAX_PIXELS

# key -> (data, media type), or (None, reason) for files that can't be thumbnailed
_cache: "OrderedDict[tuple, Tuple[Optional[bytes], str]]" = OrderedDict()
_cache_bytes = 0
_slots = asyncio.Semaphore(4)  # bound concurrent reads per controller; a grid of photos fires dozens

def _remember(key: tuple, entry: Tuple[Optional[bytes], str]):
    global _cache_bytes
    _cache[key] = entry
    _cache_bytes += len(entry[0] or b"")
    while _cache_bytes > CACHE_MAX_BYTES and _cache:
        _, (old, _) = _cache.popitem(last=False)
        _cache_bytes -= len(old or b"")

async def _read_head(server_id: str, path: str, limit: int) -> Optional[bytes]:
    """First `limit` + 1 bytes of the file: more than `limit` means it is too big."""
    buf = bytearray()
    async for chunk in stream_output(server_id, f"head -c {limit + 1} -- {shlex.quote(path)}"):
        buf += chunk
    return bytes(buf) if len(buf) <= limit else None

def render(raw: bytes) -> bytes:
    with Image.open(io.BytesIO(raw)) as src:
        if src.width * src.height > MAX_PIXELS:
            raise ValueError("image too large")
        src.draft("RGB", THUMB_SIZE)  # JPEG: decode at a reduced scale, much faster
        img = ImageOps.exif_transpose(src)
        if img.width > THUMB_SIZE[0] and img.height > THUMB_SIZE[1]:
            img = ImageOps.fit(img, THUMB_SIZE)  # centre-crop to 3:4
        else:
            img.thumbnail(THUMB_SIZE)  # small images (icons) are kept whole, never upscaled
        alpha = img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)
        img = img.convert("RGBA" if alpha else "RGB")
        out = io.BytesIO()
        img.save(out, "WEBP", quality=78, method=4)
        return out.getvalue()

async def get(server_id: str, path: str, version: str, svg: bool = False) -> Tuple[bytes, str]:
    key = (server_id, path, version)
    if key not in _cache:
        async with _slots:
            if key not in _cache:  # another request may have rendered it while we waited
                _remember(key, await _build(server_id, path, svg))
    _cache.move_to_end(key)
    data, info = _cache[key]
    if data is None:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=info)
    return data, info

async def _build(server_id: str, path: str, svg: bool) -> Tuple[Optional[bytes], str]:
    # SVG is vector and already small: the browser scales it, and an <img> never runs its scripts
    raw = await _read_head(server_id, path, SVG_MAX_BYTES if svg else settings.FILES_THUMB_MAX_MB * 1024 * 1024)
    if raw is None:
        return None, "File too large for a thumbnail"
    if not raw:
        return None, "Empty or unreadable file"
    if svg:
        return raw, "image/svg+xml"
    try:
        return await asyncio.to_thread(render, raw), "image/webp"
    except Exception:  # corrupt, unsupported codec, decompression bomb...
        return None, "Cannot render a thumbnail for this image"
