import sqlalchemy as sa
from alembic import op

revision = "78af985124ee"
down_revision = "2cd892f7bc41"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transfers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("sku", sa.String(), sa.ForeignKey("products.sku"), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("destination_id", sa.Integer(), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("source_name", sa.String(), nullable=False),
        sa.Column("destination_name", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("quantity > 0", name="ck_transfers_quantity_positive"),
        sa.CheckConstraint("source_id <> destination_id", name="ck_transfers_distinct_warehouses"),
    )


def downgrade() -> None:
    op.drop_table("transfers")
