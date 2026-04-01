"""
飞书文档获取脚本
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
        # token 有效期 2 小时，设置为 1.8 小时刷新
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

        # 如果是 429 或 5xx，等待后重试
        if response.status_code == 429 or response.status_code >= 500:
            time.sleep(5)
            response = requests.request(method, url, **kwargs)

        response.raise_for_status()
        data = response.json()

        if data.get("code") != 0:
            raise Exception(f"API error: {data}")

        return data.get("data", {})

    def get_folder_docs(self, folder_token: str) -> List[Dict]:
        """获取文件夹中的文档列表"""
        docs = []
        page_token = None

        while True:
            params = {"page_size": 50}
            if page_token:
                params["page_token"] = page_token

            data = self._request(
                "GET",
                f"/drive/v1/files?folder_token={folder_token}",
                params=params
            )

            files = data.get("files", [])
            for f in files:
                if f.get("type") in ["docx", "doc"]:
                    docs.append({
                        "token": f.get("token"),
                        "name": f.get("name"),
                        "type": f.get("type")
                    })

            page_token = data.get("page_token")
            if not page_token or not data.get("has_more"):
                break

            time.sleep(0.1)  # 避免请求过快

        return docs

    def get_doc_content(self, doc_token: str) -> Dict:
        """获取文档内容"""
        data = self._request(
            "GET",
            f"/docx/v1/documents/{doc_token}/content"
        )
        return data

    def get_doc_meta(self, doc_token: str) -> Dict:
        """获取文档元信息"""
        data = self._request(
            "GET",
            f"/docx/v1/documents/{doc_token}/meta"
        )
        return data


def fetch_all_docs(app_id: str, app_secret: str, folder_token: str) -> List[Dict]:
    """获取所有文档"""
    client = FeishuClient(app_id, app_secret)

    print(f"Fetching document list from folder: {folder_token}")
    docs = client.get_folder_docs(folder_token)
    print(f"Found {len(docs)} documents")

    results = []
    for i, doc in enumerate(docs):
        print(f"[{i+1}/{len(docs)}] Fetching: {doc['name']}")

        try:
            meta = client.get_doc_meta(doc["token"])
            content = client.get_doc_content(doc["token"])

            results.append({
                "id": doc["token"],
                "title": doc["name"],
                "type": doc["type"],
                "meta": meta,
                "content": content,
                "updated_at": meta.get("document", {}).get("updated_at")
            })

            time.sleep(0.2)  # 避免请求过快

        except Exception as e:
            print(f"  Error fetching {doc['name']}: {e}")
            continue

    return results


if __name__ == "__main__":
    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")
    folder_token = os.environ.get("FEISHU_FOLDER_TOKEN")

    if not all([app_id, app_secret, folder_token]):
        print("Error: Missing required environment variables")
        print("Need: FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_FOLDER_TOKEN")
        exit(1)

    docs = fetch_all_docs(app_id, app_secret, folder_token)
    print(f"\nSuccessfully fetched {len(docs)} documents")
