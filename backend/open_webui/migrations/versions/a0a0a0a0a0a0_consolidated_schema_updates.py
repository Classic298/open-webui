"""Consolidated schema updates post af906e964978

Revision ID: a0a0a0a0a0a0
Revises: af906e964978
Create Date: 2024-07-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a0a0a0a0a0a0'
down_revision: Union[str, None] = 'af906e964978' # Parent is af906e964978_add_feedback_table.py
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    print("Applying consolidated_001 (a0a0a0a0a0a0): Starting schema updates.")

    # From 4ace53fd72c8_update_folder_table_datetime.py
    print("Consolidated: Applying changes from 4ace53fd72c8 (folder datetime to BigInt)")
    with op.batch_alter_table("folder", schema=None) as batch_op:
        batch_op.alter_column("created_at", server_default=None)
        batch_op.alter_column("updated_at", server_default=None)
        batch_op.alter_column(
            "created_at",
            type_=sa.BigInteger(),
            existing_type=sa.DateTime(),
            existing_nullable=False, # Assuming it was not nullable from c69f45358db4
            postgresql_using="extract(epoch from created_at)::bigint",
        )
        batch_op.alter_column(
            "updated_at",
            type_=sa.BigInteger(),
            existing_type=sa.DateTime(),
            existing_nullable=False, # Assuming it was not nullable from c69f45358db4
            postgresql_using="extract(epoch from updated_at)::bigint",
        )

    # From f2c1a0b3d4e5_add_system_prompt_and_emoji_to_folder.py
    print("Consolidated: Applying changes from f2c1a0b3d4e5 (folder system_prompt, emoji)")
    op.add_column('folder', sa.Column('system_prompt', sa.Text(), nullable=True))
    op.add_column('folder', sa.Column('emoji', sa.Text(), nullable=True))

    # From 922e7a387820_add_group_table.py
    print("Consolidated: Applying changes from 922e7a387820 (group table, model/knowledge/prompt/tool access_control)")
    op.create_table(
        "group",
        sa.Column("id", sa.Text(), nullable=False, primary_key=True, unique=True),
        sa.Column("user_id", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("permissions", sa.JSON(), nullable=True),
        sa.Column("user_ids", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", sa.BigInteger(), nullable=True),
    )
    op.add_column("model", sa.Column("access_control", sa.JSON(), nullable=True))
    op.add_column("model", sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.sql.expression.true())) # Made nullable=True for safety, original was False
    op.add_column("knowledge", sa.Column("access_control", sa.JSON(), nullable=True))
    op.add_column("prompt", sa.Column("access_control", sa.JSON(), nullable=True))
    op.add_column("tool", sa.Column("access_control", sa.JSON(), nullable=True))

    # From 57c599a3cb57_add_channel_table.py
    print("Consolidated: Applying changes from 57c599a3cb57 (channel, message tables)")
    op.create_table(
        "channel",
        sa.Column("id", sa.Text(), nullable=False, primary_key=True, unique=True),
        sa.Column("user_id", sa.Text()),
        sa.Column("name", sa.Text()),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("access_control", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", sa.BigInteger(), nullable=True),
    )
    op.create_table(
        "message",
        sa.Column("id", sa.Text(), nullable=False, primary_key=True, unique=True),
        sa.Column("user_id", sa.Text()),
        sa.Column("channel_id", sa.Text(), nullable=True),
        sa.Column("content", sa.Text()),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", sa.BigInteger(), nullable=True),
    )

    # From 7826ab40b532_update_file_table.py
    print("Consolidated: Applying changes from 7826ab40b532 (file access_control)")
    op.add_column("file", sa.Column("access_control", sa.JSON(), nullable=True))

    # From 3781e22d8b01_update_message_table.py
    print("Consolidated: Applying changes from 3781e22d8b01 (channel type, message parent_id, message_reaction, channel_member tables)")
    op.add_column("channel", sa.Column("type", sa.Text(), nullable=True))
    op.add_column("message", sa.Column("parent_id", sa.Text(), nullable=True))
    op.create_table(
        "message_reaction",
        sa.Column("id", sa.Text(), nullable=False, primary_key=True, unique=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("message_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=True),
    )
    op.create_table(
        "channel_member",
        sa.Column("id", sa.Text(), nullable=False, primary_key=True, unique=True),
        sa.Column("channel_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=True),
    )

    # From 9f0c9cd09105_add_note_table.py
    print("Consolidated: Applying changes from 9f0c9cd09105 (note table)")
    op.create_table(
        "note",
        sa.Column("id", sa.Text(), nullable=False, primary_key=True, unique=True),
        sa.Column("user_id", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("access_control", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", sa.BigInteger(), nullable=True),
    )
    print("Consolidated_001 (a0a0a0a0a0a0): Schema updates complete.")


def downgrade() -> None:
    print("Consolidated_001 (a0a0a0a0a0a0): Starting schema downgrade.")

    # Reverse 9f0c9cd09105_add_note_table.py
    print("Consolidated: Downgrading changes from 9f0c9cd09105 (note table)")
    op.drop_table("note")

    # Reverse 3781e22d8b01_update_message_table.py
    print("Consolidated: Downgrading changes from 3781e22d8b01 (channel type, message parent_id, message_reaction, channel_member tables)")
    op.drop_table("channel_member")
    op.drop_table("message_reaction")
    op.drop_column("message", "parent_id")
    op.drop_column("channel", "type")

    # Reverse 7826ab40b532_update_file_table.py
    print("Consolidated: Downgrading changes from 7826ab40b532 (file access_control)")
    op.drop_column("file", "access_control")

    # Reverse 57c599a3cb57_add_channel_table.py
    print("Consolidated: Downgrading changes from 57c599a3cb57 (channel, message tables)")
    op.drop_table("message")
    op.drop_table("channel")

    # Reverse 922e7a387820_add_group_table.py
    print("Consolidated: Downgrading changes from 922e7a387820 (group table, model/knowledge/prompt/tool access_control)")
    op.drop_column("tool", "access_control")
    op.drop_column("prompt", "access_control")
    op.drop_column("knowledge", "access_control")
    op.drop_column("model", "is_active")
    op.drop_column("model", "access_control")
    op.drop_table("group")

    # Reverse f2c1a0b3d4e5_add_system_prompt_and_emoji_to_folder.py
    print("Consolidated: Downgrading changes from f2c1a0b3d4e5 (folder system_prompt, emoji)")
    op.drop_column('folder', 'emoji')
    op.drop_column('folder', 'system_prompt')

    # Reverse 4ace53fd72c8_update_folder_table_datetime.py
    print("Consolidated: Downgrading changes from 4ace53fd72c8 (folder datetime to BigInt)")
    with op.batch_alter_table("folder", schema=None) as batch_op:
        batch_op.alter_column(
            "created_at",
            type_=sa.DateTime(),
            existing_type=sa.BigInteger(),
            existing_nullable=False, # Assuming it was not nullable from c69f45358db4
            server_default=sa.func.now(),
        )
        batch_op.alter_column(
            "updated_at",
            type_=sa.DateTime(),
            existing_type=sa.BigInteger(),
            existing_nullable=False, # Assuming it was not nullable from c69f45358db4
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        )
    print("Consolidated_001 (a0a0a0a0a0a0): Schema downgrade complete.")
