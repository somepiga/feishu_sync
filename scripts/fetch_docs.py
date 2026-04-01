"""
飞书文档获取脚本
支持文件夹和 Wiki 知识库两种模式
通过飞书开放平台 API 获取文档列表和内容
"""

import os
import time
import json
import requests
from typing import List, Dict, Optional


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
            "app_secret": self.app_secret
        }

        response = requests.post(url, json=payload)
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

        url = f"{self.BASE_URL}{path}"
        return requests.request(method, url, **kwargs)

    def get_wiki_node(self, node_token: str) -> Dict:
        """获取 Wiki 节点信息"""
        return self._request(
            "GET",
            f"/wiki/v2/spaces/get_node?token={node_token}"
        )

    def get_wiki_children(self, space_id: str, parent_node_token: str = "") -> List[Dict]:
        """递归获取 Wiki 空间下所有层级的节点"""
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
                params=params
            )

            items = data.get("items", [])
            all_nodes.extend(items)

            if not data.get("has_more"):
                break

            page_token = data.get("page_token")
            time.sleep(0.1)

        return all_nodes

    def get_all_wiki_nodes_recursive(self, space_id: str, root_token: str = "") -> List[Dict]:
        """递归获取 Wiki 空间下所有节点（所有层级）"""
        all_nodes = []
        to_fetch = [root_token] if root_token else [""]

        while to_fetch:
            parent_token = to_fetch.pop(0)
            children = self.get_wiki_children(space_id, parent_token)
            all_nodes.extend(children)

            # 对于有子节点的节点，加入待处理队列
            for child in children:
                if child.get("has_child"):
                    child_node_token = child.get("node_token")
                    if child_node_token and child_node_token not in [n.get("node_token") for n in all_nodes if n.get("node_token")]:
                        to_fetch.append(child_node_token)

            if children:
                time.sleep(0.2)

        return all_nodes

    def get_doc_raw_content(self, doc_token: str) -> str:
        """获取文档原始内容（使用 raw_content API）"""
        resp = self._raw_request(
            "GET",
            f"/docx/v1/documents/{doc_token}/raw_content"
        )

        if resp.status_code == 404:
            return ""

        data = resp.json()
        if data.get("code") != 0:
            return ""

        return data.get("data", {}).get("content", "")

    def get_doc_meta(self, doc_token: str) -> Dict:
        """获取文档元信息（可能返回404，使用 wiki 节点信息作为备选）"""
        try:
            data = self._request(
                "GET",
                f"/docx/v1/documents/{doc_token}/meta"
            )
            return data
        except Exception:
            return {}


def fetch_wiki_docs(app_id: str, app_secret: str, wiki_token: str) -> List[Dict]:
    """从 Wiki 知识库获取所有文档"""
    client = FeishuClient(app_id, app_secret)

    # 支持逗号分隔的多个 wiki token
    wiki_tokens = [t.strip() for t in wiki_token.split(",") if t.strip()]
    print(f"Fetching {len(wiki_tokens)} wiki(s)")

    all_results = []
    for i, token in enumerate(wiki_tokens):
        print(f"\n[{i+1}/{len(wiki_tokens)}] Processing wiki: {token}")

        # 获取根节点信息
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

        # 获取所有子节点（递归）
        print(f"  Fetching all nodes in wiki space (recursive)...")
        try:
            all_nodes = client.get_all_wiki_nodes_recursive(space_id, token)
            print(f"  Found {len(all_nodes)} nodes total")
        except Exception as e:
            print(f"  Failed to get children: {e}")
            continue

        # 筛选出文档类型的节点
        doc_nodes = []
        for node in all_nodes:
            if node.get("obj_type") == "docx":
                doc_nodes.append({
                    "node_token": node.get("node_token"),
                    "obj_token": node.get("obj_token"),
                    "title": node.get("title"),
                    "has_child": node.get("has_child", False),
                    "obj_edit_time": node.get("obj_edit_time"),
                    "wiki_token": token  # 记录来源
                })

        print(f"  Found {len(doc_nodes)} documents")

        # 获取每个文档的内容
        for j, doc in enumerate(doc_nodes):
            print(f"  [{j+1}/{len(doc_nodes)}] Fetching: {doc['title']}")

            try:
                meta = client.get_doc_meta(doc["obj_token"])
                raw_content = client.get_doc_raw_content(doc["obj_token"])

                all_results.append({
                    "node_token": doc["node_token"],
                    "id": doc["obj_token"],
                    "title": doc["title"],
                    "type": "docx",
                    "meta": meta,
                    "raw_content": raw_content,
                    "updated_at": meta.get("document", {}).get("updated_at") or doc.get("obj_edit_time"),
                    "wiki_token": doc["wiki_token"]
                })

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
        print(f"[{i+1}/{len(docs)}] Fetching: {doc['name']}")

        try:
            meta = client.get_doc_meta(doc["token"])
            raw_content = client.get_doc_raw_content(doc["token"])

            results.append({
                "id": doc["token"],
                "title": doc["name"],
                "type": doc["type"],
                "meta": meta,
                "raw_content": raw_content,
                "updated_at": meta.get("document", {}).get("updated_at")
            })

            time.sleep(0.2)

        except Exception as e:
            print(f"  Error fetching {doc['name']}: {e}")
            continue

    return results


# 兼容旧的函数名
fetch_all_docs = fetch_wiki_docs


if __name__ == "__main__":
    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")
    wiki_token = os.environ.get("FEISHU_WIKI_TOKEN") or os.environ.get("FEISHU_FOLDER_TOKEN")

    if not all([app_id, app_secret, wiki_token]):
        print("Error: Missing required environment variables")
        print("Need: FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_WIKI_TOKEN (or FEISHU_FOLDER_TOKEN)")
        exit(1)

    docs = fetch_all_docs(app_id, app_secret, wiki_token)
    print(f"\nSuccessfully fetched {len(docs)} documents")

    for doc in docs:
        print(f"  - {doc['title']}: {len(doc.get('raw_content', ''))} chars")
