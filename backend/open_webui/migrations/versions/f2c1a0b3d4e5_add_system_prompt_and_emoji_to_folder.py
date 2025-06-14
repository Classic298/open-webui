"""add_system_prompt_and_emoji_to_folder

Revision ID: f2c1a0b3d4e5
Revises: 4ace53fd72c8
Create Date: 2024-07-10 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2c1a0b3d4e5'
down_revision: Union[str, None] = '4ace53fd72c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('folder', sa.Column('system_prompt', sa.Text(), nullable=True))
    op.add_column('folder', sa.Column('emoji', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('folder', 'emoji')
    op.drop_column('folder', 'system_prompt')
