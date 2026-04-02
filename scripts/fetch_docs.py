"""
飞书文档获取脚本
支持文件夹和 Wiki 知识库两种模式
通过飞书开放平台 API 获取文档列表和内容
"""

import os
import time
import json
from collections import deque
from typing import Dict, List, Optional

import requests


class FeishuClient:
    """飞书 API 客户端"""

    BASE_URL = "https://open.feishu.cn/open-apis"

    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self.app_access_token = None
        self.token_expires_at = 0

    def _get_app_access_token(self) -> str:
        """获取 App Access Token"""
        current_time = time.time()
        if self.app_access_token and current_time < self.token_expires_at - 60:
            return self.app_access_token

        url = f"{self.BASE_URL}/auth/v3/app_access_token/internal"
        payload = {
            "app_id": self.app_id,
            "app_secret": self.app_secret,
        }

        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()

        if data.get("code") != 0:
            raise Exception(f"Failed to get app access token: {data}")

        self.app_access_token = data["app_access_token"]
        self.token_expires_at = current_time + 7200
        return self.app_access_token

    def _request(self, method: str, path: str, **kwargs) -> Dict:
        """发起 API 请求"""
        token = self._get_app_access_token()
        headers = kwargs.get("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        kwargs["headers"] = headers
        kwargs.setdefault("timeout", 30)

        url = f"{self.BASE_URL}{path}"
        response = requests.request(method, url, **kwargs)

        if response.status_code == 429 or response.status_code >= 500:
            time.sleep(5)
            response = requests.request(method, url, **kwargs)

        response.raise_for_status()
        data = response.json()

        if data.get("code") != 0:
            raise Exception(f"API error: {data}")

        return data.get("data", {})

    def _raw_request(self, method: str, path: str, **kwargs) -> requests.Response:
        """发起 API 请求，返回原始响应（用于处理非 JSON 响应）"""
        token = self._get_app_access_token()
        headers = kwargs.get("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        kwargs["headers"] = headers
        kwargs.setdefault("timeout", 30)

        url = f"{self.BASE_URL}{path}"
        return requests.request(method, url, **kwargs)

    def get_wiki_node(self, node_token: str) -> Dict:
        """获取 Wiki 节点信息"""
        return self._request(
            "GET",
            f"/wiki/v2/spaces/get_node?token={node_token}",
        )

    def get_wiki_children(self, space_id: str, parent_node_token: str = "") -> List[Dict]:
        """获取某个父节点的直属子节点，自动处理分页"""
        all_nodes = []
        page_token = None

        while True:
            params = {"page_size": 50}
            if page_token:
                params["page_token"] = page_token
            if parent_node_token:
                params["parent_node_token"] = parent_node_token

            data = self._request(
                "GET",
                f"/wiki/v2/spaces/{space_id}/nodes",
                params=params,
            )

            items = data.get("items", [])
            all_nodes.extend(items)

            if not data.get("has_more"):
                break

            page_token = data.get("page_token")
            time.sleep(0.1)

        return all_nodes

    def _should_probe_wiki_node_children(self, node: Dict) -> bool:
        """判断是否需要继续探测该节点的子节点"""
        node_token = node.get("node_token")
        if not node_token:
            return False

        # 为了避免漏掉整片子树，这里不完全信任 has_child。
        # 即便返回 False/None，也对每个 node_token 主动探测一次。
        return True

    def get_all_wiki_nodes_recursive(
        self,
        space_id: str,
        root_token: str = "",
        root_node: Optional[Dict] = None,
    ) -> List[Dict]:
        """递归获取 Wiki 空间下所有节点（所有层级）"""
        all_nodes = []
        seen_tokens = set()
        queued_tokens = set()
        fetched_parent_tokens = set()
        to_fetch = deque()

        if root_token:
            root_node = dict(root_node or self.get_wiki_node(root_token).get("node", {}))
            root_node_token = root_node.get("node_token") or root_token

            if root_node_token:
                root_node.setdefault("node_token", root_node_token)
                all_nodes.append(root_node)
                seen_tokens.add(root_node_token)
                to_fetch.append(root_node_token)
                queued_tokens.add(root_node_token)
        else:
            to_fetch.append("")
            queued_tokens.add("")

        while to_fetch:
            parent_token = to_fetch.popleft()
            if parent_token in fetched_parent_tokens:
                continue

            fetched_parent_tokens.add(parent_token)
            print(
                f"  [RECURSIVE] Fetching children of: {parent_token or '(root)'}, "
                f"queue size: {len(to_fetch)}, total found: {len(all_nodes)}"
            )

            try:
                children = self.get_wiki_children(space_id, parent_token)
            except Exception as e:
                print(f"  [RECURSIVE] Failed to fetch children of {parent_token or '(root)'}: {e}")
                continue

            print(f"  [RECURSIVE] Got {len(children)} children")

            for child in children:
                child_token = child.get("node_token")
                child_title = child.get("title", "")[:30]
                child_has_child = child.get("has_child")
                child_obj_type = child.get("obj_type")
                print(
                    f"    [RECURSIVE]   - {child_token} | {child_title} | "
                    f"has_child={child_has_child} | type={child_obj_type}"
                )

                if child_token and child_token not in seen_tokens:
                    all_nodes.append(child)
                    seen_tokens.add(child_token)

                if (
                    child_token
                    and child_token not in queued_tokens
                    and child_token not in fetched_parent_tokens
                    and self._should_probe_wiki_node_children(child)
                ):
                    to_fetch.append(child_token)
                    queued_tokens.add(child_token)

            if children:
                time.sleep(0.2)

        print(f"  [RECURSIVE] Total nodes collected: {len(all_nodes)}")
        return all_nodes

    def get_doc_raw_content(self, doc_token: str) -> str:
        """获取文档原始内容（使用 raw_content API）"""
        resp = self._raw_request(
            "GET",
            f"/docx/v1/documents/{doc_token}/raw_content",
        )

        if resp.status_code == 404:
            return ""

        data = resp.json()
        if data.get("code") != 0:
            return ""

        return data.get("data", {}).get("content", "")

    def get_doc_meta(self, doc_token: str) -> Dict:
        """获取文档元信息（可能返回 404，使用 wiki 节点信息作为备选）"""
        try:
            return self._request(
                "GET",
                f"/docx/v1/documents/{doc_token}/meta",
            )
        except Exception:
            return {}


def fetch_wiki_docs(app_id: str, app_secret: str, wiki_token: str) -> List[Dict]:
    """从 Wiki 知识库获取所有文档"""
    client = FeishuClient(app_id, app_secret)

    wiki_tokens = [t.strip() for t in wiki_token.split(",") if t.strip()]
    print(f"Fetching {len(wiki_tokens)} wiki(s)")

    all_results = []
    seen_doc_ids = set()

    for i, token in enumerate(wiki_tokens):
        print(f"\n[{i + 1}/{len(wiki_tokens)}] Processing wiki: {token}")

        try:
            root = client.get_wiki_node(token)
            root_node = root.get("node", {})
            space_id = root_node.get("space_id")
            root_title = root_node.get("title", "Wiki Root")
        except Exception as e:
            print(f"  Failed to get wiki node: {e}")
            continue

        print(f"  Wiki space ID: {space_id}")
        print(f"  Root node: {root_title}")

        print("  Fetching all nodes in wiki space (recursive)...")
        try:
            all_nodes = client.get_all_wiki_nodes_recursive(space_id, token, root_node)
            print(f"  Found {len(all_nodes)} nodes total")
        except Exception as e:
            print(f"  Failed to get children: {e}")
            continue

        doc_nodes = []
        type_stats = {}
        for node in all_nodes:
            obj_type = node.get("obj_type", "unknown")
            type_stats[obj_type] = type_stats.get(obj_type, 0) + 1

            if obj_type in {"doc", "docx"}:
                doc_nodes.append(
                    {
                        "node_token": node.get("node_token"),
                        "parent_node_token": node.get("parent_node_token"),
                        "obj_token": node.get("obj_token"),
                        "title": node.get("title"),
                        "has_child": node.get("has_child", False),
                        "obj_edit_time": node.get("obj_edit_time"),
                        "space_id": space_id,
                        "type": obj_type,
                        "wiki_token": token,
                    }
                )

        print(f"  Node type distribution: {type_stats}")
        print(f"  Found {len(doc_nodes)} documents")

        for j, doc in enumerate(doc_nodes):
            doc_id = doc.get("obj_token")
            if not doc_id:
                print(f"  [{j + 1}/{len(doc_nodes)}] Skip node without obj_token: {doc.get('title')}")
                continue

            if doc_id in seen_doc_ids:
                print(f"  [{j + 1}/{len(doc_nodes)}] Skip duplicate: {doc['title']}")
                continue

            print(f"  [{j + 1}/{len(doc_nodes)}] Fetching: {doc['title']}")

            try:
                meta = client.get_doc_meta(doc_id)
                raw_content = client.get_doc_raw_content(doc_id)

                all_results.append(
                    {
                        "node_token": doc["node_token"],
                        "parent_node_token": doc.get("parent_node_token"),
                        "id": doc_id,
                        "title": doc["title"],
                        "type": doc["type"],
                        "meta": meta,
                        "raw_content": raw_content,
                        "updated_at": meta.get("document", {}).get("updated_at") or doc.get("obj_edit_time"),
                        "space_id": doc.get("space_id"),
                        "wiki_token": doc["wiki_token"],
                    }
                )
                seen_doc_ids.add(doc_id)
                time.sleep(0.2)
            except Exception as e:
                print(f"    Error fetching {doc['title']}: {e}")
                continue

    return all_results


def fetch_folder_docs(app_id: str, app_secret: str, folder_token: str) -> List[Dict]:
    """从文件夹获取文档（兼容旧模式）"""
    client = FeishuClient(app_id, app_secret)

    print(f"Fetching document list from folder: {folder_token}")
    docs = client.get_folder_docs(folder_token)
    print(f"Found {len(docs)} documents")

    results = []
    for i, doc in enumerate(docs):
        print(f"[{i + 1}/{len(docs)}] Fetching: {doc['name']}")

        try:
            meta = client.get_doc_meta(doc["token"])
            raw_content = client.get_doc_raw_content(doc["token"])

            results.append(
                {
                    "id": doc["token"],
                    "title": doc["name"],
                    "type": doc["type"],
                    "meta": meta,
                    "raw_content": raw_content,
                    "updated_at": meta.get("document", {}).get("updated_at"),
                }
            )

            time.sleep(0.2)
        except Exception as e:
            print(f"  Error fetching {doc['name']}: {e}")
            continue

    return results


fetch_all_docs = fetch_wiki_docs


if __name__ == "__main__":
    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")
    wiki_token = os.environ.get("FEISHU_WIKI_TOKEN") or os.environ.get("FEISHU_FOLDER_TOKEN")

    if not all([app_id, app_secret, wiki_token]):
        print("Error: Missing required environment variables")
        print("Need: FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_WIKI_TOKEN (or FEISHU_FOLDER_TOKEN)")
        raise SystemExit(1)

    docs = fetch_all_docs(app_id, app_secret, wiki_token)
    print(f"\nSuccessfully fetched {len(docs)} documents")

    for doc in docs:
        print(f"  - {doc['title']}: {len(doc.get('raw_content', ''))} chars")
