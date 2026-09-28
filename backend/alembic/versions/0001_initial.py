"""Initial schema: PostGIS extension, all tables, B-tree + GiST indexes.

Revision ID: 0001_initial
"""
from alembic import op
from sqlalchemy import text

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    from app.db import models
    from app.db.base import Base

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    Base.metadata.create_all(bind)  # tables + declared B-tree/composite indexes
    if bind.dialect.name == "postgresql":
        for ddl in models.SPATIAL_INDEX_DDL:
            bind.execute(text(ddl))


def downgrade():
    from app.db.base import Base

    Base.metadata.drop_all(op.get_bind())
