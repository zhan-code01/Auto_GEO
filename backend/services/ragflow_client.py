# -*- coding: utf-8 -*-
"""
RAGFlow API 客户端封装
用于文章向量化和去重检测!
"""

import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import List, Dict, Optional, Tuple, Any
from loguru import logger


class RAGFlowClient:
    """
    RAGFlow API 客户端封装

    功能:
    1. 知识库管理
    2. 文档上传与解析
    3. 检索(用于去重)
    4. 聊天对话(用于生成)
    """

    DEFAULT_CHUNK_METHOD = "naive"
    DEFAULT_PARSER_CONFIG = {
        "chunk_token_num": 2048,
        "delimiter": r"\n\n",
        "layout_recognize": "DeepDOC",
    }

    def __init__(self, base_url: str = None, api_key: str = None):
        """
        初始化 RAGFlow 客户端

        Args:
            base_url: RAGFlow 服务地址,默认从环境变量读取
            api_key: API Key,默认从环境变量读取
        """
        self.base_url = base_url or os.getenv("RAGFLOW_BASE_URL", "http://localhost:9380")
        self.api_key = api_key or os.getenv("RAGFLOW_API_KEY", "")
        self.dataset_id = os.getenv("RAGFLOW_DATASET_ID", "")
        self.embedding_model = os.getenv("RAGFLOW_EMBEDDING_MODEL", "text-embedding-v4@Tongyi-Qianwen")

        self.session = requests.Session()
        # 绕过系统代理: Windows 上常见的 Clash/V2Ray 代理会在环境变量暴露 HTTP_PROXY/HTTPS_PROXY,
        # 导致 RAGFlow 请求被错误转发到本地代理端口(如 127.0.0.1:7897)而超时。
        # RAGFlow 服务通常部署在同区域公网/内网,直连即可,无需走代理。
        self.session.trust_env = False
        self.session.headers.update({"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})

        # 重试:RAGFlow 偶发 502/503/504 网关抖动或连接重置时,自动退避重试,避免单次抖动直接报错。
        # 仅对幂等且安全的 GET/PUT/DELETE 生效;POST(创建知识库/上传文档)不重试,以免造成重复创建。
        retry_kwargs = dict(
            total=3,
            backoff_factor=0.5,  # 退避: ~0.5s -> 1.0s -> 2.0s
            status_forcelist=(502, 503, 504),
            raise_on_status=False,  # 保留各方法自行 raise_for_status + 捕获日志的既有行为
        )
        try:
            retry = Retry(allowed_methods=frozenset(["GET", "HEAD", "PUT", "DELETE"]), **retry_kwargs)
        except TypeError:  # urllib3 < 1.26 兼容(method_whitelist)
            retry = Retry(method_whitelist=frozenset(["GET", "HEAD", "PUT", "DELETE"]), **retry_kwargs)
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        # 超时配置:普通请求15秒(RAGFlow 检索应快速返回;过长会占用后端线程池),
        # 文档解析120秒(大文件可能需要更长时间)。
        # 当 RAGFlow 服务不可用时,短超时可让降级逻辑快速生效,避免拖垮整个后端。
        self.timeout = 15
        self.parse_timeout = 120

    def is_configured(self) -> bool:
        """检查是否已配置"""
        return bool(self.api_key and self.base_url)

    # ==================== 知识库管理 ====================

    def _extract_datasets(self, result: Dict) -> List[Dict]:
        data = result.get("data", [])
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            for key in ("items", "datasets", "list"):
                items = data.get(key)
                if isinstance(items, list):
                    return [item for item in items if isinstance(item, dict)]
        return []

    def _extract_documents(self, result: Dict) -> List[Dict]:
        """Normalize RAGFlow document lists across API versions."""
        data = result.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            for key in ("docs", "documents", "items", "list"):
                items = data.get(key)
                if isinstance(items, list):
                    return [item for item in items if isinstance(item, dict)]
            if data.get("id"):
                return [data]
        if result.get("id"):
            return [result]
        return []

    def _extract_document_ids(self, result: Dict) -> List[str]:
        return [str(doc["id"]) for doc in self._extract_documents(result) if doc.get("id")]

    def _resolve_embedding_model(self, tenant_id: str = None) -> str:
        if self.embedding_model:
            return self.embedding_model

        if not tenant_id:
            return ""

        result = self.list_datasets(page=1, page_size=100)
        if result.get("code") != 0:
            return ""

        for dataset in self._extract_datasets(result):
            if dataset.get("tenant_id") != tenant_id:
                continue
            embedding_model = dataset.get("embedding_model")
            if embedding_model:
                self.embedding_model = str(embedding_model)
                logger.info(f"复用已有 RAGFlow 向量模型: {self.embedding_model}")
                return self.embedding_model

        return ""

    def ensure_dataset_embedding_model(self, dataset_id: str) -> Dict:
        result = self.get_dataset(dataset_id)
        if result.get("code") != 0:
            return result

        data = result.get("data", {})
        current_embedding_model = data.get("embedding_model") if isinstance(data, dict) else None
        if current_embedding_model:
            if self.embedding_model and current_embedding_model != self.embedding_model:
                update_result = self.update_dataset(dataset_id, embedding_model=self.embedding_model)
                if update_result.get("code") == 0:
                    logger.info(
                        f"已更新知识库 RAGFlow 向量模型: dataset_id={dataset_id}, "
                        f"from={current_embedding_model}, to={self.embedding_model}"
                    )
                return update_result
            return result

        tenant_id = data.get("tenant_id") if isinstance(data, dict) else None
        embedding_model = self._resolve_embedding_model(tenant_id=tenant_id)
        if not embedding_model:
            return {
                "code": -1,
                "message": "当前 RAGFlow 租户未配置可用 embedding 模型,请先在 RAGFlow 中设置默认向量模型",
            }

        update_result = self.update_dataset(dataset_id, embedding_model=embedding_model)
        if update_result.get("code") == 0:
            logger.info(f"已为知识库绑定 RAGFlow 向量模型: dataset_id={dataset_id}, model={embedding_model}")
        return update_result

    def try_bind_dataset_embedding_model(self, dataset_id: str) -> Dict:
        """Best-effort bind; upload should still proceed if RAGFlow rejects the model."""
        result = self.ensure_dataset_embedding_model(dataset_id)
        if result.get("code") != 0:
            logger.warning(
                f"绑定 RAGFlow 向量模型失败,将继续上传文件: "
                f"dataset_id={dataset_id}, model={self.embedding_model}, message={result.get('message')}"
            )
        return result

    def _build_upload_parser_config(self, current_config: Any = None) -> Dict:
        parser_config = dict(current_config) if isinstance(current_config, dict) else {}
        parser_config.pop("pdf_parser", None)
        for key, value in self.DEFAULT_PARSER_CONFIG.items():
            if key == "layout_recognize":
                parser_config[key] = value
            else:
                parser_config.setdefault(key, value)
        return parser_config

    def ensure_dataset_chunk_method(self, dataset_id: str) -> Dict:
        """
        确保数据集使用兼容的分块方法。
        手动创建的数据集可能使用 paper/qa/table 等专用解析器,
        普通文档上传会解析失败,需要自动修复为 naive (通用文本分块)。
        """
        result = self.get_dataset(dataset_id)
        if result.get("code") != 0:
            return result

        data = result.get("data", {})
        current_method = data.get("chunk_method") if isinstance(data, dict) else None
        current_parser_config = data.get("parser_config") if isinstance(data, dict) else None
        desired_parser_config = self._build_upload_parser_config(current_parser_config)
        update_payload = {}

        if current_method != self.DEFAULT_CHUNK_METHOD:
            logger.warning(f"Dataset {dataset_id} chunk_method={current_method}, fixing to naive for uploads")
            update_payload["chunk_method"] = self.DEFAULT_CHUNK_METHOD

        if current_parser_config != desired_parser_config:
            current_layout = current_parser_config.get("layout_recognize") if isinstance(current_parser_config, dict) else None
            current_pdf_parser = current_parser_config.get("pdf_parser") if isinstance(current_parser_config, dict) else None
            logger.warning(
                f"Dataset {dataset_id} layout_recognize={current_layout}, pdf_parser={current_pdf_parser}, "
                "fixing to DeepDOC for PDF parsing"
            )
            update_payload["parser_config"] = desired_parser_config

        if update_payload:
            update_result = self.update_dataset(dataset_id, extra_config=update_payload)
            if update_result.get("code") == 0:
                logger.info(f"Updated RAGFlow dataset upload config: dataset_id={dataset_id}, payload={update_payload}")
            return update_result

        return {"code": 0}

        if current_method and current_method != "naive":
            logger.warning(
                f"数据集 {dataset_id} chunk_method={current_method}, "
                f"自动修复为 naive 以确保文档解析正常"
            )
            update_result = self.update_dataset(dataset_id, chunk_method="naive")
            if update_result.get("code") == 0:
                logger.info(f"已更新数据集 chunk_method: {dataset_id} paper/qa/etc -> naive")
            return update_result

        return {"code": 0}

    def create_dataset(self, name: str, description: str = None) -> Dict:
        """
        创建知识库

        Args:
            name: 知识库名称
            description: 描述

        Returns:
            API 响应
        """
        payload = {
            "name": name,
            "chunk_method": self.DEFAULT_CHUNK_METHOD,
            "parser_config": self.DEFAULT_PARSER_CONFIG.copy(),
        }
        if description:
            payload["description"] = description
        embedding_model = self._resolve_embedding_model()
        if embedding_model:
            payload["embedding_model"] = embedding_model

        logger.info(f"创建知识库: name={name}")

        try:
            resp = self.session.post(f"{self.base_url}/api/v1/datasets", json=payload, timeout=self.timeout)
            resp.raise_for_status()
            result = resp.json()
            logger.info(f"创建知识库成功: {name}")
            return result
        except Exception as e:
            logger.error(f"创建知识库失败: {e}")
            return {"code": -1, "message": str(e)}

    def list_datasets(self, name: str = None, page: int = 1, page_size: int = 100) -> Dict:
        """
        列出知识库

        Args:
            name: 可选,按名称筛选
            page: 页码
            page_size: 每页数量

        Returns:
            知识库列表
        """
        params = {"page": page, "page_size": page_size}
        if name:
            params["name"] = name

        try:
            resp = self.session.get(f"{self.base_url}/api/v1/datasets", params=params, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"列出知识库失败: {e}")
            return {"code": -1, "message": str(e)}

    def get_dataset(self, dataset_id: str) -> Dict:
        """
        获取知识库详情

        Args:
            dataset_id: 知识库 ID

        Returns:
            知识库详情
        """
        try:
            resp = self.session.get(f"{self.base_url}/api/v1/datasets/{dataset_id}", timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"获取知识库详情失败: {e}")
            return {"code": -1, "message": str(e)}

    def update_dataset(
        self,
        dataset_id: str,
        name: str = None,
        description: str = None,
        embedding_model: str = None,
        chunk_method: str = None,
        extra_config: Dict = None,
    ) -> Dict:
        """
        更新知识库

        Args:
            dataset_id: 知识库 ID
            name: 知识库名称
            description: 描述
            embedding_model: 向量模型
            chunk_method: 分块方法 (naive/paper/qa/table等)
            extra_config: 额外配置，如 parser_config

        Returns:
            API 响应
        """
        try:
            payload = {}
            if name:
                payload["name"] = name
            if description:
                payload["description"] = description
            if embedding_model:
                payload["embedding_model"] = embedding_model
            if chunk_method:
                payload["chunk_method"] = chunk_method
            if extra_config:
                payload.update(extra_config)

            if not payload:
                return {"code": 0, "message": "无需更新"}

            logger.info(f"更新知识库配置: dataset_id={dataset_id}, payload={payload}")
            resp = self.session.put(f"{self.base_url}/api/v1/datasets/{dataset_id}", json=payload, timeout=self.timeout)
            resp.raise_for_status()
            result = resp.json()
            logger.info(f"更新知识库成功: {dataset_id}")
            return result
        except Exception as e:
            logger.error(f"更新知识库失败: {e}")
            return {"code": -1, "message": str(e)}

    def delete_dataset(self, dataset_id: str) -> Dict:
        """
        删除知识库

        Args:
            dataset_id: 知识库 ID

        Returns:
            API 响应
        """
        try:
            resp = self.session.delete(
                f"{self.base_url}/api/v1/datasets",
                json={"ids": [dataset_id]},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            result = resp.json() if resp.content else {"code": 0, "data": {"ids": [dataset_id]}}
            verify = self.get_dataset(dataset_id)
            if verify.get("code") == 0:
                logger.error(f"RAGFlow 知识库删除后仍可查询到，拒绝当作成功: {dataset_id}")
                return {"code": -1, "message": f"RAGFlow dataset still exists after delete: {dataset_id}"}
            logger.info(f"删除知识库成功: {dataset_id}")
            return result
        except Exception as e:
            logger.error(f"删除知识库失败: {e}")
            return {"code": -1, "message": str(e)}

    def get_or_create_dataset(self, name: str) -> Optional[str]:
        """
        获取或创建知识库

        Args:
            name: 知识库名称

        Returns:
            知识库 ID
        """
        # 先尝试查找
        result = self.list_datasets(name=name)
        if result.get("code") == 0:
            datasets = result.get("data", [])
            for ds in datasets:
                if ds.get("name") == name:
                    return ds.get("id")

        # 不存在则创建
        result = self.create_dataset(name, f"{name} - 自动创建")
        if result.get("code") == 0:
            return result.get("data", {}).get("id")

        return None

    # ==================== 文档管理 ====================

    def upload_document_content(self, dataset_id: str, title: str, content: str) -> Dict:
        """
        上传文本内容到知识库(创建为 txt 文档)

        Args:
            dataset_id: 知识库 ID
            title: 文档标题
            content: 文档内容

        Returns:
            API 响应
        """
        try:
            self.try_bind_dataset_embedding_model(dataset_id)
            self.ensure_dataset_chunk_method(dataset_id)

            # 创建临时文件内容
            file_content = f"# {title}\n\n{content}"
            file_name = f"{title[:50]}.txt"

            # 使用 multipart/form-data 上传
            files = {"file": (file_name, file_content.encode("utf-8"), "text/plain")}
            headers = {"Authorization": f"Bearer {self.api_key}"}

            resp = requests.post(
                f"{self.base_url}/api/v1/datasets/{dataset_id}/documents",
                files=files,
                headers=headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            result = resp.json()

            if result.get("code") == 0:
                logger.info(f"文档上传成功: {title}")
                # 触发解析
                doc_ids = self._extract_document_ids(result)
                if doc_ids:
                    self.parse_documents(dataset_id, doc_ids)

            return result

        except Exception as e:
            logger.error(f"上传文档失败: {e}")
            return {"code": -1, "message": str(e)}

    def upload_document_file(self, dataset_id: str, file_path: str, file_name: str = None) -> Dict:
        """
        上传二进制文件到知识库(支持PDF、Word、Excel等格式)

        Args:
            dataset_id: 知识库 ID
            file_path: 文件路径(绝对路径)
            file_name: 自定义文件名(可选,默认使用原文件名)

        Returns:
            API 响应
        """
        try:
            self.try_bind_dataset_embedding_model(dataset_id)
            self.ensure_dataset_chunk_method(dataset_id)

            import os
            from pathlib import Path

            file_path_obj = Path(file_path)
            if not file_path_obj.exists():
                return {"code": -1, "message": f"文件不存在: {file_path}"}

            # 使用自定义文件名或原文件名
            final_file_name = file_name or file_path_obj.name

            # 确定文件MIME类型
            mime_types = {
                ".pdf": "application/pdf",
                ".doc": "application/msword",
                ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ".xls": "application/vnd.ms-excel",
                ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ".txt": "text/plain",
                ".md": "text/markdown",
                ".html": "text/html",
                ".htm": "text/html",
            }
            content_type = mime_types.get(file_path_obj.suffix.lower(), "application/octet-stream")

            # 读取二进制文件
            with open(file_path, "rb") as f:
                file_content = f.read()

            # 使用 multipart/form-data 上传二进制文件
            files = {"file": (final_file_name, file_content, content_type)}
            headers = {"Authorization": f"Bearer {self.api_key}"}

            resp = requests.post(
                f"{self.base_url}/api/v1/datasets/{dataset_id}/documents",
                files=files,
                headers=headers,
                timeout=self.timeout * 2,  # 文件上传可能需要更长时间
            )
            resp.raise_for_status()
            result = resp.json()

            if result.get("code") == 0:
                logger.info(f"文件上传成功: {final_file_name}")
                # 触发解析
                doc_ids = self._extract_document_ids(result)
                if doc_ids:
                    self.parse_documents(dataset_id, doc_ids)

            return result

        except Exception as e:
            logger.error(f"上传文件失败: {e}")
            return {"code": -1, "message": str(e)}

    def upload_document_bytes(
        self, dataset_id: str, file_content: bytes, file_name: str, content_type: str = None, do_parse: bool = True
    ) -> Dict:
        """
        上传二进制内容到知识库(用于直接上传内存中的文件)

        Args:
            dataset_id: 知识库 ID
            file_content: 文件二进制内容
            file_name: 文件名
            content_type: MIME类型(可选)
            do_parse: 是否自动触发解析 (默认True)

        Returns:
            API 响应
        """
        try:
            self.try_bind_dataset_embedding_model(dataset_id)
            self.ensure_dataset_chunk_method(dataset_id)

            from pathlib import Path

            # 确定文件MIME类型
            if not content_type:
                mime_types = {
                    ".pdf": "application/pdf",
                    ".doc": "application/msword",
                    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ".xls": "application/vnd.ms-excel",
                    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ".txt": "text/plain",
                    ".md": "text/markdown",
                    ".html": "text/html",
                    ".htm": "text/html",
                }
                content_type = mime_types.get(Path(file_name).suffix.lower(), "application/octet-stream")

            # 使用 multipart/form-data 上传二进制文件
            files = {"file": (file_name, file_content, content_type)}
            headers = {"Authorization": f"Bearer {self.api_key}"}

            # PDF 文件可能较大，增加超时
            upload_timeout = self.timeout * 4 if Path(file_name).suffix.lower() == ".pdf" else self.timeout * 2

            resp = requests.post(
                f"{self.base_url}/api/v1/datasets/{dataset_id}/documents",
                files=files,
                headers=headers,
                timeout=upload_timeout,
            )
            resp.raise_for_status()
            result = resp.json()

            if result.get("code") == 0:
                logger.info(f"二进制内容上传成功: {file_name}")
                if do_parse:
                    doc_ids = self._extract_document_ids(result)
                    if doc_ids:
                        # 触发解析前再次确保配置正确
                        try:
                            self.try_bind_dataset_embedding_model(dataset_id)
                            self.ensure_dataset_chunk_method(dataset_id)
                        except Exception as config_err:
                            logger.warning(f"解析前配置检查失败（继续尝试解析）: {config_err}")

                        parse_result = self.parse_documents(dataset_id, doc_ids)
                        if parse_result.get("code") != 0:
                            logger.warning(
                                f"文档上传成功但解析触发失败: file={file_name}, doc_ids={doc_ids}, "
                                f"parse_error={parse_result.get('message')}"
                            )
                            # 将解析错误信息加入返回结果
                            result["parse_warning"] = parse_result.get("message")
                        else:
                            logger.info(f"文档上传并解析成功: file={file_name}, doc_ids={doc_ids}")
                else:
                    logger.info(f"用户选择不自动解析文档: {file_name}")

            return result

        except requests.exceptions.Timeout:
            logger.error(f"上传文件超时（{upload_timeout}s）: {file_name}")
            return {"code": -1, "message": "上传超时（文件可能较大），请稍后重试或尝试更小的文件"}
        except Exception as e:
            logger.error(f"上传二进制内容失败: {e}")
            return {"code": -1, "message": str(e)}

    def parse_documents(self, dataset_id: str, document_ids: List[str]) -> Dict:
        """
        触发文档解析(分块)

        Args:
            dataset_id: 知识库 ID
            document_ids: 文档 ID 列表

        Returns:
            API 响应
        """
        document_ids = [str(doc_id) for doc_id in document_ids if doc_id]
        if not document_ids:
            return {"code": 0, "message": "没有需要解析的文档", "data": []}

        # 确保 dataset 配置正确（embedding model 和 chunk_method）
        try:
            self.try_bind_dataset_embedding_model(dataset_id)
            self.ensure_dataset_chunk_method(dataset_id)
        except Exception as e:
            logger.warning(f"解析前确保 dataset 配置失败（继续尝试解析）: {e}")

        try:
            resp = self.session.post(
                f"{self.base_url}/api/v1/datasets/{dataset_id}/chunks",
                json={"document_ids": document_ids},
                timeout=self.parse_timeout,
            )
            resp.raise_for_status()
            result = resp.json()

            # 检查返回 code
            if result.get("code") != 0:
                logger.error(f"文档解析 API 返回错误: code={result.get('code')}, message={result.get('message')}, document_ids={document_ids}")
                return result

            logger.info(f"文档解析已触发: {len(document_ids)} 个文档")
            return result
        except requests.exceptions.Timeout:
            logger.warning(f"文档解析请求超时（{self.parse_timeout}s），文档可能已在后台开始解析: {document_ids}")
            # 超时不代表失败，RAGFlow 可能在后台继续处理
            return {"code": 0, "message": "解析请求已发送，文档可能正在后台处理"}
        except Exception as e:
            logger.warning(f"标准文档解析接口失败，尝试兼容接口 /api/v1/document/run: {e}")

        try:
            resp = self.session.post(
                f"{self.base_url}/api/v1/document/run",
                json={"doc_ids": document_ids},
                timeout=self.parse_timeout,
            )
            resp.raise_for_status()
            result = resp.json()

            # 检查返回 code
            if result.get("code") != 0:
                logger.error(f"文档解析（兼容接口）返回错误: code={result.get('code')}, message={result.get('message')}, document_ids={document_ids}")
                return result

            logger.info(f"文档解析已通过兼容接口触发: {len(document_ids)} 个文档")
            return result
        except requests.exceptions.Timeout:
            logger.warning(f"文档解析（兼容接口）请求超时（{self.parse_timeout}s），文档可能已在后台开始解析: {document_ids}")
            return {"code": 0, "message": "解析请求已发送，文档可能正在后台处理"}
        except Exception as e:
            logger.error(f"文档解析失败: {e}")
            return {"code": -1, "message": str(e)}

    def get_document(self, dataset_id: str, document_id: str) -> Dict:
        """
        获取文档详情

        Args:
            dataset_id: 知识库 ID
            document_id: 文档 ID

        Returns:
            文档详情
        """
        try:
            resp = self.session.get(
                f"{self.base_url}/api/v1/datasets/{dataset_id}/documents/{document_id}", timeout=self.timeout
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"获取文档详情失败: {e}")
            return {"code": -1, "message": str(e)}

    def get_document_parsing_status(self, dataset_id: str, document_id: str) -> Dict[str, Any]:
        """
        获取文档解析状态

        Args:
            dataset_id: 知识库 ID
            document_id: 文档 ID

        Returns:
            {
                "status": "unstart" | "running" | "done" | "fail" | "unknown",
                "progress": float,  # 0.0 - 1.0
                "message": str,
                "is_ready": bool,  # 是否可以用于检索
            }
        """
        try:
            doc_result = self.get_document(dataset_id, document_id)
            if doc_result.get("code") != 0:
                return {
                    "status": "unknown",
                    "progress": 0.0,
                    "message": doc_result.get("message", "获取文档状态失败"),
                    "is_ready": False,
                }

            data = doc_result.get("data", {})
            if isinstance(data, dict):
                # RAGFlow 文档状态：UNSTART=0, RUNNING=1, DONE=2, CANCEL=3, FAIL=4
                status_raw = data.get("status")
                status_str = str(status_raw).upper() if status_raw else "UNKNOWN"

                # 解析状态映射
                status_map = {
                    "0": "unstart",
                    "UNSTART": "unstart",
                    "1": "running",
                    "RUNNING": "running",
                    "2": "done",
                    "DONE": "done",
                    "3": "cancel",
                    "CANCEL": "cancel",
                    "4": "fail",
                    "FAIL": "fail",
                }
                status = status_map.get(status_str, "unknown")

                # 进度（仅 RAGFlow 返回）
                progress = float(data.get("progress", 0.0)) if status == "running" else (1.0 if status == "done" else 0.0)

                # 错误信息
                error_msg = data.get("error_msg") or data.get("message", "")
                if status == "fail" and error_msg:
                    message = f"解析失败: {error_msg}"
                elif status == "running":
                    message = f"解析中... {int(progress * 100)}%"
                elif status == "done":
                    message = "解析完成"
                elif status == "unstart":
                    message = "等待解析"
                else:
                    message = error_msg or "状态未知"

                return {
                    "status": status,
                    "progress": progress,
                    "message": message,
                    "is_ready": status == "done",
                    "raw_status": status_raw,
                }

            return {
                "status": "unknown",
                "progress": 0.0,
                "message": "文档数据格式异常",
                "is_ready": False,
            }

        except Exception as e:
            logger.error(f"获取文档解析状态失败: {e}")
            return {
                "status": "unknown",
                "progress": 0.0,
                "message": str(e),
                "is_ready": False,
            }

    def get_documents_parsing_status(self, dataset_id: str, document_ids: List[str]) -> Dict[str, Any]:
        """
        批量获取文档解析状态

        Args:
            dataset_id: 知识库 ID
            document_ids: 文档 ID 列表

        Returns:
            {
                "total": int,
                "done": int,
                "running": int,
                "failed": int,
                "unstart": int,
                "is_ready": bool,  # 全部完成才算就绪
                "documents": [...],  # 每个文档的状态详情
            }
        """
        if not document_ids:
            return {"total": 0, "done": 0, "running": 0, "failed": 0, "unstart": 0, "is_ready": True, "documents": []}

        documents_status = []
        counts = {"done": 0, "running": 0, "failed": 0, "unstart": 0, "unknown": 0}

        for doc_id in document_ids:
            status_info = self.get_document_parsing_status(dataset_id, doc_id)
            documents_status.append({"document_id": doc_id, **status_info})
            counts[status_info["status"]] = counts.get(status_info["status"], 0) + 1

        return {
            "total": len(document_ids),
            "done": counts["done"],
            "running": counts["running"],
            "failed": counts["failed"],
            "unstart": counts["unstart"],
            "unknown": counts.get("unknown", 0),
            "is_ready": counts["done"] == len(document_ids) and counts["failed"] == 0,
            "documents": documents_status,
        }

    def get_document_content(self, dataset_id: str, document_id: str) -> Dict:
        """
        获取文档内容（通过 chunks API 直接获取，而非依赖 retrieve 检索）

        Args:
            dataset_id: 知识库 ID
            document_id: 文档 ID

        Returns:
            文档内容
        """
        try:
            # 方案1：直接通过 chunks API 获取文档的所有分块内容
            resp = self.session.get(
                f"{self.base_url}/api/v1/datasets/{dataset_id}/chunks",
                params={"document_id": document_id, "page": 1, "size": 100},
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                result = resp.json()
                if result.get("code") == 0:
                    chunks = result.get("data", {}).get("chunks", [])
                    if chunks:
                        # 按 chunk_id 排序后拼接，保持原文顺序
                        chunks_sorted = sorted(chunks, key=lambda c: c.get("chunk_id", 0))
                        content = "\n\n".join(chunk.get("content", "") for chunk in chunks_sorted if chunk.get("content"))
                        title = chunks[0].get("document_name", "") if chunks else ""
                        if content:
                            return {"code": 0, "data": {"content": content, "title": title}}

            # 方案2（兜底）：通过文档详情 API 获取元数据，再尝试检索
            doc_result = self.get_document(dataset_id, document_id)
            if doc_result.get("code") == 0:
                doc_info = doc_result.get("data", {})
                # 检查文档状态：UNSTART=未开始, RUNNING=解析中, DONE=已完成, CANCEL=已取消, FAIL=失败
                status = str(doc_info.get("status", "")).upper()
                if status in ("RUNNING", "1", "UNSTART", "0"):
                    return {"code": -1, "message": f"文档仍在解析中(status={status})，请稍后再试"}

            return {"code": -1, "message": "文档内容获取失败"}
        except Exception as e:
            logger.error(f"获取文档内容失败: {e}")
            return {"code": -1, "message": str(e)}

    def update_document(self, dataset_id: str, document_id: str, title: str = None, content: str = None) -> Dict:
        """
        更新文档(通过删除旧文档并创建新文档实现)

        Args:
            dataset_id: 知识库 ID
            document_id: 文档 ID
            title: 新标题
            content: 新内容

        Returns:
            API 响应
        """
        try:
            # 先删除旧文档
            delete_result = self.delete_document(dataset_id, document_id)
            if delete_result.get("code") != 0:
                logger.warning(f"删除旧文档失败,可能文档不存在: {document_id}")

            # 创建新文档
            if title and content:
                new_result = self.upload_document_content(dataset_id, title, content)
                if new_result.get("code") == 0:
                    logger.info(f"更新文档成功: {title}")
                    return new_result

            return {"code": -1, "message": "更新文档失败"}
        except Exception as e:
            logger.error(f"更新文档失败: {e}")
            return {"code": -1, "message": str(e)}

    def delete_document(self, dataset_id: str, document_id: str) -> Dict:
        """
        删除文档

        Args:
            dataset_id: 知识库 ID
            document_id: 文档 ID

        Returns:
            API 响应
        """
        try:
            resp = self.session.delete(
                f"{self.base_url}/api/v1/datasets/{dataset_id}/documents",
                json={"ids": [document_id]},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            result = resp.json() if resp.content else {"code": 0, "data": {"ids": [document_id]}}
            logger.info(f"删除文档成功: {document_id}")
            return result
        except Exception as e:
            logger.error(f"删除文档失败: {e}")
            return {"code": -1, "message": str(e)}

    def list_documents(self, dataset_id: str, **kwargs) -> Dict:
        """
        列出知识库中的文档

        Args:
            dataset_id: 知识库 ID
            **kwargs: 其他查询参数

        Returns:
            文档列表
        """
        try:
            resp = self.session.get(
                f"{self.base_url}/api/v1/datasets/{dataset_id}/documents", params=kwargs, timeout=self.timeout
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"列出文档失败: {e}")
            return {"code": -1, "message": str(e)}

    # ==================== 检索(去重核心)====================

    def retrieve(
        self, question: str, dataset_ids: List[str], similarity_threshold: float = 0.85, top_k: int = 1024
    ) -> Dict:
        """
        检索相似内容(用于去重)

        Args:
            question: 待检测的文章内容摘要
            dataset_ids: 知识库 ID 列表
            similarity_threshold: 相似度阈值,0-1 之间
            top_k: 候选数量

        Returns:
            检索结果
        """
        try:
            resp = self.session.post(
                f"{self.base_url}/api/v1/retrieval",
                json={
                    "question": question,
                    "dataset_ids": dataset_ids,
                    "similarity_threshold": similarity_threshold,
                    "vector_similarity_weight": 0.5,
                    "top_k": top_k,
                    "keyword": True,
                    "highlight": True,
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"检索失败: {e}")
            return {"code": -1, "message": str(e)}

    def check_duplicate(
        self, content: str, dataset_ids: List[str] = None, threshold: float = 0.85
    ) -> Tuple[bool, List[Dict]]:
        """
        检查文章是否重复

        Args:
            content: 文章内容
            dataset_ids: 知识库 ID 列表(默认使用配置的 dataset_id)
            threshold: 相似度阈值

        Returns:
            (is_duplicate, similar_articles): 是否重复及相似文章列表
        """
        if not dataset_ids:
            dataset_ids = [self.dataset_id] if self.dataset_id else []

        if not dataset_ids:
            logger.warning("未配置知识库 ID,跳过去重检测")
            return False, []

        # 生成内容摘要(取前500字符)
        summary = content[:500] if len(content) > 500 else content
        logger.debug(f"去重检索摘要: {summary[:50]}...")
        logger.debug(f"检索阈值: {threshold}, 知识库: {dataset_ids}")

        result = self.retrieve(summary, dataset_ids, similarity_threshold=threshold)

        if result.get("code") != 0:
            logger.warning(f"去重检测失败: {result.get('message')}")
            return False, []

        chunks = result.get("data", {}).get("chunks", [])
        similar_chunks = [c for c in chunks if c.get("similarity", 0) >= threshold]

        if not similar_chunks:
            return False, []

        # 按文档聚合
        articles = {}
        for chunk in similar_chunks:
            doc_id = chunk.get("document_id")
            if not doc_id:
                continue

            if doc_id not in articles:
                articles[doc_id] = {
                    "document_id": doc_id,
                    "document_name": chunk.get("document_name") or chunk.get("docname") or f"Doc_{doc_id[:8]}",
                    "max_similarity": chunk.get("similarity"),
                    "similar_content": chunk.get("content", "")[:200],
                }
            articles[doc_id]["max_similarity"] = max(articles[doc_id]["max_similarity"], chunk.get("similarity", 0))

        return True, list(articles.values())

    # ==================== 聊天(文章生成)====================

    def create_chat(self, name: str, dataset_ids: List[str], system_prompt: str = None) -> Dict:
        """
        创建聊天助手

        Args:
            name: 助手名称
            dataset_ids: 关联的知识库 ID 列表
            system_prompt: 系统提示词

        Returns:
            API 响应
        """
        payload = {"name": name, "dataset_ids": dataset_ids}
        if system_prompt:
            payload["prompt"] = [{"role": "system", "content": system_prompt}]

        try:
            resp = self.session.post(f"{self.base_url}/api/v1/chats", json=payload, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"创建聊天助手失败: {e}")
            return {"code": -1, "message": str(e)}

    def chat_completion(self, chat_id: str, question: str, stream: bool = False) -> Dict:
        """
        发送对话请求

        Args:
            chat_id: 聊天助手 ID
            question: 问题/提示
            stream: 是否流式返回

        Returns:
            API 响应
        """
        try:
            resp = self.session.post(
                f"{self.base_url}/api/v1/chats/{chat_id}/completions",
                json={"question": question, "stream": stream},
                timeout=self.timeout * 2,  # 对话可能需要更长时间
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"对话请求失败: {e}")
            return {"code": -1, "message": str(e)}


# 全局单例
_ragflow_client: Optional[RAGFlowClient] = None


def get_ragflow_client() -> RAGFlowClient:
    """获取 RAGFlow 客户端单例"""
    global _ragflow_client
    if _ragflow_client is None:
        from backend.config import RAGFLOW_BASE_URL, RAGFLOW_API_KEY

        _ragflow_client = RAGFlowClient(base_url=RAGFLOW_BASE_URL, api_key=RAGFLOW_API_KEY)
    return _ragflow_client
