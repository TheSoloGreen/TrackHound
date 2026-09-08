"""Frozen schema for unversioned releases through September 2026. Do not edit."""

import sqlalchemy as sa

metadata = sa.MetaData()

sa.Table('users', metadata,
    sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
    sa.Column('plex_user_id', sa.String(255), nullable=False, unique=True),
    sa.Column('plex_username', sa.String(255), nullable=False),
    sa.Column('plex_email', sa.String(255), nullable=True),
    sa.Column('plex_token', sa.Text(), nullable=False),
    sa.Column('plex_thumb_url', sa.String(512), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('last_login', sa.DateTime(), nullable=False),
)

sa.Table('scan_locations', metadata,
    sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
    sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
    sa.Column('path', sa.String(1024), nullable=False),
    sa.Column('label', sa.String(255), nullable=False),
    sa.Column('media_type', sa.String(20), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('last_scanned', sa.DateTime(), nullable=True),
    sa.Column('file_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
)

sa.Table('shows', metadata,
    sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
    sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
    sa.Column('title', sa.String(512), nullable=False),
    sa.Column('media_type', sa.String(20), nullable=False),
    sa.Column('plex_key', sa.String(255), nullable=True),
    sa.Column('plex_rating_key', sa.String(255), nullable=True),
    sa.Column('is_anime', sa.Boolean(), nullable=False),
    sa.Column('anime_source', sa.String(50), nullable=True),
    sa.Column('thumb_url', sa.String(512), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
)

sa.Table('user_preferences', metadata,
    sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
    sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
    sa.Column('key', sa.String(255), nullable=False),
    sa.Column('value', sa.Text(), nullable=False),
)

sa.Table('seasons', metadata,
    sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
    sa.Column('show_id', sa.Integer(), sa.ForeignKey('shows.id', ondelete='CASCADE'), nullable=False),
    sa.Column('season_number', sa.Integer(), nullable=False),
    sa.Column('plex_key', sa.String(255), nullable=True),
    sa.Column('plex_rating_key', sa.String(255), nullable=True),
)

sa.Table('media_files', metadata,
    sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
    sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
    sa.Column('show_id', sa.Integer(), sa.ForeignKey('shows.id', ondelete='SET NULL'), nullable=True),
    sa.Column('season_id', sa.Integer(), sa.ForeignKey('seasons.id', ondelete='SET NULL'), nullable=True),
    sa.Column('file_path', sa.String(1024), nullable=False, unique=True),
    sa.Column('filename', sa.String(512), nullable=False),
    sa.Column('episode_number', sa.Integer(), nullable=True),
    sa.Column('episode_title', sa.String(512), nullable=True),
    sa.Column('file_size', sa.BigInteger(), nullable=False),
    sa.Column('container_format', sa.String(50), nullable=True),
    sa.Column('duration_ms', sa.BigInteger(), nullable=True),
    sa.Column('last_scanned', sa.DateTime(), nullable=False),
    sa.Column('last_modified', sa.DateTime(), nullable=False),
    sa.Column('has_issues', sa.Boolean(), nullable=False),
    sa.Column('issue_details', sa.Text(), nullable=True),
)

sa.Table('audio_tracks', metadata,
    sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
    sa.Column('media_file_id', sa.Integer(), sa.ForeignKey('media_files.id', ondelete='CASCADE'), nullable=False),
    sa.Column('track_index', sa.Integer(), nullable=False),
    sa.Column('language', sa.String(50), nullable=True),
    sa.Column('language_raw', sa.String(100), nullable=True),
    sa.Column('codec', sa.String(50), nullable=True),
    sa.Column('channels', sa.Integer(), nullable=True),
    sa.Column('channel_layout', sa.String(50), nullable=True),
    sa.Column('bitrate', sa.Integer(), nullable=True),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('is_forced', sa.Boolean(), nullable=False),
    sa.Column('title', sa.String(255), nullable=True),
)
