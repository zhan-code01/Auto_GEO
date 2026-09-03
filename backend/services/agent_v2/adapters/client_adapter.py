# -*- coding: utf-8 -*-
"""ClientAdapter - 客户管理适配器。"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.database.models import Client
from backend.middleware.user_isolation import scoped_query


class ClientAdapter:
    """客户管理适配器 - 给 Agent V2 工具层调用。"""

    def __init__(self, db: Session):
        self.db = db

    def list_clients(self, user, keyword: str | None = None, page: int = 1, limit: int = 20) -> dict[str, Any]:
        query = scoped_query(self.db, Client, user).filter(Client.deleted_at.is_(None) if hasattr(Client, "deleted_at") else True)
        if keyword:
            like = f"%{keyword}%"
            query = query.filter(
                (Client.name.ilike(like)) | (Client.company_name.ilike(like))
            )
        total = query.count()
        rows = query.order_by(Client.created_at.desc()).offset((page - 1) * limit).limit(limit).all()
        return {"total": total, "items": [self._to_dict(r) for r in rows]}

    def get_client(self, user, client_id: int) -> dict[str, Any] | None:
        row = scoped_query(self.db, Client, user).filter(Client.id == client_id).first()
        return self._to_dict(row) if row else None

    def create_client(self, user, data: dict[str, Any]) -> dict[str, Any]:
        client = Client(
            user_id=user.id,
            name=data.get("name") or data.get("company_name") or "未命名客户",
            company_name=data.get("company_name") or data.get("name"),
            contact_person=data.get("contact_person"),
            phone=data.get("phone"),
            email=data.get("email"),
            industry=data.get("industry"),
            location=data.get("location"),
            address=data.get("address"),
            website=data.get("website"),
            description=data.get("description"),
            status=1,
        )
        self.db.add(client)
        self.db.commit()
        self.db.refresh(client)
        return self._to_dict(client)

    def update_client(self, user, client_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
        client = scoped_query(self.db, Client, user).filter(Client.id == client_id).first()
        if not client:
            return None
        for key in ("name", "company_name", "contact_person", "phone", "email", "industry",
                     "location", "address", "website", "description", "status"):
            if key in data and data[key] is not None:
                setattr(client, key, data[key])
        self.db.commit()
        self.db.refresh(client)
        return self._to_dict(client)

    def delete_client(self, user, client_id: int) -> bool:
        client = scoped_query(self.db, Client, user).filter(Client.id == client_id).first()
        if not client:
            return False
        self.db.delete(client)
        self.db.commit()
        return True

    def find_by_company_name(self, user, company_name: str) -> list[dict[str, Any]]:
        """按公司名模糊查找（多候选时用）。"""
        rows = scoped_query(self.db, Client, user).filter(
            Client.company_name.ilike(f"%{company_name}%")
        ).limit(10).all()
        return [self._to_dict(r) for r in rows]

    @staticmethod
    def _to_dict(client: Client) -> dict[str, Any]:
        return {
            "id": client.id,
            "name": client.name,
            "company_name": client.company_name,
            "contact_person": client.contact_person,
            "phone": client.phone,
            "email": client.email,
            "industry": client.industry,
            "location": client.location,
            "address": client.address,
            "website": client.website,
            "description": client.description,
            "status": client.status,
            "created_at": client.created_at.isoformat() if client.created_at else None,
        }
