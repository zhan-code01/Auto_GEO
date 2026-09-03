import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.api.smart_articles import _require_linked_project, list_projects
from backend.database import Base
from backend.database.models import Client, Project, User


@pytest.fixture
def local_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def _seed(db):
    user = User(
        username="company_project_user",
        email="company_project_user@test.local",
        password_hash="x",
        role="user",
        is_active=True,
    )
    db.add(user)
    db.flush()
    first_client = Client(name="甲公司", company_name="甲公司", user_id=user.id, status=1)
    second_client = Client(name="乙公司", company_name="乙公司", user_id=user.id, status=1)
    db.add_all([first_client, second_client])
    db.flush()
    linked = Project(name="甲项目", user_id=user.id, client_id=first_client.id, status=1)
    other = Project(name="乙项目", user_id=user.id, client_id=second_client.id, status=1)
    unlinked = Project(name="未归属项目", user_id=user.id, client_id=None, status=1)
    disabled = Project(name="停用项目", user_id=user.id, client_id=first_client.id, status=0)
    db.add_all([linked, other, unlinked, disabled])
    db.commit()
    return user, first_client, second_client, linked, other, unlinked, disabled


def test_project_list_filters_by_company_and_hides_unlinked_projects(local_db):
    db = local_db
    user, first_client, _second_client, linked, other, unlinked, disabled = _seed(db)

    first_company_projects = asyncio.run(list_projects(first_client.id, db, user))
    all_linked_projects = asyncio.run(list_projects(None, db, user))

    assert [item["id"] for item in first_company_projects] == [linked.id]
    assert {item["id"] for item in all_linked_projects} == {linked.id, other.id}
    assert unlinked.id not in {item["id"] for item in all_linked_projects}
    assert disabled.id not in {item["id"] for item in all_linked_projects}
    assert first_company_projects[0]["client_id"] == first_client.id
    assert first_company_projects[0]["company_name"] == "甲公司"


def test_unlinked_project_is_rejected_by_smart_article_actions(local_db):
    db = local_db
    user, _first_client, _second_client, linked, _other, unlinked, disabled = _seed(db)

    assert _require_linked_project(db, user, linked.id).id == linked.id
    with pytest.raises(HTTPException, match="尚未关联公司"):
        _require_linked_project(db, user, unlinked.id)
    with pytest.raises(HTTPException, match="已停用"):
        _require_linked_project(db, user, disabled.id)
