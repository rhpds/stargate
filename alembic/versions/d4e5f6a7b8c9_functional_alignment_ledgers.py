"""Add durable functional-alignment ledgers.

Revision ID: d4e5f6a7b8c9
Revises: faff0a4b8665
"""

from alembic import op
import sqlalchemy as sa

revision = "d4e5f6a7b8c9"
down_revision = "faff0a4b8665"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source_system", sa.String(50), nullable=False),
        sa.Column("source_instance", sa.String(255), nullable=False),
        sa.Column("source_event_id", sa.String(255), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(30), nullable=False, server_default="fail"),
        sa.Column("state", sa.String(30), nullable=False, server_default="new"),
        sa.Column("job_id", sa.String(255)), sa.Column("controller_url", sa.String(500)),
        sa.Column("job_url", sa.String(500)), sa.Column("task", sa.Text()),
        sa.Column("play", sa.Text()), sa.Column("role", sa.Text()),
        sa.Column("guid", sa.String(255)), sa.Column("catalog_item", sa.String(255)),
        sa.Column("stage", sa.String(100)), sa.Column("action", sa.String(100)),
        sa.Column("provider", sa.String(100)), sa.Column("cluster", sa.String(100)),
        sa.Column("failure_class", sa.String(255)),
        sa.Column("normalized_error", sa.Text(), nullable=False),
        sa.Column("raw_evidence", sa.JSON()),
        sa.Column("occurred_at", sa.DateTime(timezone=True)),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True)),
        sa.Column("diagnosed_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("source_system", "source_instance", "source_event_id", name="uq_source_event_identity"),
    )
    for name, columns in (
        ("ix_source_events_state", ["state"]), ("ix_source_events_outcome", ["outcome"]),
        ("ix_source_events_job_id", ["job_id"]),
        ("ix_source_events_evidence_hash", ["evidence_hash"]),
        ("ix_source_events_catalog_item", ["catalog_item"]),
        ("ix_source_events_failure_class", ["failure_class"]),
        ("idx_source_event_state_seen", ["state", "last_seen_at"]),
    ):
        op.create_index(name, "source_events", columns)

    op.add_column("evaluations", sa.Column("source_event_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_evaluations_source_event", "evaluations", "source_events", ["source_event_id"], ["id"])
    op.create_index("ix_evaluations_source_event_id", "evaluations", ["source_event_id"])
    op.add_column("investigations", sa.Column("diagnosis_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("investigations", sa.Column("evidence_hash", sa.String(64), nullable=True))
    op.add_column("investigations", sa.Column("review_state", sa.String(30), nullable=False, server_default="unreviewed"))
    op.add_column("investigations", sa.Column("reviewed_by", sa.String(255), nullable=True))
    op.add_column("investigations", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("investigations", sa.Column("knowledge_match", sa.JSON(), nullable=True))
    op.create_index("ix_investigations_evidence_hash", "investigations", ["evidence_hash"])

    op.create_table(
        "investigation_source_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("investigation_id", sa.Integer, sa.ForeignKey("investigations.id"), nullable=False),
        sa.Column("source_event_id", sa.Integer, sa.ForeignKey("source_events.id"), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("diagnosis_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("diagnosed_at", sa.DateTime(timezone=True)),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column("release_reason", sa.String(255)),
        sa.UniqueConstraint("investigation_id", "source_event_id", name="uq_inv_source_event"),
    )
    op.create_index("ix_inv_source_investigation", "investigation_source_events", ["investigation_id"])
    op.create_index("ix_inv_source_event", "investigation_source_events", ["source_event_id"])

    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Integer, primary_key=True), sa.Column("channel", sa.String(50), nullable=False),
        sa.Column("dedup_key", sa.String(255), nullable=False), sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("investigation_id", sa.Integer, sa.ForeignKey("investigations.id")),
        sa.Column("diagnosis_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("external_message_id", sa.String(255)), sa.Column("last_error", sa.Text()),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("channel", "dedup_key", name="uq_notification_channel_key"),
    )
    op.create_index("ix_notification_status", "notification_deliveries", ["status"])

    op.create_table(
        "external_tickets",
        sa.Column("id", sa.Integer, primary_key=True), sa.Column("system", sa.String(30), nullable=False),
        sa.Column("dedup_signature", sa.String(255), nullable=False), sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("ticket_key", sa.String(100)), sa.Column("ticket_url", sa.String(500)),
        sa.Column("status", sa.String(50), nullable=False, server_default="draft"),
        sa.Column("investigation_id", sa.Integer, sa.ForeignKey("investigations.id")),
        sa.Column("diagnosis_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("source_event_ids", sa.JSON(), nullable=False), sa.Column("draft_payload", sa.JSON(), nullable=False),
        sa.Column("last_error", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("uq_active_ticket_signature", "external_tickets", ["system", "dedup_signature"],
                    unique=True, postgresql_where=sa.text("active = true"))
    op.create_index("ix_external_ticket_status", "external_tickets", ["status"])

    op.create_table(
        "knowledge_entries",
        sa.Column("id", sa.Integer, primary_key=True), sa.Column("signature", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer, nullable=False), sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("root_cause", sa.Text(), nullable=False), sa.Column("remediation", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON()), sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float()), sa.Column("investigation_id", sa.Integer, sa.ForeignKey("investigations.id"), nullable=False),
        sa.Column("reviewed_by", sa.String(255), nullable=False), sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        sa.Column("acceptance_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("rejection_count", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint("signature", "version", name="uq_knowledge_signature_version"),
    )
    op.create_index("ix_knowledge_signature", "knowledge_entries", ["signature"])

    op.create_table(
        "trend_signals",
        sa.Column("id", sa.Integer, primary_key=True), sa.Column("signal_key", sa.String(255), unique=True, nullable=False),
        sa.Column("signal_type", sa.String(100), nullable=False), sa.Column("catalog_item", sa.String(255)),
        sa.Column("failure_class", sa.String(255)), sa.Column("current_rate", sa.Float()),
        sa.Column("baseline_rate", sa.Float()), sa.Column("failure_count", sa.Integer, nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False), sa.Column("status", sa.String(30), nullable=False, server_default="open"),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False), sa.Column("resolved_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_trend_signal_type", "trend_signals", ["signal_type"])


def downgrade() -> None:
    for table in ("trend_signals", "knowledge_entries", "external_tickets", "notification_deliveries", "investigation_source_events"):
        op.drop_table(table)
    op.drop_index("ix_investigations_evidence_hash", table_name="investigations")
    for column in ("knowledge_match", "reviewed_at", "reviewed_by", "review_state", "evidence_hash", "diagnosis_version"):
        op.drop_column("investigations", column)
    op.drop_index("ix_evaluations_source_event_id", table_name="evaluations")
    op.drop_constraint("fk_evaluations_source_event", "evaluations", type_="foreignkey")
    op.drop_column("evaluations", "source_event_id")
    op.drop_table("source_events")
