"""t13b: rag_traces

Revision ID: c3d8e52f71ab
Revises: b2c7a91d4e50
Create Date: 2026-09-09 11:30:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d8e52f71ab'
down_revision: Union[str, None] = 'b2c7a91d4e50'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'rag_traces',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('student_id', sa.String(length=36), nullable=False),
        sa.Column('raw_query', sa.Text(), nullable=False),
        sa.Column('rewritten_query', sa.Text(), nullable=False),
        sa.Column('filters', sa.JSON(), nullable=False),
        sa.Column('index_version', sa.String(length=32), nullable=False),
        sa.Column('candidates', sa.JSON(), nullable=False),
        sa.Column('reranked', sa.JSON(), nullable=False),
        sa.Column('final_sources', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('safe_message', sa.Text(), nullable=True),
        sa.Column('planner_source', sa.String(length=20), nullable=False),
        sa.Column('model_id', sa.String(length=80), nullable=True),
        sa.Column('fallback_reason', sa.String(length=200), nullable=True),
        sa.Column('flags', sa.JSON(), nullable=False),
        sa.Column('duration_ms', sa.Integer(), nullable=False),
        sa.Column('concept_id', sa.String(length=40), nullable=True),
        sa.Column('exercise_id', sa.String(length=36), nullable=True),
        sa.Column('content_type', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_rag_traces_student_id'), 'rag_traces', ['student_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_rag_traces_student_id'), table_name='rag_traces')
    op.drop_table('rag_traces')
