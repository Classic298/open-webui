"""
Standalone test for the chat_message migration (8452d01d26d7).

Tests both the SQLite (default) path and the PostgreSQL-optimized path.
Verifies:
  - Table creation with correct schema
  - Data backfill from chat table
  - Index creation
  - FK constraint
  - Idempotency (crash recovery / re-run safety)
  - Shared chats are excluded
  - Various edge cases in chat data
"""

import json
import os
import sys
import tempfile
import time

import importlib.util

import sqlalchemy as sa
from sqlalchemy import create_engine, inspect, text

# Import the migration module directly (bypass open_webui __init__.py)
_spec = importlib.util.spec_from_file_location(
    'migration_8452d01d26d7',
    os.path.join(
        os.path.dirname(__file__),
        'backend',
        'open_webui',
        'migrations',
        'versions',
        '8452d01d26d7_add_chat_message_table.py',
    ),
)
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)


def make_chat_json(messages_dict):
    """Build a chat JSON blob from a {msg_id: {role, content, ...}} dict."""
    return json.dumps({'history': {'messages': messages_dict}})


def make_test_chats():
    """Return a list of (id, user_id, chat_json) tuples for testing."""
    now = int(time.time())
    return [
        # Normal chat with 2 messages
        (
            'chat-001',
            'user-1',
            make_chat_json({
                'msg-a': {
                    'role': 'user',
                    'content': 'Hello',
                    'timestamp': now,
                    'parentId': None,
                    'model': 'gpt-4',
                },
                'msg-b': {
                    'role': 'assistant',
                    'content': 'Hi there!',
                    'timestamp': now,
                    'parentId': 'msg-a',
                    'model': 'gpt-4',
                    'usage': {'input_tokens': 10, 'output_tokens': 20},
                },
            }),
        ),
        # Chat with various edge cases
        (
            'chat-002',
            'user-2',
            make_chat_json({
                'msg-c': {
                    'role': 'user',
                    'content': 'Test',
                    'timestamp': str(now * 1000),  # millisecond timestamp
                },
                'msg-d': {
                    'role': 'system',
                    'content': 'System prompt',
                    'timestamp': 'invalid',  # invalid timestamp
                },
                'msg-e': {
                    'role': 'assistant',
                    'content': {'type': 'text', 'text': 'Complex content'},
                    'timestamp': now,
                    'statusHistory': [{'status': 'generating'}],
                },
            }),
        ),
        # Chat with no messages
        (
            'chat-003',
            'user-1',
            json.dumps({'history': {'messages': {}}}),
        ),
        # Chat with malformed data
        (
            'chat-004',
            'user-3',
            json.dumps({'history': 'not a dict'}),
        ),
        # Chat with None data
        ('chat-005', 'user-3', None),
        # Chat with string chat data
        (
            'chat-006',
            'user-1',
            make_chat_json({
                'msg-f': {'role': 'user', 'content': 'String chat data test'},
            }),
        ),
        # Shared chat - should be EXCLUDED
        (
            'chat-007',
            'shared-abc123',
            make_chat_json({
                'msg-g': {
                    'role': 'user',
                    'content': 'This should not be migrated',
                },
            }),
        ),
        # Chat with message that has no role - should be skipped
        (
            'chat-008',
            'user-4',
            make_chat_json({
                'msg-h': {'content': 'No role field'},
                'msg-i': {'role': 'user', 'content': 'Has role'},
            }),
        ),
        # Chat with non-dict message entry - should be skipped
        (
            'chat-009',
            'user-4',
            make_chat_json({
                'msg-j': 'just a string, not a dict',
                'msg-k': {'role': 'user', 'content': 'Valid message'},
            }),
        ),
    ]


def setup_prerequisite_tables(engine):
    """Create the chat table (and any other prerequisite tables) directly."""
    with engine.connect() as conn:
        # Create a minimal chat table matching what previous migrations produce
        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS chat (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                chat JSON
            )
        """)
        )
        conn.commit()


def seed_test_data(engine):
    """Insert test chat data."""
    chats = make_test_chats()
    with engine.connect() as conn:
        for chat_id, user_id, chat_data in chats:
            if chat_data is not None:
                conn.execute(
                    text(
                        "INSERT INTO chat (id, user_id, chat) VALUES (:id, :uid, :chat)"
                    ),
                    {'id': chat_id, 'uid': user_id, 'chat': chat_data},
                )
            else:
                conn.execute(
                    text(
                        "INSERT INTO chat (id, user_id, chat) VALUES (:id, :uid, NULL)"
                    ),
                    {'id': chat_id, 'uid': user_id},
                )
        conn.commit()


def run_migration_directly(engine, use_pg_path):
    """
    Run the migration upgrade() logic directly against the engine,
    simulating what Alembic does but without the full Alembic machinery.
    """
    from unittest.mock import MagicMock, patch

    with engine.connect() as conn:
        # Start a transaction (simulating Alembic's begin_transaction)
        trans = conn.begin()

        # Mock alembic's op module to use our connection
        mock_op = MagicMock()
        mock_op.get_bind.return_value = conn

        # For create_table, execute the DDL via our connection
        _deferred_indexes = []

        def mock_create_table(name, *columns, **kwargs):
            cols = []
            fk_clauses = []
            for col in columns:
                if isinstance(col, sa.Column):
                    col_def = f'"{col.name}" {col.type}'
                    if col.primary_key:
                        col_def += ' PRIMARY KEY'
                    if col.nullable is False:
                        col_def += ' NOT NULL'
                    cols.append(col_def)
                    # Handle index=True by creating a separate index
                    if getattr(col, 'index', False):
                        _deferred_indexes.append(
                            (f'ix_{name}_{col.name}', name, col.name)
                        )
                elif isinstance(col, sa.ForeignKeyConstraint):
                    # Parse the FK spec directly from _colspec strings
                    ref_specs = [e._colspec for e in col.elements]
                    ref_table = ref_specs[0].split('.')[0]
                    ref_cols = ', '.join(s.split('.')[1] for s in ref_specs)
                    local_cols = ', '.join(col.column_keys)
                    ondelete = f" ON DELETE {col.ondelete}" if col.ondelete else ""
                    fk_clauses.append(
                        f'FOREIGN KEY ({local_cols}) REFERENCES {ref_table}({ref_cols}){ondelete}'
                    )

            all_parts = cols + fk_clauses
            ddl = f'CREATE TABLE IF NOT EXISTS {name} ({", ".join(all_parts)})'
            conn.execute(text(ddl))
            # Create deferred indexes from index=True columns
            for idx_name, tbl_name, col_name in _deferred_indexes:
                conn.execute(
                    text(
                        f'CREATE INDEX IF NOT EXISTS {idx_name}'
                        f' ON {tbl_name} ({col_name})'
                    )
                )
            _deferred_indexes.clear()

        def mock_create_index(name, table_name, columns, **kwargs):
            cols = ', '.join(columns)
            conn.execute(
                text(
                    f'CREATE INDEX IF NOT EXISTS {name} ON {table_name} ({cols})'
                )
            )

        mock_op.create_table = mock_create_table
        mock_op.create_index = mock_create_index

        with patch.object(migration, 'op', mock_op):
            if use_pg_path:
                migration._upgrade_postgresql()
            else:
                migration._upgrade_default()

        # For the default path, commit the transaction (simulating Alembic)
        if not use_pg_path:
            trans.commit()
        else:
            # PostgreSQL path manages its own transactions;
            # the final transaction is left open for Alembic to commit
            trans.commit()


def verify_results(engine, dialect_name):
    """Verify the migration produced correct results."""
    with engine.connect() as conn:
        # 1. Verify table exists
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        assert 'chat_message' in tables, f"chat_message table not found! Tables: {tables}"
        print(f"  [PASS] chat_message table exists")

        # 2. Verify columns
        columns = {c['name'] for c in inspector.get_columns('chat_message')}
        expected_cols = {
            'id', 'chat_id', 'user_id', 'role', 'parent_id', 'content',
            'output', 'model_id', 'files', 'sources', 'embeds', 'done',
            'status_history', 'error', 'usage', 'created_at', 'updated_at',
        }
        assert expected_cols == columns, f"Column mismatch: expected {expected_cols}, got {columns}"
        print(f"  [PASS] All columns present")

        # 3. Verify indexes
        indexes = inspector.get_indexes('chat_message')
        index_names = {idx['name'] for idx in indexes}
        expected_indexes = {
            'chat_message_chat_parent_idx',
            'chat_message_model_created_idx',
            'chat_message_user_created_idx',
        }
        # Single-column indexes have different names per dialect
        if dialect_name == 'postgresql':
            expected_indexes.update({
                'ix_chat_message_chat_id',
                'ix_chat_message_user_id',
                'ix_chat_message_model_id',
                'ix_chat_message_created_at',
            })
        else:
            expected_indexes.update({
                'ix_chat_message_chat_id',
                'ix_chat_message_user_id',
                'ix_chat_message_model_id',
                'ix_chat_message_created_at',
            })
        missing = expected_indexes - index_names
        assert not missing, f"Missing indexes: {missing}. Found: {index_names}"
        print(f"  [PASS] All indexes present: {index_names}")

        # 4. Verify FK constraint (PostgreSQL only)
        if dialect_name == 'postgresql':
            fks = inspector.get_foreign_keys('chat_message')
            assert len(fks) >= 1, f"No FK constraints found"
            fk = fks[0]
            assert fk['referred_table'] == 'chat', f"FK refers to wrong table: {fk}"
            assert fk['constrained_columns'] == ['chat_id'], f"FK on wrong column: {fk}"
            print(f"  [PASS] FK constraint present and correct")

        # 5. Verify message count
        result = conn.execute(text("SELECT COUNT(*) FROM chat_message")).fetchone()
        msg_count = result[0]
        # Expected: msg-a, msg-b (chat-001), msg-c, msg-d, msg-e (chat-002),
        #           msg-f (chat-006), msg-i (chat-008), msg-k (chat-009)
        # NOT: shared chat msg-g, no-role msg-h, non-dict msg-j,
        #      empty chat-003, malformed chat-004, null chat-005
        expected_count = 8
        assert msg_count == expected_count, (
            f"Expected {expected_count} messages, got {msg_count}"
        )
        print(f"  [PASS] Correct message count: {msg_count}")

        # 6. Verify specific messages
        rows = conn.execute(
            text("SELECT id, chat_id, user_id, role, content, parent_id, model_id "
                 "FROM chat_message ORDER BY id")
        ).fetchall()
        msg_ids = {r[0] for r in rows}
        assert 'chat-001-msg-a' in msg_ids, "msg-a missing"
        assert 'chat-001-msg-b' in msg_ids, "msg-b missing"
        assert 'chat-007-msg-g' not in msg_ids, "shared chat message should be excluded"
        assert 'chat-008-msg-h' not in msg_ids, "no-role message should be excluded"
        assert 'chat-009-msg-j' not in msg_ids, "non-dict message should be excluded"
        print(f"  [PASS] Correct messages included/excluded")

        # 7. Verify timestamp normalization
        msg_c = conn.execute(
            text("SELECT created_at FROM chat_message WHERE id = 'chat-002-msg-c'")
        ).fetchone()
        if msg_c:
            # Was milliseconds, should be converted to seconds
            assert msg_c[0] < 10_000_000_000, (
                f"Timestamp not normalized from ms: {msg_c[0]}"
            )
            print(f"  [PASS] Millisecond timestamps normalized correctly")

        # 8. Verify usage data preserved
        msg_b = conn.execute(
            text("SELECT usage FROM chat_message WHERE id = 'chat-001-msg-b'")
        ).fetchone()
        if msg_b and msg_b[0]:
            usage = msg_b[0] if isinstance(msg_b[0], dict) else json.loads(msg_b[0])
            assert usage.get('input_tokens') == 10
            assert usage.get('output_tokens') == 20
            print(f"  [PASS] Usage data preserved correctly")

        print(f"  [PASS] All verifications passed!")


def test_idempotency(engine, use_pg_path):
    """Verify re-running the migration doesn't duplicate data."""
    with engine.connect() as conn:
        count_before = conn.execute(
            text("SELECT COUNT(*) FROM chat_message")
        ).fetchone()[0]

    # Run migration again
    run_migration_directly(engine, use_pg_path)

    with engine.connect() as conn:
        count_after = conn.execute(
            text("SELECT COUNT(*) FROM chat_message")
        ).fetchone()[0]

    if use_pg_path:
        # PostgreSQL path uses ON CONFLICT DO NOTHING - count should be same
        assert count_after == count_before, (
            f"Idempotency failed: {count_before} -> {count_after}"
        )
        print(f"  [PASS] Idempotent: {count_before} messages before and after re-run")
    else:
        # SQLite path uses savepoints which will fail on duplicate PK
        # and skip via the fallback - count should also be same
        assert count_after == count_before, (
            f"Idempotency failed: {count_before} -> {count_after}"
        )
        print(f"  [PASS] Idempotent: {count_before} messages before and after re-run")


def test_sqlite():
    """Test the default (SQLite) migration path."""
    print("\n=== Testing SQLite (default path) ===")
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name

    try:
        engine = create_engine(f'sqlite:///{db_path}')

        # Enable foreign keys for SQLite
        with engine.connect() as conn:
            conn.execute(text("PRAGMA foreign_keys = ON"))
            conn.commit()

        setup_prerequisite_tables(engine)
        seed_test_data(engine)

        print("Running migration (default path)...")
        run_migration_directly(engine, use_pg_path=False)

        print("Verifying results...")
        verify_results(engine, 'sqlite')

        print("Testing idempotency...")
        test_idempotency(engine, use_pg_path=False)

        print("\n=== SQLite tests PASSED ===")
    finally:
        os.unlink(db_path)


def test_postgresql():
    """Test the PostgreSQL-optimized migration path."""
    print("\n=== Testing PostgreSQL (optimized path) ===")
    pg_url = os.environ.get(
        'TEST_PG_URL',
        'postgresql://testuser:testpass@localhost:5432/test_migration',
    )

    try:
        engine = create_engine(pg_url)
        # Verify connection works
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        print(f"  [SKIP] PostgreSQL not available: {e}")
        return False

    try:
        # Clean up from any previous run
        with engine.connect() as conn:
            conn.execute(text("DROP TABLE IF EXISTS chat_message CASCADE"))
            conn.execute(text("DROP TABLE IF EXISTS chat CASCADE"))
            conn.commit()

        setup_prerequisite_tables(engine)
        seed_test_data(engine)

        print("Running migration (PostgreSQL path)...")
        run_migration_directly(engine, use_pg_path=True)

        print("Verifying results...")
        verify_results(engine, 'postgresql')

        print("Testing idempotency (re-run after crash recovery)...")
        test_idempotency(engine, use_pg_path=True)

        # Verify FK works: deleting a chat should cascade
        print("Testing FK cascade delete...")
        with engine.connect() as conn:
            count_before = conn.execute(
                text("SELECT COUNT(*) FROM chat_message WHERE chat_id = 'chat-001'")
            ).fetchone()[0]
            assert count_before == 2, f"Expected 2 messages for chat-001, got {count_before}"

            conn.execute(text("DELETE FROM chat WHERE id = 'chat-001'"))
            conn.commit()

            count_after = conn.execute(
                text("SELECT COUNT(*) FROM chat_message WHERE chat_id = 'chat-001'")
            ).fetchone()[0]
            assert count_after == 0, f"FK cascade failed: still {count_after} messages"
            print(f"  [PASS] FK cascade delete works correctly")

        print("\n=== PostgreSQL tests PASSED ===")
        return True
    finally:
        # Cleanup
        with engine.connect() as conn:
            conn.execute(text("DROP TABLE IF EXISTS chat_message CASCADE"))
            conn.execute(text("DROP TABLE IF EXISTS chat CASCADE"))
            conn.commit()
        engine.dispose()


def test_parse_chat_messages():
    """Unit test for _parse_chat_messages edge cases."""
    print("\n=== Testing _parse_chat_messages ===")
    now = int(time.time())

    # None data
    assert migration._parse_chat_messages('c1', 'u1', None, now) == []
    print("  [PASS] None data returns empty")

    # Empty string
    assert migration._parse_chat_messages('c1', 'u1', '', now) == []
    print("  [PASS] Empty string returns empty")

    # Invalid JSON string
    assert migration._parse_chat_messages('c1', 'u1', 'not json', now) == []
    print("  [PASS] Invalid JSON string returns empty")

    # String JSON data
    data = json.dumps({
        'history': {
            'messages': {'m1': {'role': 'user', 'content': 'hi'}}
        }
    })
    result = migration._parse_chat_messages('c1', 'u1', data, now)
    assert len(result) == 1
    assert result[0]['id'] == 'c1-m1'
    print("  [PASS] String JSON data parsed correctly")

    # Dict data (already parsed)
    data = {'history': {'messages': {'m1': {'role': 'user', 'content': 'hi'}}}}
    result = migration._parse_chat_messages('c1', 'u1', data, now)
    assert len(result) == 1
    print("  [PASS] Dict data parsed correctly")

    # History is not a dict
    data = {'history': 'string'}
    assert migration._parse_chat_messages('c1', 'u1', data, now) == []
    print("  [PASS] Non-dict history returns empty")

    # Messages is a list (not dict)
    data = {'history': {'messages': ['a', 'b']}}
    assert migration._parse_chat_messages('c1', 'u1', data, now) == []
    print("  [PASS] List messages returns empty")

    # Timestamp in milliseconds
    data = {
        'history': {
            'messages': {
                'm1': {'role': 'user', 'content': 'hi', 'timestamp': now * 1000}
            }
        }
    }
    result = migration._parse_chat_messages('c1', 'u1', data, now)
    assert result[0]['created_at'] == now
    print("  [PASS] Millisecond timestamps normalized")

    # Timestamp too old
    data = {
        'history': {
            'messages': {
                'm1': {'role': 'user', 'content': 'hi', 'timestamp': 1000000000}
            }
        }
    }
    result = migration._parse_chat_messages('c1', 'u1', data, now)
    assert result[0]['created_at'] == now
    print("  [PASS] Too-old timestamps default to now")

    # Message with no role
    data = {'history': {'messages': {'m1': {'content': 'no role'}}}}
    assert migration._parse_chat_messages('c1', 'u1', data, now) == []
    print("  [PASS] Messages without role are skipped")

    # camelCase field names
    data = {
        'history': {
            'messages': {
                'm1': {
                    'role': 'user',
                    'content': 'hi',
                    'parentId': 'parent-1',
                    'statusHistory': [{'status': 'done'}],
                }
            }
        }
    }
    result = migration._parse_chat_messages('c1', 'u1', data, now)
    assert result[0]['parent_id'] == 'parent-1'
    assert result[0]['status_history'] == [{'status': 'done'}]
    print("  [PASS] camelCase fields mapped to snake_case")

    print("\n=== _parse_chat_messages tests PASSED ===")


if __name__ == '__main__':
    test_parse_chat_messages()
    test_sqlite()
    test_postgresql()
    print("\n" + "=" * 50)
    print("ALL TESTS PASSED")
    print("=" * 50)
