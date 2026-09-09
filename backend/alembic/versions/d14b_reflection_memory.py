"""T14-B reflection snapshots and versioned memory facts."""
from alembic import op
import sqlalchemy as sa
revision='d14b_reflection_memory'; down_revision='c3d8e52f71ab'; branch_labels=None; depends_on=None
def upgrade():
    for name, typ in [('course_id',sa.String(40)),('concept_id',sa.String(40)),('version',sa.Integer()),('supersedes_id',sa.String(36)),('source_session_id',sa.String(36))]:
        op.add_column('memory_facts',sa.Column(name,typ,nullable=True))
    op.create_table('learning_reflections',sa.Column('id',sa.String(36),primary_key=True),sa.Column('student_id',sa.String(36),nullable=False),sa.Column('course_id',sa.String(40),nullable=False),sa.Column('session_id',sa.String(36),nullable=False),sa.Column('planner_source',sa.String(30),nullable=False),sa.Column('fallback_reason',sa.String(160)),sa.Column('learned',sa.JSON(),nullable=False),sa.Column('still_uncertain',sa.JSON(),nullable=False),sa.Column('evidence_summary',sa.JSON(),nullable=False),sa.Column('next_recommendation',sa.JSON(),nullable=False),sa.Column('learning_characteristics',sa.JSON(),nullable=False),sa.Column('created_at',sa.DateTime(),nullable=False))
def downgrade(): op.drop_table('learning_reflections')
