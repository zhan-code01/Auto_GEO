"""Add the two-step smart article question pool.

Revision ID: 0026_smart_article_question_pool
Revises: 0025_smart_article_generation
"""

from __future__ import annotations

import re

from alembic import op
import sqlalchemy as sa


revision = "0026_smart_article_question_pool"
down_revision = "0025_smart_article_generation"
branch_labels = None
depends_on = None


def _normalize_question(value: str) -> str:
    return re.sub(r"[\s\W_]+", "", str(value or "")).lower()


def upgrade() -> None:
    op.add_column(
        "smart_article_batches",
        sa.Column("batch_type", sa.String(length=30), nullable=False, server_default="article_generation"),
    )
    op.add_column("smart_article_batches", sa.Column("expanded_terms", sa.JSON(), nullable=True))

    op.create_table(
        "smart_article_questions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("generation_batch_id", sa.Integer(), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("normalized_question", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="ai"),
        sa.Column("intent_type", sa.String(length=30), nullable=False, server_default="manual"),
        sa.Column("context_type", sa.String(length=20), nullable=False, server_default="general"),
        sa.Column("brand_entry_reason", sa.Text(), nullable=True),
        sa.Column("retrieval_terms", sa.JSON(), nullable=True),
        sa.Column("has_article", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("article_id", sa.Integer(), nullable=True),
        sa.Column("article_generation_status", sa.String(length=20), nullable=False, server_default="idle"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["generation_batch_id"], ["smart_article_batches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["article_id"], ["geo_articles.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("project_id", "normalized_question", name="uq_smart_article_questions_project_question"),
    )
    for name, column in (
        ("user_id", "user_id"),
        ("project_id", "project_id"),
        ("generation_batch_id", "generation_batch_id"),
        ("article_id", "article_id"),
        ("has_article", "has_article"),
        ("is_deleted", "is_deleted"),
    ):
        op.create_index(f"ix_smart_article_questions_{name}", "smart_article_questions", [column])

    op.add_column("smart_article_jobs", sa.Column("question_id", sa.Integer(), nullable=True))
    op.create_index("ix_smart_article_jobs_question_id", "smart_article_jobs", ["question_id"])
    op.create_foreign_key(
        "fk_smart_article_jobs_question_id",
        "smart_article_jobs",
        "smart_article_questions",
        ["question_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Backfill existing smart jobs and legacy smart_question keywords so the first
    # two-step question generation does not immediately repeat old questions.
    bind = op.get_bind()
    question_rows = (
        bind.execute(
            sa.text(
                """
            SELECT j.id, j.user_id, j.project_id, j.batch_id, j.question, j.status, j.article_id,
                   COALESCE(b.mode, 'auto') AS batch_mode
            FROM smart_article_jobs j
            LEFT JOIN smart_article_batches b ON b.id = j.batch_id
            WHERE j.question IS NOT NULL AND length(trim(j.question)) > 0
            ORDER BY j.id
            """
            )
        )
        .mappings()
        .all()
    )
    question_ids: dict[tuple[int, str], int] = {}
    for row in question_rows:
        key = (int(row["project_id"]), _normalize_question(row["question"]))
        if not key[1]:
            continue
        question_id = question_ids.get(key)
        if question_id is None:
            has_article = row["status"] == "completed" and row["article_id"] is not None
            status = "generated" if has_article else ("failed" if row["status"] == "failed" else "generating")
            result = bind.execute(
                sa.text(
                    """
                    INSERT INTO smart_article_questions
                        (user_id, project_id, generation_batch_id, question, normalized_question,
                         source, intent_type, context_type, has_article, article_id,
                         article_generation_status)
                    VALUES (:user_id, :project_id, :batch_id, :question, :normalized,
                            :source, 'manual', 'general', :has_article, :article_id, :status)
                    RETURNING id
                    """
                ),
                {
                    "user_id": row["user_id"],
                    "project_id": row["project_id"],
                    "batch_id": row["batch_id"],
                    "question": row["question"],
                    "normalized": key[1],
                    "source": "manual" if row["batch_mode"] == "manual" else "ai",
                    "has_article": has_article,
                    "article_id": row["article_id"] if has_article else None,
                    "status": status,
                },
            )
            question_id = int(result.scalar_one())
            question_ids[key] = question_id
        bind.execute(
            sa.text("UPDATE smart_article_jobs SET question_id=:question_id WHERE id=:job_id"),
            {"question_id": question_id, "job_id": row["id"]},
        )

    keyword_rows = (
        bind.execute(
            sa.text(
                """
            SELECT project_id, keyword
            FROM keywords
            WHERE keyword_type = 'smart_question' AND keyword IS NOT NULL
            """
            )
        )
        .mappings()
        .all()
    )
    for row in keyword_rows:
        key = (int(row["project_id"]), _normalize_question(row["keyword"]))
        if not key[1] or key in question_ids:
            continue
        result = bind.execute(
            sa.text(
                """
                INSERT INTO smart_article_questions
                    (project_id, question, normalized_question, source, intent_type,
                     context_type, article_generation_status)
                VALUES (:project_id, :question, :normalized, 'ai', 'manual', 'general', 'idle')
                RETURNING id
                """
            ),
            {"project_id": row["project_id"], "question": row["keyword"], "normalized": key[1]},
        )
        question_ids[key] = int(result.scalar_one())


def downgrade() -> None:
    op.drop_constraint("fk_smart_article_jobs_question_id", "smart_article_jobs", type_="foreignkey")
    op.drop_index("ix_smart_article_jobs_question_id", table_name="smart_article_jobs")
    op.drop_column("smart_article_jobs", "question_id")
    for name in (
        "ix_smart_article_questions_is_deleted",
        "ix_smart_article_questions_has_article",
        "ix_smart_article_questions_article_id",
        "ix_smart_article_questions_generation_batch_id",
        "ix_smart_article_questions_project_id",
        "ix_smart_article_questions_user_id",
    ):
        op.drop_index(name, table_name="smart_article_questions")
    op.drop_table("smart_article_questions")
    op.drop_column("smart_article_batches", "expanded_terms")
    op.drop_column("smart_article_batches", "batch_type")
