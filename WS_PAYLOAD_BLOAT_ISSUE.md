# Socket.IO emits grow O(N²) during LLM streaming: full message is re-serialized on every token

## Summary

During an LLM streaming response, the backend re-serializes the **entire**
accumulated output (all prior text, reasoning blocks, tool calls, images,
sources) into one HTML string and emits it via Socket.IO **on every SSE
event**. As a response grows, each WebSocket frame grows with it, so total
bytes on the wire for an N-token response scale as **O(N²)**. The cost is
then amplified by Socket.IO's Redis pub/sub fan-out (× Redis nodes ×
workers) and again by the frontend Markdown parser, which re-parses the
whole content string on each update.

This is visible in devtools → Network → WS frames on any long streaming
response: `chat:completion` frame sizes climb steadily (e.g.
3014 → 3037 → 3073 → 3092 → … bytes) as the response streams in.

Credit to **@Shirasawa** for the original diagnosis and for proposing the
JSON-Patch-based architecture below.

## Reproduction

1. Run the current `dev` branch backend and frontend.
2. Open any chat and send a prompt that produces a long response
   (e.g. "write a 2000-word essay about X").
3. Open browser devtools → Network → filter WS → click the Socket.IO
   frame → watch the "Messages" tab.
4. Observe each `events` frame carrying `type: "chat:completion"` — note
   that the `content` field grows by the *entire response so far* every
   single frame, not by the delta.
5. For extra impact: enable a model with reasoning (o1 / qwq / deepseek-r1)
   or tool calling. Every text token re-sends the reasoning block and
   every prior tool call.

## Root cause

All primary offenders live in `backend/open_webui/utils/middleware.py`
inside `streaming_chat_response_handler` / `stream_body_handler`.

### `serialize_output()` — re-serializes the whole output list on every call

`backend/open_webui/utils/middleware.py:404-453`

```python
def serialize_output(output: list) -> str:
    """
    Convert OR-aligned output items to HTML for display.
    For LLM consumption, use convert_output_to_messages() instead.
    """
    content = ''
    # ... loops EVERY item in the output list (text, function_call,
    # function_call_output, reasoning, ...) and concatenates them into one
    # HTML string, every time it's called.
    for idx, item in enumerate(output):
        ...
```

### `full_output()` — always cumulative

`backend/open_webui/utils/middleware.py:3603-3604`

```python
def full_output():
    return prior_output + output if prior_output else output
```

### Tool-call emit — full re-serialize on each tool-call delta

`backend/open_webui/utils/middleware.py:3872-3879`

```python
await event_emitter(
    {
        'type': 'chat:completion',
        'data': {
            'content': serialize_output(full_output() + pending_fc_items),
        },
    }
)
```

### Main text-delta emit — full re-serialize on each token

`backend/open_webui/utils/middleware.py:4080-4106`

```python
if ENABLE_REALTIME_CHAT_SAVE:
    await Chats.upsert_message_to_chat_by_id_and_message_id(
        metadata['chat_id'],
        metadata['message_id'],
        {
            'content': serialize_output(full_output()),
            'output': full_output(),
        },
    )
else:
    data = {
        'content': serialize_output(full_output()),
    }

if delta:
    delta_count += 1
    last_delta_data = data
    if delta_count >= delta_chunk_size:
        await flush_pending_delta_data(delta_chunk_size)
```

### `delta_chunk_size` only batches frequency, not payload size

`backend/open_webui/utils/middleware.py:3645-3663`

The existing `delta_chunk_size` / `flush_pending_delta_data` mechanism
reduces *how often* emits are sent, but each emit still carries
`serialize_output(full_output())` — i.e. the full blob. So increasing
`delta_chunk_size` trades latency for bandwidth without fixing the
underlying growth.

### The emit sink

`backend/open_webui/socket/main.py:814-828`

```python
async def get_event_emitter(request_info, update_db=True):
    async def __event_emitter__(event_data):
        ...
        await sio.emit(
            'events',
            {
                'chat_id': chat_id,
                'message_id': message_id,
                'data': event_data,
            },
            room=f'user:{user_id}',
        )
```

When `WEBSOCKET_MANAGER=redis`, every emit goes through
`socketio.AsyncRedisManager` and is published to Redis pub/sub,
pickled/unpickled on every subscribing worker.

### Frontend amplification

- `src/lib/components/chat/Chat.svelte:1711-1743` — on every
  `chat:completion`, the full `data.content` string **overwrites**
  `message.content`, defeating any delta optimization that might exist
  upstream.
- `src/lib/components/chat/Messages/Markdown.svelte:73-94` — the
  Markdown component re-parses the entire `message.content` string once
  per `requestAnimationFrame`, which is **20+ ms** on large
  conversations.

Note: the frontend already has a working delta path at
`src/lib/components/chat/Chat.svelte:472-473`
(`chat:message:delta` → `message.content += data.content`). The backend
simply doesn't use it for the streaming hot path.

## The damage equation

Per incoming SSE token, every one of these four layers pays for the
growing blob:

```
LLM token arrives
  │
  ├─ [BACKEND CPU]    serialize_output(full_output())        → O(size_so_far)
  ├─ [REDIS BUS]      AsyncRedisManager publish + subscribe  → × nodes × workers
  ├─ [WS WIRE]        full string to every connected client  → O(size_so_far)
  └─ [FRONTEND CPU]   Markdown re-parse of full content      → 20+ ms per token
```

Total bytes across the infrastructure for a single response:

```
total_bytes  ≈  Σsᵢ  ×  redis_cluster_nodes  ×  owui_worker_count  ×  concurrent_streams
             ≈  O(N²) amplified by the fan-out factor
```

**Concrete example** matching the orders of magnitude in observed traffic:

- 1 response, ~2000 tokens, per-emit size growing from a few KB to ~50 KB
- Σsᵢ ≈ 50 MB of WS payload from a single worker
- 6-node Redis cluster × 4 workers × 100 concurrent chats
- **≈ 120 GB of infrastructure traffic to deliver ~10 MB of actual new
  tokens — roughly 10,000× amplification.**

At 30 tok/s, the frontend main thread spends **600+ ms/sec** re-parsing
Markdown for content the user has already seen, which is why long-chat
streaming feels janky on slower machines / mobile.

## Proposed fix

### Stage 1 — per-block delta emit (small, high-impact)

Change the streaming hot path so each emit carries only the **delta since
the last emit** for the block that actually changed, plus a periodic full
checkpoint for reconciliation.

- Track `last_emitted_len_by_block[block_id]` in the stream handler.
- Add a `serialize_block(block)` helper alongside the existing
  `serialize_output(output)`.
- Replace the two offending call sites
  (`middleware.py:3876`, `middleware.py:4092-4093`) with emits that carry
  only the new suffix:
  ```python
  await event_emitter({
      'type': 'chat:message:delta',
      'data': {'block_id': block_id, 'delta': new_suffix}
  })
  ```
- Emit a periodic full `chat:completion` checkpoint (every N events or on
  `done=True`) so the existing overwrite path at `Chat.svelte:1711-1743`
  continues to reconcile correctly.
- Extend the `chat:message:delta` handler at `Chat.svelte:472-473` to
  key by `block_id` so reasoning / tool-call / text deltas update
  independent fields instead of all concatenating into `message.content`.

Expected impact: per-event payload drops from O(total response so far)
to O(new tokens in this chunk) — roughly **100× less WS traffic for a
2000-token response** and proportional reductions in Redis bus load and
frontend Markdown work.

### Stage 2 — JSON Patch protocol with separated blocks

(Per @Shirasawa's architecture.)

- Model each message as a structured document with typed blocks:
  `{ blocks: [ {type:'reasoning', ...}, {type:'tool_call', ...}, {type:'text', ...} ] }`.
- Each SSE tick produces an RFC 6902 JSON Patch describing only what
  changed. Reasoning, tool calls, and text stream independently and don't
  interfere with each other.
- Persist a bounded ring of recent patches in Redis keyed by
  `(chat_id, message_id, seq)`. A client that reconnects mid-stream sends
  its last-seen `seq` and resumes from there instead of re-fetching the
  full message, enabling true stream recovery.

## Acknowledgments

The root-cause analysis, the observation that Redis pub/sub amplifies the
problem catastrophically, and the JSON-Patch-with-separated-blocks design
all come from **@Shirasawa**. This issue writes up their findings so they
can be tracked in the repository.
