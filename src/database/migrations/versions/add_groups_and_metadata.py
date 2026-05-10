"""Add Source Groups and Metadata

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-09 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    # Create source_groups table
    op.create_table(
        "source_groups",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("color", sa.String(length=20), nullable=True, default="#666666"),
        sa.Column("is_tag_based", sa.Boolean(), nullable=True, default=False),
        sa.Column("tag_pattern", sa.String(length=500), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=True, default=2),
        sa.Column("rate_limit_ms", sa.Integer(), nullable=True, default=2000),
        sa.Column("enabled", sa.Boolean(), nullable=True, default=True),
        sa.Column("created_at", sa.DateTime(), nullable=True, default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=True, default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint("name"),
    )
    print("source_groups table created")

    # Create source_metadata table
    op.create_table(
        "source_metadata",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("source_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("language", sa.String(length=20), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=True),
        sa.Column("region", sa.String(length=100), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("timezone", sa.String(length=50), nullable=True),
        sa.Column("robots_txt_url", sa.String(length=500), nullable=True),
        sa.Column("robots_allowed", sa.Boolean(), nullable=True, default=True),
        sa.Column("crawl_delay", sa.Integer(), nullable=True),
        sa.Column("sitemap_url", sa.String(length=500), nullable=True),
        sa.Column("favicon_url", sa.String(length=500), nullable=True),
        sa.Column("logo_url", sa.String(length=500), nullable=True),
        sa.Column("contact_email", sa.String(length=255), nullable=True),
        sa.Column("social_twitter", sa.String(length=255), nullable=True),
        sa.Column("social_facebook", sa.String(length=500), nullable=True),
        sa.Column("social_linkedin", sa.String(length=500), nullable=True),
        sa.Column("alexa_rank", sa.Integer(), nullable=True),
        sa.Column("last_checked", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
    )
    print("source_metadata table created")

    # Create source_group_association table
    op.create_table(
        "source_group_association",
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("added_at", sa.DateTime(), nullable=True, default=sa.func.now()),
        sa.PrimaryKeyConstraint("source_id", "group_id"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.ForeignKeyConstraint(["group_id"], ["source_groups.id"]),
    )
    print("source_group_association table created")

    # Create indexes for source_metadata
    op.create_index(op.f("idx_metadata_source_id"), "source_metadata", ["source_id"], unique=True)
    op.create_index(op.f("idx_metadata_country"), "source_metadata", ["country"])
    op.create_index(op.f("idx_metadata_language"), "source_metadata", ["language"])
    op.create_index(op.f("idx_metadata_robots_allowed"), "source_metadata", ["robots_allowed"])

    # Create indexes for source_group_association
    op.create_index(op.f("idx_source_group_source_id"), "source_group_association", ["source_id"])
    op.create_index(op.f("idx_source_group_group_id"), "source_group_association", ["group_id"])


def downgrade():
    # Drop indexes for source_group_association
    op.drop_index(op.f("idx_source_group_group_id"), table_name="source_group_association")
    op.drop_index(op.f("idx_source_group_source_id"), table_name="source_group_association")

    # Drop indexes for source_metadata
    op.drop_index(op.f("idx_metadata_robots_allowed"), table_name="source_metadata")
    op.drop_index(op.f("idx_metadata_language"), table_name="source_metadata")
    op.drop_index(op.f("idx_metadata_country"), table_name="source_metadata")
    op.drop_index(op.f("idx_metadata_source_id"), table_name="source_metadata")

    # Drop tables
    op.drop_table("source_group_association")
    op.drop_table("source_metadata")
    op.drop_table("source_groups")
