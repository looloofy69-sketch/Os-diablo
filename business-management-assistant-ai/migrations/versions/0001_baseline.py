"""Baseline: the 0.4 schema.

Fresh databases get every table from the current models. Databases created by the application itself (sandbox
auto-create) already match this revision: mark them with ``alembic stamp head``. From the next revision on,
migrations must be written explicitly (``alembic revision --autogenerate`` and review the output); never edit
this file once released.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlmodel import SQLModel

from app.core import SCHEMA_VERSION
from app.domain import chat_models, models  # noqa: F401

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    SQLModel.metadata.create_all(bind)  # checkfirst: a no-op for tables that already exist
    bind.execute(
        sa.text("INSERT INTO schemameta (key, value) SELECT 'schema_version', :v WHERE NOT EXISTS (SELECT 1 FROM schemameta WHERE key = 'schema_version')"),
        {"v": SCHEMA_VERSION},
    )


def downgrade() -> None:
    SQLModel.metadata.drop_all(op.get_bind())
