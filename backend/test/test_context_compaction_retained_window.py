"""Regression tests for context-compaction retained-window persistence.

Bug: the summary checkpoint was stored on the *current* (last) user message,
i.e. the END of the retained recent window. Reconstruction
(``_apply_latest_summary_checkpoint``) keeps messages from the marker forward,
so on the compaction turn it worked, but on every later turn the retained ~40%
window that sat *before* the marker was sliced away — leaving only
``summary + current_user_message`` and breaking both caching and continuity.

Fix: anchor the checkpoint to the FIRST retained message
(``_retained_checkpoint_message_id``) so the whole window survives
reconstruction on subsequent turns.

These import the real functions, so they exercise the shipped logic. They need
the backend dependency set installed (the normal dev/test environment).
"""

from open_webui.utils.context_compaction import (
    _apply_latest_summary_checkpoint,
    _find_compaction_boundary,
    _retained_checkpoint_message_id,
)


def _make_chain():
    chain = [{'id': f'm{i}', 'role': 'assistant' if i % 2 == 0 else 'user', 'content': f'msg{i}'} for i in range(1, 10)]
    chain.append({'id': 'uA', 'role': 'user', 'content': 'current prompt A'})
    return chain


def _rebuild_turn2(chain, checkpoint_id, summary='SUMMARY'):
    """The next-turn DB chain: same messages (marked at checkpoint) + a new exchange."""
    rebuilt = [dict(message) for message in chain]
    for message in rebuilt:
        if message['id'] == checkpoint_id:
            message['contextSummary'] = summary
    rebuilt.append({'id': 'aA', 'role': 'assistant', 'content': 'answer A'})
    rebuilt.append({'id': 'uB', 'role': 'user', 'content': 'prompt B'})
    return rebuilt


def test_retained_checkpoint_is_first_message_with_id():
    recent = [
        {'role': 'user', 'content': 'no id here'},  # synthetic (e.g. regeneration prompt)
        {'id': 'm7', 'role': 'user', 'content': 'first real'},
        {'id': 'm8', 'role': 'assistant', 'content': 'second real'},
    ]
    assert _retained_checkpoint_message_id(recent) == 'm7'


def test_retained_checkpoint_none_when_no_ids():
    assert _retained_checkpoint_message_id([{'role': 'user', 'content': 'x'}]) is None
    assert _retained_checkpoint_message_id([]) is None


def test_retained_window_survives_next_turn_with_fixed_checkpoint():
    chain = _make_chain()
    boundary = _find_compaction_boundary(chain)
    recent = chain[boundary:]
    assert len(recent) >= 2  # more than just the current user message

    checkpoint_id = _retained_checkpoint_message_id(recent)
    assert checkpoint_id == recent[0]['id']

    reconstructed, summary = _apply_latest_summary_checkpoint(_rebuild_turn2(chain, checkpoint_id))
    reconstructed_ids = [m['id'] for m in reconstructed]

    # The entire retained window is preserved, and reconstruction begins at it.
    assert reconstructed_ids[0] == recent[0]['id']
    assert all(m['id'] in reconstructed_ids for m in recent)
    assert summary == 'SUMMARY'


def test_old_checkpoint_on_last_message_would_drop_the_window():
    """Guard the regression: marking the current (last) message loses the window."""
    chain = _make_chain()
    boundary = _find_compaction_boundary(chain)
    recent = chain[boundary:]

    # Old behavior stored the summary on the current user message (chain[-1]).
    reconstructed, _ = _apply_latest_summary_checkpoint(_rebuild_turn2(chain, chain[-1]['id']))
    reconstructed_ids = [m['id'] for m in reconstructed]

    # Only the current message + the new exchange survive — the retained window
    # before it is gone. This is exactly what the fix prevents.
    assert reconstructed_ids == ['uA', 'aA', 'uB']
    dropped = [m['id'] for m in recent[:-1]]
    assert dropped and all(mid not in reconstructed_ids for mid in dropped)
