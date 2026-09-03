# -*- coding: utf-8 -*-

import asyncio


def _make_user(db, username):
    from backend.database.models import User

    user = User(username=username, email=f"{username}@test.local", password_hash="x", role="user", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_client_category(db, user, *, dataset_id="ds-delete-test"):
    from backend.database.models import Client, Knowledge, KnowledgeCategory
    from backend.services.geo_knowledge_service import CLIENT_UPLOAD_TAG_PREFIX

    client = Client(name="Delete Co", company_name="Delete Co", user_id=user.id, status=1)
    db.add(client)
    db.commit()
    db.refresh(client)

    category = KnowledgeCategory(
        name="Delete Co-客户知识库",
        user_id=user.id,
        client_id=client.id,
        tags=f"{CLIENT_UPLOAD_TAG_PREFIX}{client.id}",
        ragflow_dataset_id=dataset_id,
        status=1,
    )
    db.add(category)
    db.commit()
    db.refresh(category)

    item = Knowledge(
        category_id=category.id,
        ragflow_dataset_id=dataset_id,
        ragflow_document_id=f"doc-{dataset_id}",
        title="test.txt",
        content="test",
        status=1,
    )
    db.add(item)
    db.commit()
    return client, category


def test_delete_category_deletes_remote_dataset_first(db, monkeypatch):
    from backend.api import knowledge as knowledge_api
    from backend.database.models import KnowledgeCategory, User

    user = _make_user(db, "delete_category_user")
    client, category = _make_client_category(db, user, dataset_id="ds-category-delete")
    deleted = []
    monkeypatch.setattr(knowledge_api, "delete_ragflow_datasets", lambda ids: deleted.extend(ids))

    try:
        asyncio.run(knowledge_api.delete_category(category.id, db=db, current_user=user))

        assert deleted == ["ds-category-delete"]
        assert db.query(KnowledgeCategory).filter(KnowledgeCategory.id == category.id).first() is None
    finally:
        db.query(User).filter(User.id == user.id).delete(synchronize_session=False)
        db.commit()


def test_delete_client_deletes_owned_remote_dataset(db, monkeypatch):
    from backend.api import client as client_api
    from backend.database.models import Client, KnowledgeCategory, User

    user = _make_user(db, "delete_client_user")
    client, category = _make_client_category(db, user, dataset_id="ds-client-delete")
    deleted = []
    monkeypatch.setattr(client_api, "delete_ragflow_datasets", lambda ids: deleted.extend(ids))

    try:
        stats = client_api._cascade_delete_client(client.id, user.id, db)
        db.delete(client)
        db.commit()

        assert deleted == ["ds-client-delete"]
        assert stats["knowledge_categories"] == 1
        assert db.query(KnowledgeCategory).filter(KnowledgeCategory.id == category.id).first() is None
        assert db.query(Client).filter(Client.id == client.id).first() is None
    finally:
        db.query(User).filter(User.id == user.id).delete(synchronize_session=False)
        db.commit()
