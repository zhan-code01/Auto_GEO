"""Yxer local bindings and record extension placeholder.

This migration was applied outside the current codebase. It is kept as a
placeholder so the Alembic version chain remains intact.

Revision ID: 0031_yxer_local_bindings_and_record_extension
Revises: 0028_link_smart_questions
"""

from alembic import op


revision = "0031_yxer_local_bindings_and_record_extension"
down_revision = "0028_link_smart_questions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Placeholder: schema changes were already applied to the database.
    pass


def downgrade() -> None:
    # Placeholder: rollback is not implemented for this out-of-tree migration.
    pass
