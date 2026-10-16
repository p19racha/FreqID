"""phase6_admin_and_devices

Revision ID: a1b2c3d4e5f6
Revises: 750c49748c60
Create Date: 2026-10-14 09:20:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: str | Sequence[str] | None = '750c49748c60'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create admin_users table
    op.create_table(
        'admin_users',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('username', sa.String(length=64), nullable=False),
        sa.Column('password_hash', sa.String(length=256), nullable=False),
        sa.Column('role', sa.String(length=32), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('failed_logins', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('totp_secret_enc', sa.String(length=256), nullable=True),
        sa.Column('totp_enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('owner', 'admin', 'operator', 'auditor')", name='check_admin_role'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_admin_users_username'), 'admin_users', ['username'], unique=True)
    op.create_index('idx_admin_users_role', 'admin_users', ['role'], unique=False)

    # 2. Create admin_refresh_tokens table
    op.create_table(
        'admin_refresh_tokens',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('admin_id', sa.UUID(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('family_id', sa.UUID(), nullable=False),
        sa.Column('is_revoked', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('user_agent', sa.String(length=256), nullable=True),
        sa.Column('ip_hash', sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(['admin_id'], ['admin_users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_admin_refresh_tokens_token_hash'), 'admin_refresh_tokens', ['token_hash'], unique=True)
    op.create_index(op.f('ix_admin_refresh_tokens_family_id'), 'admin_refresh_tokens', ['family_id'], unique=False)
    op.create_index(op.f('ix_admin_refresh_tokens_expires_at'), 'admin_refresh_tokens', ['expires_at'], unique=False)
    op.create_index(op.f('ix_admin_refresh_tokens_admin_id'), 'admin_refresh_tokens', ['admin_id'], unique=False)

    # 3. Create devices table
    op.create_table(
        'devices',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('location', sa.String(length=128), nullable=True),
        sa.Column('state', sa.String(length=32), nullable=False),
        sa.Column('scopes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('public_key', sa.String(length=128), nullable=False),
        sa.Column('key_id', sa.String(length=64), nullable=False),
        sa.Column('software_version', sa.String(length=64), nullable=True),
        sa.Column('approved_by', sa.UUID(), nullable=True),
        sa.Column('last_seen', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_ip_hash', sa.String(length=64), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revocation_reason', sa.String(length=256), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("state IN ('pending', 'active', 'suspended', 'revoked')", name='check_device_state'),
        sa.ForeignKeyConstraint(['approved_by'], ['admin_users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('public_key')
    )
    op.create_index(op.f('ix_devices_key_id'), 'devices', ['key_id'], unique=True)
    op.create_index('idx_devices_state', 'devices', ['state'], unique=False)

    # 4. Create pairing_tokens table
    op.create_table(
        'pairing_tokens',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('is_used', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('used_by_device_id', sa.UUID(), nullable=True),
        sa.Column('name_hint', sa.String(length=128), nullable=True),
        sa.Column('location_hint', sa.String(length=128), nullable=True),
        sa.Column('scopes_allowed', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['admin_users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['used_by_device_id'], ['devices.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_pairing_tokens_token_hash'), 'pairing_tokens', ['token_hash'], unique=True)
    op.create_index(op.f('ix_pairing_tokens_expires_at'), 'pairing_tokens', ['expires_at'], unique=False)

    # 5. Create device_heartbeats table
    op.create_table(
        'device_heartbeats',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('device_id', sa.UUID(), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('software_version', sa.String(length=64), nullable=True),
        sa.Column('camera_ok', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('uptime_seconds', sa.Float(), nullable=True),
        sa.Column('queued_payloads', sa.Integer(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['device_id'], ['devices.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_device_heartbeats_device_id'), 'device_heartbeats', ['device_id'], unique=False)
    op.create_index(op.f('ix_device_heartbeats_timestamp'), 'device_heartbeats', ['timestamp'], unique=False)

    # 6. Create system_settings table
    op.create_table(
        'system_settings',
        sa.Column('key', sa.String(length=64), nullable=False),
        sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('description', sa.String(length=256), nullable=True),
        sa.ForeignKeyConstraint(['updated_by'], ['admin_users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('key')
    )

    # 7. Migrate audit_events (convert string columns to UUID FKs)
    op.alter_column(
        'audit_events',
        'device_id',
        type_=sa.UUID(),
        postgresql_using="CASE WHEN device_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN device_id::uuid ELSE NULL END"
    )
    op.alter_column(
        'audit_events',
        'admin_id',
        type_=sa.UUID(),
        postgresql_using="CASE WHEN admin_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN admin_id::uuid ELSE NULL END"
    )
    # Clean orphan IDs in existing audit records before creating foreign key constraints
    op.execute("UPDATE audit_events SET device_id = NULL WHERE device_id IS NOT NULL AND device_id NOT IN (SELECT id FROM devices)")
    op.execute("UPDATE audit_events SET admin_id = NULL WHERE admin_id IS NOT NULL AND admin_id NOT IN (SELECT id FROM admin_users)")

    op.create_foreign_key(
        'fk_audit_events_device_id_devices',
        'audit_events',
        'devices',
        ['device_id'],
        ['id'],
        ondelete='SET NULL'
    )
    op.create_foreign_key(
        'fk_audit_events_admin_id_admin_users',
        'audit_events',
        'admin_users',
        ['admin_id'],
        ['id'],
        ondelete='SET NULL'
    )
    op.create_index('idx_audit_events_device_time', 'audit_events', ['device_id', 'event_time'], unique=False)
    op.create_index('idx_audit_events_admin_time', 'audit_events', ['admin_id', 'event_time'], unique=False)

    # 8. Migrate enrollment_sessions (convert string columns to UUID FKs)
    op.alter_column(
        'enrollment_sessions',
        'device_id',
        type_=sa.UUID(),
        postgresql_using="CASE WHEN device_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN device_id::uuid ELSE NULL END"
    )
    op.alter_column(
        'enrollment_sessions',
        'admin_id',
        type_=sa.UUID(),
        postgresql_using="CASE WHEN admin_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN admin_id::uuid ELSE NULL END"
    )
    # Clean orphan IDs in existing enrollment sessions before creating foreign key constraints
    op.execute("UPDATE enrollment_sessions SET device_id = NULL WHERE device_id IS NOT NULL AND device_id NOT IN (SELECT id FROM devices)")
    op.execute("UPDATE enrollment_sessions SET admin_id = NULL WHERE admin_id IS NOT NULL AND admin_id NOT IN (SELECT id FROM admin_users)")

    op.create_foreign_key(
        'fk_enrollment_sessions_device_id_devices',
        'enrollment_sessions',
        'devices',
        ['device_id'],
        ['id'],
        ondelete='SET NULL'
    )
    op.create_foreign_key(
        'fk_enrollment_sessions_admin_id_admin_users',
        'enrollment_sessions',
        'admin_users',
        ['admin_id'],
        ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    # 1. Revert enrollment_sessions FKs and column types
    op.drop_constraint('fk_enrollment_sessions_admin_id_admin_users', 'enrollment_sessions', type_='foreignkey')
    op.drop_constraint('fk_enrollment_sessions_device_id_devices', 'enrollment_sessions', type_='foreignkey')
    op.alter_column('enrollment_sessions', 'admin_id', type_=sa.String(length=128))
    op.alter_column('enrollment_sessions', 'device_id', type_=sa.String(length=128))

    # 2. Revert audit_events FKs, indexes and column types
    op.drop_index('idx_audit_events_admin_time', table_name='audit_events')
    op.drop_index('idx_audit_events_device_time', table_name='audit_events')
    op.drop_constraint('fk_audit_events_admin_id_admin_users', 'audit_events', type_='foreignkey')
    op.drop_constraint('fk_audit_events_device_id_devices', 'audit_events', type_='foreignkey')
    op.alter_column('audit_events', 'admin_id', type_=sa.String(length=128))
    op.alter_column('audit_events', 'device_id', type_=sa.String(length=128))

    # 3. Drop tables in reverse order
    op.drop_table('system_settings')
    op.drop_index(op.f('ix_device_heartbeats_timestamp'), table_name='device_heartbeats')
    op.drop_index(op.f('ix_device_heartbeats_device_id'), table_name='device_heartbeats')
    op.drop_table('device_heartbeats')
    op.drop_index(op.f('ix_pairing_tokens_expires_at'), table_name='pairing_tokens')
    op.drop_index(op.f('ix_pairing_tokens_token_hash'), table_name='pairing_tokens')
    op.drop_table('pairing_tokens')
    op.drop_index('idx_devices_state', table_name='devices')
    op.drop_index(op.f('ix_devices_key_id'), table_name='devices')
    op.drop_table('devices')
    op.drop_index(op.f('ix_admin_refresh_tokens_admin_id'), table_name='admin_refresh_tokens')
    op.drop_index(op.f('ix_admin_refresh_tokens_expires_at'), table_name='admin_refresh_tokens')
    op.drop_index(op.f('ix_admin_refresh_tokens_family_id'), table_name='admin_refresh_tokens')
    op.drop_index(op.f('ix_admin_refresh_tokens_token_hash'), table_name='admin_refresh_tokens')
    op.drop_table('admin_refresh_tokens')
    op.drop_index('idx_admin_users_role', table_name='admin_users')
    op.drop_index(op.f('ix_admin_users_username'), table_name='admin_users')
    op.drop_table('admin_users')
