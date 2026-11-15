"""ledger de partida doble, con sus reglas dentro de la base de datos

Revision ID: 0010
Revises: 0009
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

SQLITE_TRIGGERS = [
    # Un asiento confirmado no se toca
    """CREATE TRIGGER entry_no_update BEFORE UPDATE ON journal_entries WHEN OLD.status = 'posted'
       BEGIN SELECT RAISE(ABORT, 'asiento confirmado: no se puede cambiar'); END""",
    """CREATE TRIGGER entry_no_delete BEFORE DELETE ON journal_entries WHEN OLD.status = 'posted'
       BEGIN SELECT RAISE(ABORT, 'asiento confirmado: no se puede borrar'); END""",
    """CREATE TRIGGER posting_no_update BEFORE UPDATE ON postings
       WHEN (SELECT status FROM journal_entries WHERE id = OLD.entry_id) = 'posted'
       BEGIN SELECT RAISE(ABORT, 'asiento confirmado: no se puede cambiar'); END""",
    """CREATE TRIGGER posting_no_delete BEFORE DELETE ON postings
       WHEN (SELECT status FROM journal_entries WHERE id = OLD.entry_id) = 'posted'
       BEGIN SELECT RAISE(ABORT, 'asiento confirmado: no se puede borrar'); END""",
    """CREATE TRIGGER posting_no_insert BEFORE INSERT ON postings
       WHEN (SELECT status FROM journal_entries WHERE id = NEW.entry_id) = 'posted'
       BEGIN SELECT RAISE(ABORT, 'asiento confirmado: no se puede cambiar'); END""",
]

PG_SQL = [
    """CREATE FUNCTION ledger_entry_guard() RETURNS trigger AS $$
       BEGIN
         IF OLD.status = 'posted' THEN RAISE EXCEPTION 'asiento confirmado: no se puede cambiar'; END IF;
         IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
         RETURN NEW;
       END $$ LANGUAGE plpgsql""",
    """CREATE TRIGGER entry_guard BEFORE UPDATE OR DELETE ON journal_entries FOR EACH ROW EXECUTE FUNCTION ledger_entry_guard()""",
    """CREATE FUNCTION ledger_posting_guard() RETURNS trigger AS $$
       DECLARE eid integer := COALESCE(NEW.entry_id, OLD.entry_id);
       BEGIN
         IF TG_OP <> 'INSERT' AND (SELECT status FROM journal_entries WHERE id = eid) = 'posted' THEN
           RAISE EXCEPTION 'asiento confirmado: no se puede cambiar';
         END IF;
         IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
         RETURN NEW;
       END $$ LANGUAGE plpgsql""",
    """CREATE TRIGGER posting_guard BEFORE INSERT OR UPDATE OR DELETE ON postings FOR EACH ROW EXECUTE FUNCTION ledger_posting_guard()""",
    # Al confirmar la transacción, cada asiento debe sumar cero por moneda
    """CREATE FUNCTION ledger_balance_check() RETURNS trigger AS $$
       DECLARE eid integer := COALESCE(NEW.entry_id, OLD.entry_id);
       BEGIN
         IF EXISTS (SELECT 1 FROM postings WHERE entry_id = eid GROUP BY currency HAVING sum(amount) <> 0) THEN
           RAISE EXCEPTION 'asiento % descuadrado', eid;
         END IF;
         RETURN NULL;
       END $$ LANGUAGE plpgsql""",
    """CREATE CONSTRAINT TRIGGER posting_balance AFTER INSERT OR UPDATE OR DELETE ON postings
       DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ledger_balance_check()""",
]


def upgrade() -> None:
    op.create_table("ledger_accounts",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("name", sa.String(160), nullable=False, unique=True),
        sa.Column("kind", sa.String(12), nullable=False, index=True), sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("institution", sa.String(80), nullable=False), sa.Column("closed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("kind IN ('asset','liability','equity','income','expense')", name="ck_account_kind"))
    op.create_table("import_batches",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("account_id", sa.Integer(), sa.ForeignKey("ledger_accounts.id"), nullable=False),
        sa.Column("filename", sa.String(200), nullable=False), sa.Column("sha256", sa.String(64), nullable=False, index=True),
        sa.Column("rows", sa.Integer(), nullable=False), sa.Column("created_by", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_table("journal_entries",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("entry_date", sa.String(10), nullable=False, index=True),
        sa.Column("description", sa.String(300), nullable=False), sa.Column("counterparty", sa.String(160), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, index=True), sa.Column("reverses_id", sa.Integer(), sa.ForeignKey("journal_entries.id"), nullable=True),
        sa.Column("external_id", sa.String(160), nullable=True, unique=True), sa.Column("batch_id", sa.Integer(), sa.ForeignKey("import_batches.id"), nullable=True, index=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id"), nullable=True), sa.Column("created_by", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("status IN ('pending','posted')", name="ck_entry_status"))
    op.create_table("postings",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("entry_id", sa.Integer(), sa.ForeignKey("journal_entries.id"), nullable=False, index=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("ledger_accounts.id"), nullable=False, index=True),
        sa.Column("amount", sa.Numeric(18, 4), nullable=False), sa.Column("currency", sa.String(8), nullable=False))
    op.create_table("balance_assertions",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("account_id", sa.Integer(), sa.ForeignKey("ledger_accounts.id"), nullable=False, index=True),
        sa.Column("as_of", sa.String(10), nullable=False), sa.Column("amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_table("category_rules",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("pattern", sa.String(120), nullable=False, unique=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("ledger_accounts.id"), nullable=False))
    op.create_table("budgets",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("account_id", sa.Integer(), sa.ForeignKey("ledger_accounts.id"), nullable=False),
        sa.Column("month", sa.String(7), nullable=False, index=True), sa.Column("amount", sa.Numeric(18, 4), nullable=False),
        sa.UniqueConstraint("account_id", "month"))
    for sql in (PG_SQL if op.get_bind().dialect.name == "postgresql" else SQLITE_TRIGGERS):
        op.execute(sql)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER posting_balance ON postings")
        op.execute("DROP TRIGGER posting_guard ON postings")
        op.execute("DROP TRIGGER entry_guard ON journal_entries")
        for f in ("ledger_balance_check", "ledger_posting_guard", "ledger_entry_guard"):
            op.execute(f"DROP FUNCTION {f}()")
    for t in ("budgets", "category_rules", "balance_assertions", "postings", "journal_entries", "import_batches", "ledger_accounts"):
        op.drop_table(t)
