# -*- coding: utf-8 -*-

from backend.services.ragflow_client import RAGFlowClient


class _ConfigClient(RAGFlowClient):
    def __init__(self, dataset_data):
        super().__init__(base_url="http://example.invalid", api_key="k")
        self.dataset_data = dataset_data
        self.updated = []

    def get_dataset(self, dataset_id):
        return {"code": 0, "data": self.dataset_data}

    def update_dataset(
        self,
        dataset_id,
        name=None,
        description=None,
        embedding_model=None,
        chunk_method=None,
        extra_config=None,
    ):
        payload = {}
        if chunk_method:
            payload["chunk_method"] = chunk_method
        if extra_config:
            payload.update(extra_config)
        self.updated.append((dataset_id, payload))
        return {"code": 0}


def test_upload_config_moves_legacy_pdf_parser_to_layout_recognize_deepdoc():
    client = _ConfigClient(
        {
            "chunk_method": "naive",
            "parser_config": {
                "chunk_token_num": 1024,
                "delimiter": "\n",
                "layout_recognize": True,
                "pdf_parser": True,
                "raptor": {"use_raptor": False},
            },
        }
    )

    result = client.ensure_dataset_chunk_method("ds_pdf")

    assert result["code"] == 0
    assert client.updated == [
        (
            "ds_pdf",
            {
                "parser_config": {
                    "chunk_token_num": 1024,
                    "delimiter": "\n",
                    "layout_recognize": "DeepDOC",
                    "raptor": {"use_raptor": False},
                }
            },
        )
    ]


def test_upload_config_fixes_chunk_method_and_missing_parser_config():
    client = _ConfigClient({"chunk_method": "paper", "parser_config": {}})

    result = client.ensure_dataset_chunk_method("ds_paper")

    assert result["code"] == 0
    assert client.updated == [
        (
            "ds_paper",
            {
                "chunk_method": "naive",
                "parser_config": {
                    "chunk_token_num": 2048,
                    "delimiter": r"\n\n",
                    "layout_recognize": "DeepDOC",
                },
            },
        )
    ]


def test_upload_config_does_not_update_when_already_ready():
    client = _ConfigClient(
        {
            "chunk_method": "naive",
            "parser_config": {
                "chunk_token_num": 2048,
                "delimiter": r"\n\n",
                "layout_recognize": "DeepDOC",
            },
        }
    )

    result = client.ensure_dataset_chunk_method("ds_ready")

    assert result["code"] == 0
    assert client.updated == []


def test_create_dataset_uses_deepdoc_layout_without_legacy_pdf_parser(monkeypatch):
    client = RAGFlowClient(base_url="http://example.invalid", api_key="k")
    captured = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"code": 0, "data": {"id": "ds_new"}}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(client.session, "post", fake_post)

    result = client.create_dataset("PDF dataset", "desc")

    assert result["code"] == 0
    assert captured["json"]["chunk_method"] == "naive"
    assert captured["json"]["parser_config"]["layout_recognize"] == "DeepDOC"
    assert "pdf_parser" not in captured["json"]["parser_config"]
