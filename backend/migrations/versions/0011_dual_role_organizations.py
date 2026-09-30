"""двойное участие организации: одно членство на человека и сторону"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE memberships DROP CONSTRAINT ux_memberships_user_org")
    op.execute(
        "CREATE UNIQUE INDEX ux_memberships_user_org_side ON memberships "
        "(user_id, organization_id, (role IN ('customer_employee', 'customer_manager')))"
    )


def downgrade() -> None:
    op.execute(
        """DO $$
        DECLARE duplicates integer;
        BEGIN
            SELECT count(*) INTO duplicates FROM (
                SELECT 1 FROM memberships
                GROUP BY user_id, organization_id
                HAVING count(*) > 1
            ) AS pairs;
            IF duplicates > 0 THEN
                RAISE EXCEPTION
                    'downgrade 0011: у % пар «пользователь — организация» по два членства '
                    '(по стороне заказчика и исполнителя); прежнее ограничение '
                    'ux_memberships_user_org их не допускает — оставьте по одному '
                    'членству на пару и повторите', duplicates;
            END IF;
        END $$"""
    )
    op.execute("DROP INDEX ux_memberships_user_org_side")
    op.execute(
        "ALTER TABLE memberships "
        "ADD CONSTRAINT ux_memberships_user_org UNIQUE (user_id, organization_id)"
    )
