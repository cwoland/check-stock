import sqlalchemy as sa
from alembic import op

revision = "4f08b75a327c"
down_revision = "e0ea542b2b60"
branch_labels = None
depends_on = None

WAREHOUSE_KEYS = (
    ("stock", "warehouse_id", None),
    ("receipts", "warehouse_id", "SET NULL"),
    ("transfers", "source_id", None),
    ("transfers", "destination_id", None),
    ("shipments", "warehouse_id", None),
)


def upgrade() -> None:
    op.create_table(
        "retired_warehouses",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=False),
    )
    for table, column, _ in WAREHOUSE_KEYS:
        op.drop_constraint(f"{table}_{column}_fkey", table, type_="foreignkey")
    op.alter_column("receipts", "warehouse_id", nullable=False)


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM retired_warehouses)")
    ).scalar_one():
        raise RuntimeError("Откат невозможен после удаления ФФ с сохранением истории")

    op.alter_column("receipts", "warehouse_id", nullable=True)
    for table, column, ondelete in WAREHOUSE_KEYS:
        op.create_foreign_key(
            f"{table}_{column}_fkey",
            table,
            "warehouses",
            [column],
            ["id"],
            ondelete=ondelete,
        )
    op.drop_table("retired_warehouses")