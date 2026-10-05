import sqlalchemy as sa
from alembic import op

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('roles',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('permissions', sa.JSON(), nullable=False),
    sa.Column('builtin', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('rules',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('categories', sa.JSON(), nullable=False),
    sa.Column('source_ids', sa.JSON(), nullable=False),
    sa.Column('event_types', sa.JSON(), nullable=False),
    sa.Column('min_severity', sa.String(length=16), nullable=False),
    sa.Column('target_roles', sa.JSON(), nullable=False),
    sa.Column('target_users', sa.JSON(), nullable=False),
    sa.Column('escalate_after_min', sa.Integer(), nullable=False),
    sa.Column('escalate_roles', sa.JSON(), nullable=False),
    sa.Column('escalate_users', sa.JSON(), nullable=False),
    sa.Column('stop', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('settings',
    sa.Column('key', sa.String(length=100), nullable=False),
    sa.Column('value', sa.JSON(), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('sources',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('type', sa.String(length=64), nullable=False),
    sa.Column('category', sa.String(length=32), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('config', sa.JSON(), nullable=False),
    sa.Column('secrets', sa.Text(), nullable=False),
    sa.Column('poll_interval', sa.Integer(), nullable=False),
    sa.Column('visible_roles', sa.JSON(), nullable=False),
    sa.Column('ingest_token', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('last_check_at', sa.DateTime(), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=False),
    sa.Column('metrics', sa.JSON(), nullable=False),
    sa.Column('state', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ingest_token')
    )
    with op.batch_alter_table('sources', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_sources_type'), ['type'], unique=False)

    op.create_table('backup_jobs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('source_id', sa.Integer(), nullable=True),
    sa.Column('schedule', sa.String(length=100), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('keep_last', sa.Integer(), nullable=False),
    sa.Column('encrypt', sa.Boolean(), nullable=False),
    sa.Column('password', sa.Text(), nullable=False),
    sa.Column('options', sa.JSON(), nullable=False),
    sa.Column('destinations', sa.JSON(), nullable=False),
    sa.Column('last_run_at', sa.DateTime(), nullable=True),
    sa.Column('last_status', sa.String(length=16), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('password_hash', sa.String(length=300), nullable=False),
    sa.Column('full_name', sa.String(length=200), nullable=False),
    sa.Column('email', sa.String(length=200), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('is_superuser', sa.Boolean(), nullable=False),
    sa.Column('role_id', sa.Integer(), nullable=True),
    sa.Column('telegram_username', sa.String(length=100), nullable=False),
    sa.Column('telegram_chat_id', sa.BigInteger(), nullable=True),
    sa.Column('telegram_link_code', sa.String(length=32), nullable=True),
    sa.Column('telegram_link_expires', sa.DateTime(), nullable=True),
    sa.Column('personal_bot_token', sa.Text(), nullable=True),
    sa.Column('personal_bot_username', sa.String(length=100), nullable=False),
    sa.Column('personal_chat_id', sa.BigInteger(), nullable=True),
    sa.Column('notify_telegram', sa.Boolean(), nullable=False),
    sa.Column('notify_desktop', sa.Boolean(), nullable=False),
    sa.Column('quiet_start', sa.String(length=5), nullable=False),
    sa.Column('quiet_end', sa.String(length=5), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('last_login_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_users_telegram_chat_id'), ['telegram_chat_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_users_telegram_link_code'), ['telegram_link_code'], unique=False)
        batch_op.create_index(batch_op.f('ix_users_username'), ['username'], unique=True)

    op.create_table('auth_sessions',
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('client', sa.String(length=300), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('token_hash')
    )
    with op.batch_alter_table('auth_sessions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_auth_sessions_user_id'), ['user_id'], unique=False)

    op.create_table('backup_records',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('job_id', sa.Integer(), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=False),
    sa.Column('finished_at', sa.DateTime(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('manual', sa.Boolean(), nullable=False),
    sa.Column('file_path', sa.Text(), nullable=False),
    sa.Column('size', sa.BigInteger(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('verified', sa.Boolean(), nullable=False),
    sa.Column('delivery', sa.JSON(), nullable=False),
    sa.Column('error', sa.Text(), nullable=False),
    sa.Column('deleted', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['backup_jobs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('backup_records', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_backup_records_job_id'), ['job_id'], unique=False)

    op.create_table('events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(), nullable=False),
    sa.Column('source_id', sa.Integer(), nullable=True),
    sa.Column('source_name', sa.String(length=200), nullable=False),
    sa.Column('category', sa.String(length=32), nullable=False),
    sa.Column('type', sa.String(length=100), nullable=False),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('title', sa.String(length=500), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('details', sa.JSON(), nullable=False),
    sa.Column('fingerprint', sa.String(length=64), nullable=False),
    sa.Column('external_id', sa.String(length=200), nullable=True),
    sa.Column('count', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('reporter_id', sa.Integer(), nullable=True),
    sa.Column('acked_by_id', sa.Integer(), nullable=True),
    sa.Column('acked_at', sa.DateTime(), nullable=True),
    sa.Column('resolved_by_id', sa.Integer(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(), nullable=True),
    sa.Column('resolution', sa.Text(), nullable=False),
    sa.Column('notified_at', sa.DateTime(), nullable=True),
    sa.Column('escalation', sa.JSON(), nullable=False),
    sa.Column('escalation_level', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['acked_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['reporter_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['resolved_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_events_category'), ['category'], unique=False)
        batch_op.create_index(batch_op.f('ix_events_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_events_external_id'), ['external_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_events_fingerprint'), ['fingerprint'], unique=False)
        batch_op.create_index(batch_op.f('ix_events_last_seen_at'), ['last_seen_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_events_severity'), ['severity'], unique=False)
        batch_op.create_index(batch_op.f('ix_events_source_id'), ['source_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_events_status'), ['status'], unique=False)

    op.create_table('subscriptions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('category', sa.String(length=32), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('min_severity', sa.String(length=16), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('subscriptions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_subscriptions_user_id'), ['user_id'], unique=False)

    op.create_table('attachments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('event_id', sa.Integer(), nullable=False),
    sa.Column('filename', sa.String(length=300), nullable=False),
    sa.Column('stored_name', sa.String(length=300), nullable=False),
    sa.Column('content_type', sa.String(length=100), nullable=False),
    sa.Column('size', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['event_id'], ['events.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('attachments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_attachments_event_id'), ['event_id'], unique=False)

    op.create_table('notifications',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('event_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('title', sa.String(length=500), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('category', sa.String(length=32), nullable=False),
    sa.Column('is_read', sa.Boolean(), nullable=False),
    sa.Column('telegram_status', sa.String(length=16), nullable=False),
    sa.Column('telegram_chat_id', sa.BigInteger(), nullable=True),
    sa.Column('telegram_message_id', sa.BigInteger(), nullable=True),
    sa.Column('telegram_via_personal', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['event_id'], ['events.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_notifications_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_notifications_event_id'), ['event_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_notifications_is_read'), ['is_read'], unique=False)
        batch_op.create_index(batch_op.f('ix_notifications_user_id'), ['user_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_notifications_user_id'))
        batch_op.drop_index(batch_op.f('ix_notifications_is_read'))
        batch_op.drop_index(batch_op.f('ix_notifications_event_id'))
        batch_op.drop_index(batch_op.f('ix_notifications_created_at'))

    op.drop_table('notifications')
    with op.batch_alter_table('attachments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_attachments_event_id'))

    op.drop_table('attachments')
    with op.batch_alter_table('subscriptions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_subscriptions_user_id'))

    op.drop_table('subscriptions')
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_events_status'))
        batch_op.drop_index(batch_op.f('ix_events_source_id'))
        batch_op.drop_index(batch_op.f('ix_events_severity'))
        batch_op.drop_index(batch_op.f('ix_events_last_seen_at'))
        batch_op.drop_index(batch_op.f('ix_events_fingerprint'))
        batch_op.drop_index(batch_op.f('ix_events_external_id'))
        batch_op.drop_index(batch_op.f('ix_events_created_at'))
        batch_op.drop_index(batch_op.f('ix_events_category'))

    op.drop_table('events')
    with op.batch_alter_table('backup_records', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_backup_records_job_id'))

    op.drop_table('backup_records')
    with op.batch_alter_table('auth_sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_auth_sessions_user_id'))

    op.drop_table('auth_sessions')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_username'))
        batch_op.drop_index(batch_op.f('ix_users_telegram_link_code'))
        batch_op.drop_index(batch_op.f('ix_users_telegram_chat_id'))
        batch_op.drop_index(batch_op.f('ix_users_status'))

    op.drop_table('users')
    op.drop_table('backup_jobs')
    with op.batch_alter_table('sources', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sources_type'))

    op.drop_table('sources')
    op.drop_table('settings')
    op.drop_table('rules')
    op.drop_table('roles')
