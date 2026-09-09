"""t10b/t11b: diagnosis_reports + path_decisions

Revision ID: b2c7a91d4e50
Revises: 3f3a318f15d5
Create Date: 2026-09-09 10:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c7a91d4e50'
down_revision: Union[str, None] = '3f3a318f15d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'diagnosis_reports',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('student_id', sa.String(length=36), nullable=False),
        sa.Column('goal_id', sa.String(length=36), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('planner_source', sa.String(length=20), nullable=False),
        sa.Column('model_id', sa.String(length=80), nullable=True),
        sa.Column('fallback_reason', sa.String(length=160), nullable=True),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('observations', sa.JSON(), nullable=False),
        sa.Column('hypotheses', sa.JSON(), nullable=False),
        sa.Column('recommended_probe', sa.JSON(), nullable=False),
        sa.Column('evidence_ids', sa.JSON(), nullable=False),
        sa.Column('input_state', sa.JSON(), nullable=False),
        sa.Column('duration_ms', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['student_id'], ['students.id'], ),
        sa.ForeignKeyConstraint(['goal_id'], ['goals.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_diagnosis_reports_student_id'), 'diagnosis_reports', ['student_id'], unique=False)
    op.create_index(op.f('ix_diagnosis_reports_goal_id'), 'diagnosis_reports', ['goal_id'], unique=False)

    op.create_table(
        'path_decisions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('student_id', sa.String(length=36), nullable=False),
        sa.Column('goal_id', sa.String(length=36), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('candidate_actions', sa.JSON(), nullable=False),
        sa.Column('selected_action', sa.JSON(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('evidence_ids', sa.JSON(), nullable=False),
        sa.Column('policy_version', sa.String(length=20), nullable=False),
        sa.Column('planner_source', sa.String(length=20), nullable=False),
        sa.Column('model_id', sa.String(length=80), nullable=True),
        sa.Column('fallback_reason', sa.String(length=160), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=False),
        sa.Column('plan_version_before', sa.Integer(), nullable=False),
        sa.Column('plan_version_after', sa.Integer(), nullable=False),
        sa.Column('changed', sa.Boolean(), nullable=False),
        sa.Column('input_state_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['student_id'], ['students.id'], ),
        sa.ForeignKeyConstraint(['goal_id'], ['goals.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_path_decisions_student_id'), 'path_decisions', ['student_id'], unique=False)
    op.create_index(op.f('ix_path_decisions_goal_id'), 'path_decisions', ['goal_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_path_decisions_goal_id'), table_name='path_decisions')
    op.drop_index(op.f('ix_path_decisions_student_id'), table_name='path_decisions')
    op.drop_table('path_decisions')
    op.drop_index(op.f('ix_diagnosis_reports_goal_id'), table_name='diagnosis_reports')
    op.drop_index(op.f('ix_diagnosis_reports_student_id'), table_name='diagnosis_reports')
    op.drop_table('diagnosis_reports')
