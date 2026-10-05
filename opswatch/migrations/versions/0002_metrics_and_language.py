import sqlalchemy as sa
from alembic import op

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('metric_points',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('value', sa.Float(), nullable=False),
    sa.Column('ts', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('metric_points', schema=None) as batch_op:
        batch_op.create_index('ix_metric_points_series', ['source_id', 'name', 'ts'], unique=False)
        batch_op.create_index(batch_op.f('ix_metric_points_ts'), ['ts'], unique=False)

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('language', sa.String(length=8), server_default='ru', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('language')

    with op.batch_alter_table('metric_points', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_metric_points_ts'))
        batch_op.drop_index('ix_metric_points_series')

    op.drop_table('metric_points')
