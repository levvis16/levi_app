"""fix dialog created_at

Revision ID: a85be5b0590e
Revises: b2f93819437e
Create Date: 2026-05-16 21:01:51.990689

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a85be5b0590e'
down_revision: Union[str, Sequence[str], None] = 'b2f93819437e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.alter_column('dialogs', 'created_at',
                    server_default=sa.text('now()'),
                    existing_nullable=False)


def downgrade():
    op.alter_column('dialogs', 'created_at',
                    server_default=None,
                    existing_nullable=False)