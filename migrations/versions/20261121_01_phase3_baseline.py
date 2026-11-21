"""Create missing TrafficWatch Phase 1/3 tables without replacing existing data."""
from alembic import op
from services.db_schema import metadata

revision = "20261121_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # checkfirst preserves existing Phase 1 tables and observations in-place.
    metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    # This is a baseline migration over existing operational data. It is intentionally
    # non-destructive; use a reviewed data-retention migration for any future removal.
    pass
