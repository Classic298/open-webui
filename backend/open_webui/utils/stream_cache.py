"""Redis-backed cache of in-progress streaming chat responses.

When ``ENABLE_REDIS_STREAM_CACHE`` is set, the cumulative snapshot of an
assistant message is mirrored to Redis while it streams. A client that
reconnects or refreshes mid-generation — landing on any worker — can then fetch
the latest snapshot via the ``chat:stream:resume`` socket event and resume
rendering immediately, instead of seeing an empty message until the response
completes and is persisted to the database.

The snapshot is the same cumulative ``{'content': ..., 'output': ...}`` payload
that is already broadcast on the ``chat:completion`` event, so a single replayed
snapshot fully repaints the message; subsequent live events continue normally.

Everything here degrades gracefully: if Redis is not configured the helpers are
no-ops, and any Redis error is swallowed (logged at debug) so a cache hiccup can
never break the live stream itself.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional

from open_webui.env import (
    ENABLE_REDIS_STREAM_CACHE,
    REDIS_KEY_PREFIX,
    REDIS_STREAM_CACHE_TTL,
    REDIS_STREAM_CACHE_WRITE_INTERVAL_MS,
)
from open_webui.utils.redis import get_redis_client

log = logging.getLogger(__name__)

_STREAM_CACHE_PREFIX = f'{REDIS_KEY_PREFIX}:stream_cache'

# Per-process throttle state: last Redis write time (monotonic seconds) keyed by
# message id. The generating background task for a given message runs on a single
# worker, so a process-local map is sufficient to coalesce that message's writes.
_last_write: dict[str, float] = {}


def _key(chat_id: str, message_id: str) -> str:
    return f'{_STREAM_CACHE_PREFIX}:{chat_id}:{message_id}'


def _redis():
    """Return the shared async Redis client, or ``None`` when not configured.

    ``get_redis_client`` caches connections by parameters, so this reuses the
    same client instance that the rest of the app (tasks, etc.) relies on.
    """
    return get_redis_client(async_mode=True)


def _should_write(message_id: str, force: bool) -> bool:
    """Apply the per-message write throttle. ``force`` always writes."""
    if force or REDIS_STREAM_CACHE_WRITE_INTERVAL_MS <= 0:
        return True

    now = time.monotonic()
    last = _last_write.get(message_id)
    if last is not None and (now - last) * 1000 < REDIS_STREAM_CACHE_WRITE_INTERVAL_MS:
        return False
    _last_write[message_id] = now
    return True


async def write_stream_snapshot(
    chat_id: Optional[str],
    message_id: Optional[str],
    snapshot: dict,
    *,
    force: bool = False,
) -> None:
    """Store the latest cumulative snapshot for an in-progress message.

    Writes are throttled per message (see ``REDIS_STREAM_CACHE_WRITE_INTERVAL_MS``)
    to bound bandwidth; pass ``force=True`` for the terminal ``done`` snapshot so
    a client whose generation finishes during its reconnect window can still
    recover the completed message.
    """
    if not ENABLE_REDIS_STREAM_CACHE or not chat_id or not message_id:
        return
    if not _should_write(message_id, force):
        return

    redis = _redis()
    if redis is None:
        return

    try:
        await redis.set(
            _key(chat_id, message_id),
            json.dumps(snapshot),
            ex=REDIS_STREAM_CACHE_TTL,
        )
    except Exception:
        log.debug('Failed to write stream snapshot to Redis', exc_info=True)

    if force:
        # Terminal snapshot written — drop throttle state for this message.
        _last_write.pop(message_id, None)


async def read_stream_snapshot(
    chat_id: Optional[str],
    message_id: Optional[str],
) -> Optional[dict]:
    """Return the cached snapshot for a message, or ``None`` if absent."""
    if not ENABLE_REDIS_STREAM_CACHE or not chat_id or not message_id:
        return None

    redis = _redis()
    if redis is None:
        return None

    try:
        raw = await redis.get(_key(chat_id, message_id))
        if raw is None:
            return None
        return json.loads(raw)
    except Exception:
        log.debug('Failed to read stream snapshot from Redis', exc_info=True)
        return None


async def clear_stream_snapshot(
    chat_id: Optional[str],
    message_id: Optional[str],
) -> None:
    """Remove a cached snapshot (best-effort; TTL is the safety net)."""
    if not ENABLE_REDIS_STREAM_CACHE or not chat_id or not message_id:
        return

    _last_write.pop(message_id, None)

    redis = _redis()
    if redis is None:
        return

    try:
        await redis.delete(_key(chat_id, message_id))
    except Exception:
        log.debug('Failed to clear stream snapshot from Redis', exc_info=True)
