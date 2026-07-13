"""Behavioral tests for the streaming per-chunk idle timeout.

These guard the contract that ``AIOHTTP_CLIENT_TIMEOUT_STREAM_IDLE`` relies on:
the streaming OpenAI-compatible calls in ``routers/openai.py`` build their
timeout as ``aiohttp.ClientTimeout(total=..., sock_read=STREAM_IDLE)``. The
``sock_read`` leg must abort a stream that *stalls* mid-response while leaving
an *actively producing* stream (of any length) untouched, and must be a no-op
when unset (``None``) so the default behavior is unchanged.

The tests are self-contained (only ``aiohttp`` + ``pytest``) and do not import
the full application, so they run without the backend's heavy dependency set.
"""

import asyncio

import aiohttp
from aiohttp import web
from aiohttp.test_utils import unused_port

# How long the stall handler hangs after its first chunk. It only needs to
# outlast the longest client timeout used against it (total=2s in the unset
# test) — kept short so ``runner.cleanup()`` doesn't block draining a handler
# that is still sleeping.
_STALL_SECONDS = 3


async def _stall_handler(request):
    """Emit one chunk, then hang — simulates a stalled upstream."""
    resp = web.StreamResponse()
    resp.headers['Content-Type'] = 'text/event-stream'
    await resp.prepare(request)
    await resp.write(b'data: chunk-0\n\n')
    await asyncio.sleep(_STALL_SECONDS)
    return resp


async def _steady_handler(request):
    """Emit 8 chunks 0.5s apart — active stream, never idle longer than 0.5s."""
    resp = web.StreamResponse()
    resp.headers['Content-Type'] = 'text/event-stream'
    await resp.prepare(request)
    for i in range(8):
        await resp.write(f'data: chunk-{i}\n\n'.encode())
        await asyncio.sleep(0.5)
    await resp.write_eof()
    return resp


async def _serve():
    port = unused_port()
    app = web.Application()
    app.add_routes(
        [
            web.get('/stall', _stall_handler),
            web.get('/steady', _steady_handler),
        ]
    )
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', port)
    await site.start()
    return runner, f'http://127.0.0.1:{port}'


async def _run_stall_trips_on_idle():
    runner, base = await _serve()
    try:
        # total is a long dead-man backstop; sock_read is the short idle cap.
        timeout = aiohttp.ClientTimeout(total=10, sock_read=1)
        loop = asyncio.get_event_loop()
        start = loop.time()
        got_first_chunk = False
        async with aiohttp.ClientSession() as session:
            async with session.get(f'{base}/stall', timeout=timeout) as resp:
                async for _ in resp.content:
                    got_first_chunk = True
        return None, loop.time() - start, got_first_chunk
    except asyncio.TimeoutError:
        return 'timeout', loop.time() - start, got_first_chunk
    finally:
        await runner.cleanup()


async def _run_steady_completes():
    runner, base = await _serve()
    try:
        timeout = aiohttp.ClientTimeout(total=10, sock_read=1)
        chunks = 0
        async with aiohttp.ClientSession() as session:
            async with session.get(f'{base}/steady', timeout=timeout) as resp:
                async for line in resp.content:
                    if line.strip():
                        chunks += 1
        return chunks
    finally:
        await runner.cleanup()


async def _run_unset_ignores_idle():
    runner, base = await _serve()
    try:
        # sock_read=None (the unset default): idle must NOT trip; only total does.
        timeout = aiohttp.ClientTimeout(total=2, sock_read=None)
        loop = asyncio.get_event_loop()
        start = loop.time()
        async with aiohttp.ClientSession() as session:
            async with session.get(f'{base}/stall', timeout=timeout) as resp:
                async for _ in resp.content:
                    pass
        return None, loop.time() - start
    except asyncio.TimeoutError:
        return 'timeout', loop.time() - start
    finally:
        await runner.cleanup()


def test_stalled_stream_trips_sock_read_before_total():
    kind, elapsed, got_first_chunk = asyncio.run(_run_stall_trips_on_idle())
    assert kind == 'timeout'
    # Tripped by the 1s idle cap, nowhere near the 30s total backstop.
    assert 0.8 <= elapsed <= 5.0, elapsed
    # The first chunk still arrives before the stall — only the gap trips.
    assert got_first_chunk is True


def test_active_stream_is_not_interrupted_by_idle_cap():
    chunks = asyncio.run(_run_steady_completes())
    # All 8 chunks delivered: idle gaps (0.5s) never exceed sock_read (1s).
    assert chunks == 8


def test_unset_sock_read_does_not_trip_on_idle():
    kind, elapsed = asyncio.run(_run_unset_ignores_idle())
    # With sock_read=None the stall is only bounded by total (2s), not idle.
    assert kind == 'timeout'
    assert elapsed >= 1.8, elapsed
