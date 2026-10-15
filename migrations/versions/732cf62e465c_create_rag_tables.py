"""create rag tables

Revision ID: 732cf62e465c
Revises: None
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR

revision = "732cf62e465c"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("index_signature", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
    )
    op.create_table(
        "chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("locator", sa.Text(), nullable=False),
        sa.Column("embedding", VECTOR(1024), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_chunks_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chunks"),
        sa.UniqueConstraint("document_id", "ordinal", name="uq_chunks_document_id"),
    )


def downgrade() -> None:
    op.drop_table("chunks")
    op.drop_table("documents")
    # Retain the extension: another application
