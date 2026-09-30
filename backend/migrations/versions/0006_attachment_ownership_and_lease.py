"""вложения: фото оборудования, слот, связь копии с оригиналом, публикация, аренда обработки"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OWNER_KINDS_NEW = (
    "('request', 'message', 'profile', 'review', 'verification', 'moderation', 'equipment')"
)
OWNER_KINDS_OLD = "('request', 'message', 'profile', 'review', 'verification', 'moderation')"

OWNER_REF_COMMON = """
    (owner_kind = 'request' and request_id is not null)
    or (owner_kind = 'message' and message_id is not null and request_id is not null)
    or (owner_kind = 'profile' and provider_profile_id is not null)
    or (owner_kind = 'review' and review_id is not null)
    or (owner_kind = 'verification' and verification_case_id is not null)
    or (owner_kind = 'moderation' and moderation_case_id is not null)
"""


def upgrade() -> None:
    op.execute("ALTER TABLE attachments ADD COLUMN equipment_id uuid REFERENCES equipment (id)")
    op.execute("ALTER TABLE attachments ADD COLUMN slot text")
    op.execute(
        "ALTER TABLE attachments ADD COLUMN source_attachment_id uuid REFERENCES attachments (id)"
    )
    op.execute("ALTER TABLE attachments ADD COLUMN publication_state text")
    op.execute("ALTER TABLE attachments ADD COLUMN lease_until timestamptz")
    op.execute("ALTER TABLE attachments ADD COLUMN attempt_count integer NOT NULL DEFAULT 0")
    op.execute(
        """ALTER TABLE attachments ADD CONSTRAINT ck_attachments_publication_state
           CHECK (publication_state IS NULL
                  OR publication_state IN ('pending', 'published', 'rejected', 'removed'))"""
    )
    op.execute("ALTER TABLE attachments DROP CONSTRAINT ck_attachments_owner_kind")
    op.execute(
        f"ALTER TABLE attachments ADD CONSTRAINT ck_attachments_owner_kind "
        f"CHECK (owner_kind IN {OWNER_KINDS_NEW})"
    )
    op.execute("ALTER TABLE attachments DROP CONSTRAINT ck_attachments_owner_ref")
    op.execute(
        f"""ALTER TABLE attachments ADD CONSTRAINT ck_attachments_owner_ref CHECK (
            {OWNER_REF_COMMON}
            or (owner_kind = 'equipment' and equipment_id is not null)
        )"""
    )
    op.execute("CREATE INDEX ix_attachments_equipment_id ON attachments (equipment_id)")
    op.execute(
        "CREATE INDEX ix_attachments_source_attachment_id ON attachments (source_attachment_id)"
    )
    op.execute(
        """CREATE INDEX ix_attachments_processing_queue ON attachments (lease_until)
           WHERE processing_state = 'quarantined'"""
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_attachments_processing_queue")
    op.execute("DROP INDEX ix_attachments_source_attachment_id")
    op.execute("DROP INDEX ix_attachments_equipment_id")
    op.execute("DELETE FROM attachments WHERE owner_kind = 'equipment'")
    op.execute("ALTER TABLE attachments DROP CONSTRAINT ck_attachments_owner_ref")
    op.execute(
        f"ALTER TABLE attachments ADD CONSTRAINT ck_attachments_owner_ref CHECK ({OWNER_REF_COMMON})"
    )
    op.execute("ALTER TABLE attachments DROP CONSTRAINT ck_attachments_owner_kind")
    op.execute(
        f"ALTER TABLE attachments ADD CONSTRAINT ck_attachments_owner_kind "
        f"CHECK (owner_kind IN {OWNER_KINDS_OLD})"
    )
    op.execute("ALTER TABLE attachments DROP CONSTRAINT ck_attachments_publication_state")
    for column in (
        "attempt_count",
        "lease_until",
        "publication_state",
        "source_attachment_id",
        "slot",
        "equipment_id",
    ):
        op.execute(f"ALTER TABLE attachments DROP COLUMN {column}")
