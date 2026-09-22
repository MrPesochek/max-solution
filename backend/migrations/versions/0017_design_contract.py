"""контракт под итоговый макет: отметка выезда, гарантия в смете, подписи

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-29

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE assignments ADD COLUMN en_route_at timestamptz")
    op.execute("ALTER TABLE repair_quotes ADD COLUMN warranty_terms text")
    op.execute("ALTER TABLE attachments ADD COLUMN caption text")
    op.execute(
        "ALTER TABLE attachments ADD CONSTRAINT ck_attachments_caption_length "
        "CHECK (caption IS NULL OR char_length(caption) <= 200)"
    )
    op.execute("ALTER TABLE messages ADD COLUMN author_label text")
    op.execute(
        "ALTER TABLE messages ADD CONSTRAINT ck_messages_author_label_length "
        "CHECK (author_label IS NULL OR char_length(author_label) <= 100)"
    )
    op.execute("ALTER TABLE service_bindings ADD COLUMN stated_guarantor_name text")
    op.execute("ALTER TABLE moderation_cases DROP CONSTRAINT ck_moderation_cases_status")
    op.execute(
        "ALTER TABLE moderation_cases ADD CONSTRAINT ck_moderation_cases_status "
        "CHECK (status IN ('pending', 'published', 'rejected', 'removed', 'withdrawn'))"
    )


def downgrade() -> None:
    op.execute("UPDATE moderation_cases SET status = 'rejected' WHERE status = 'withdrawn'")
    op.execute("ALTER TABLE moderation_cases DROP CONSTRAINT ck_moderation_cases_status")
    op.execute(
        "ALTER TABLE moderation_cases ADD CONSTRAINT ck_moderation_cases_status "
        "CHECK (status IN ('pending', 'published', 'rejected', 'removed'))"
    )
    op.execute("ALTER TABLE service_bindings DROP COLUMN stated_guarantor_name")
    op.execute("ALTER TABLE messages DROP COLUMN author_label")
    op.execute("ALTER TABLE attachments DROP COLUMN caption")
    op.execute("ALTER TABLE repair_quotes DROP COLUMN warranty_terms")
    op.execute("ALTER TABLE assignments DROP COLUMN en_route_at")
