"""Link smart article questions to GEO evaluation runs.

Revision ID: 0028_link_smart_questions
Revises: 0027_repair_platform_mojibake
"""

from alembic import op
import sqlalchemy as sa


revision = "0028_link_smart_questions"
down_revision = "0027_repair_platform_mojibake"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("geo_prompts", sa.Column("smart_article_question_id", sa.Integer(), nullable=True))
    op.create_index(
        "ix_geo_prompts_smart_article_question_id",
        "geo_prompts",
        ["smart_article_question_id"],
    )
    op.create_foreign_key(
        "fk_geo_prompts_smart_article_question_id",
        "geo_prompts",
        "smart_article_questions",
        ["smart_article_question_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_geo_prompts_set_smart_question",
        "geo_prompts",
        ["prompt_set_id", "smart_article_question_id"],
    )
    op.add_column("geo_evaluation_runs", sa.Column("prompt_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("geo_evaluation_runs", "prompt_ids")
    op.drop_constraint("uq_geo_prompts_set_smart_question", "geo_prompts", type_="unique")
    op.drop_constraint("fk_geo_prompts_smart_article_question_id", "geo_prompts", type_="foreignkey")
    op.drop_index("ix_geo_prompts_smart_article_question_id", table_name="geo_prompts")
    op.drop_column("geo_prompts", "smart_article_question_id")
