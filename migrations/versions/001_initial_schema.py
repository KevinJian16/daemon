"""Initial daemon schema.

Revision ID: 001
Revises: None
Create Date: 2026-03-13
"""
from typing import Sequence, Union
from pathlib import Path

from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    sql_path = Path(__file__).parent.parent / "001_initial_schema.sql"
    sql = sql_path.read_text()
    op.execute(sql)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS conversation_decisions CASCADE")
    op.execute("DROP TABLE IF EXISTS conversation_digests CASCADE")
    op.execute("DROP TABLE IF EXISTS conversation_messages CASCADE")
    op.execute("DROP TABLE IF EXISTS event_log CASCADE")
    op.execute("DROP TABLE IF EXISTS knowledge_cache CASCADE")
    op.execute("DROP TABLE IF EXISTS job_artifacts CASCADE")
    op.execute("DROP TABLE IF EXISTS job_steps CASCADE")
    op.execute("DROP TABLE IF EXISTS jobs CASCADE")
    op.execute("DROP TABLE IF EXISTS daemon_tasks CASCADE")
    op.execute("DROP FUNCTION IF EXISTS notify_event_bus CASCADE")
