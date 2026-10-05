import sqlalchemy as sa
from alembic import op

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('chat_rooms',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('direct_key', sa.String(length=64), nullable=True),
    sa.Column('roles', sa.JSON(), nullable=False),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('last_message_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('direct_key')
    )
    with op.batch_alter_table('chat_rooms', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_chat_rooms_last_message_at'), ['last_message_at'], unique=False)

    op.create_table('chat_members',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('room_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('is_admin', sa.Boolean(), nullable=False),
    sa.Column('via_role', sa.String(length=64), nullable=False),
    sa.Column('last_read_id', sa.Integer(), nullable=False),
    sa.Column('muted', sa.Boolean(), nullable=False),
    sa.Column('joined_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['room_id'], ['chat_rooms.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('room_id', 'user_id', name='uq_chat_members_room_user')
    )
    with op.batch_alter_table('chat_members', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_chat_members_room_id'), ['room_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_chat_members_user_id'), ['user_id'], unique=False)

    op.create_table('chat_messages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('room_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('data', sa.JSON(), nullable=False),
    sa.Column('event_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('edited_at', sa.DateTime(), nullable=True),
    sa.Column('deleted', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['event_id'], ['events.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['room_id'], ['chat_rooms.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('chat_messages', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_chat_messages_created_at'), ['created_at'], unique=False)
        batch_op.create_index('ix_chat_messages_room', ['room_id', 'id'], unique=False)

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('chat_telegram', sa.Boolean(), server_default=sa.true(), nullable=False))



def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('chat_telegram')

    with op.batch_alter_table('chat_messages', schema=None) as batch_op:
        batch_op.drop_index('ix_chat_messages_room')
        batch_op.drop_index(batch_op.f('ix_chat_messages_created_at'))

    op.drop_table('chat_messages')
    with op.batch_alter_table('chat_members', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_chat_members_user_id'))
        batch_op.drop_index(batch_op.f('ix_chat_members_room_id'))

    op.drop_table('chat_members')
    with op.batch_alter_table('chat_rooms', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_chat_rooms_last_message_at'))

    op.drop_table('chat_rooms')
