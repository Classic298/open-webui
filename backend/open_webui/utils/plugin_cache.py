# plugin_cache.py
#
# Cross-worker invalidation for tool + function module caches.
#
# Tool / function source code lives in the DB (shared across workers),
# but the compiled Python module is cached per-worker in
# ``request.app.state.TOOLS`` / ``FUNCTIONS``.  Saving a tool on
# worker A does not touch worker B's module dict, so worker B keeps
# serving the stale module until the process restarts.
#
# We fix that by publishing an invalidation message on Redis whenever
# a plugin is created / updated / deleted / toggled.  Every worker
# subscribes on startup and drops the matching entries from its local
# caches, forcing the next invocation to reload fresh from the DB.
#
# When Redis is not configured we fall back to in-process invalidation
# only — the single-worker case "just works" because save already
# updates that worker's cache directly.

import asyncio
import json
import logging
from typing import Literal

from redis.asyncio import Redis

from open_webui.env import REDIS_KEY_PREFIX

log = logging.getLogger(__name__)

REDIS_PLUGIN_CACHE_CHANNEL = f"{REDIS_KEY_PREFIX}:plugins:invalidate"

PluginKind = Literal["tool", "function"]


def _local_invalidate(app, kind: PluginKind, plugin_id: str) -> None:
    """Drop the per-worker cache entries for a plugin id.

    Safe to call when the caches don't exist yet (first invocation on
    this worker, startup race with the listener, etc.).
    """
    try:
        if kind == "tool":
            store = getattr(app.state, "TOOLS", None)
            content_store = getattr(app.state, "TOOL_CONTENTS", None)
        else:
            store = getattr(app.state, "FUNCTIONS", None)
            content_store = getattr(app.state, "FUNCTION_CONTENTS", None)
        if store is not None:
            store.pop(plugin_id, None)
        if content_store is not None:
            content_store.pop(plugin_id, None)
    except Exception as e:
        log.exception(f"plugin-cache: local invalidate failed ({kind}/{plugin_id}): {e}")


async def publish_invalidation(app, kind: PluginKind, plugin_id: str) -> None:
    """Invalidate locally + publish to Redis for the other workers.

    Called by the save / update / delete / toggle handlers.  The local
    invalidation covers the single-worker case and the worker that
    received the write request; the Redis publish covers every other
    worker in a multi-process deployment.
    """
    _local_invalidate(app, kind, plugin_id)
    redis: Redis | None = getattr(app.state, "redis", None)
    if redis is None:
        return
    try:
        payload = json.dumps({"kind": kind, "id": plugin_id})
        await redis.publish(REDIS_PLUGIN_CACHE_CHANNEL, payload)
    except Exception as e:
        log.exception(f"plugin-cache: redis publish failed ({kind}/{plugin_id}): {e}")


async def plugin_cache_listener(app) -> None:
    """Subscribe to invalidations and drop local caches on receipt.

    Mirrors the existing ``redis_task_command_listener`` pattern.
    Started from the lifespan hook in main.py.  Silently exits if
    Redis is unavailable.
    """
    redis: Redis | None = getattr(app.state, "redis", None)
    if redis is None:
        return
    pubsub = redis.pubsub()
    try:
        await pubsub.subscribe(REDIS_PLUGIN_CACHE_CHANNEL)
    except Exception as e:
        log.exception(f"plugin-cache: redis subscribe failed: {e}")
        return

    async for message in pubsub.listen():
        if message.get("type") != "message":
            continue
        try:
            data = message.get("data")
            if isinstance(data, (bytes, bytearray)):
                data = data.decode("utf-8", "replace")
            payload = json.loads(data)
            kind = payload.get("kind")
            plugin_id = payload.get("id")
            if kind not in ("tool", "function") or not plugin_id:
                continue
            _local_invalidate(app, kind, plugin_id)
            log.info(f"plugin-cache: invalidated {kind}/{plugin_id}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception(f"plugin-cache: listener handler failed: {e}")
