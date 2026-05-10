"""Initial migration for Open Omniscience.

Revision ID: 0001
Revises:
Create Date: 2026-05-07 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0001'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # Create sources table
    op.create_table(
        'sources',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('domain', sa.String(length=255), nullable=False, unique=True),
        sa.Column('rss_url', sa.String(length=500), nullable=True),
        sa.Column('rate_limit_ms', sa.Integer(), nullable=True, default=2000),
        sa.Column('enabled', sa.Boolean(), nullable=True, default=True),
        sa.Column('priority', sa.Integer(), nullable=True, default=2),
        sa.Column('tags', sa.String(length=500), nullable=True),
    )

    # Create articles table
    op.create_table(
        'articles',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('url', sa.String(length=1000), nullable=False),
        sa.Column('canonical_url', sa.String(length=1000), nullable=False),
        sa.Column('source_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('published_at', sa.DateTime(), nullable=True),
        sa.Column('language', sa.String(length=10), nullable=True),
        sa.Column('hash', sa.String(length=64), nullable=False, unique=True),
        sa.Column('created_at', sa.DateTime(), nullable=True, default=sa.func.now()),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
    )

    # Create indexes
    op.create_index(op.f('idx_article_hash'), 'articles', ['hash'], unique=True)
    op.create_index(op.f('idx_article_canonical_url'), 'articles', ['canonical_url'])
    op.create_index(op.f('idx_article_source_id'), 'articles', ['source_id'])
    op.create_index(op.f('idx_article_content'), 'articles', ['content'])

def downgrade():
    # Drop indexes
    op.drop_index(op.f('idx_article_content'), table_name='articles')
    op.drop_index(op.f('idx_article_source_id'), table_name='articles')
    op.drop_index(op.f('idx_article_canonical_url'), table_name='articles')
    op.drop_index(op.f('idx_article_hash'), table_name='articles')

    # Drop tables
    op.drop_table('articles')
    op.drop_table('sources')
