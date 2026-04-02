"""
Feishu document fetch helpers.

Supports:
- recursively walking wiki trees
- fetching raw text content
- fetching docx blocks for rich rendering
- downloading image/file media referenced by blocks
"""

from __future__ import annotations

import html
import mimetypes
import os
import re
import time
from collections import deque
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.parse import unquote

import requests


ASSET_URL_PREFIX = "content/media"
SYNC_FORMAT_VERSION = 4


class FeishuClient:
    """Feishu OpenAPI client."""

    BASE_URL = "https://open.feishu.cn/open-apis"

    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self.app_access_token: Optional[str] = None
        self.token_expires_at = 0.0

    def _get_app_access_token(self) -> str:
        current_time = time.time()
        if self.app_access_token and current_time < self.token_expires_at - 60:
            return self.app_access_token

        response = requests.post(
            f"{self.BASE_URL}/auth/v3/app_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        if data.get("code") != 0:
            raise RuntimeError(f"Failed to get app access token: {data}")

        self.app_access_token = data["app_access_token"]
        self.token_expires_at = current_time + 7200
        return self.app_access_token

    def _request(self, method: str, path: str, **kwargs) -> Dict:
        token = self._get_app_access_token()
        headers = kwargs.get("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        kwargs["headers"] = headers
        kwargs.setdefault("timeout", 30)

        response = requests.request(method, f"{self.BASE_URL}{path}", **kwargs)
        if response.status_code == 429 or response.status_code >= 500:
            time.sleep(5)
            response = requests.request(method, f"{self.BASE_URL}{path}", **kwargs)

        response.raise_for_status()
        data = response.json()
        if data.get("code") != 0:
            raise RuntimeError(f"API error: {data}")
        return data.get("data", {})

    def _raw_request(self, method: str, path: str, **kwargs) -> requests.Response:
        token = self._get_app_access_token()
        headers = kwargs.get("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        kwargs["headers"] = headers
        kwargs.setdefault("timeout", 60)
        return requests.request(method, f"{self.BASE_URL}{path}", **kwargs)

    def get_wiki_node(self, node_token: str) -> Dict:
        return self._request("GET", f"/wiki/v2/spaces/get_node?token={node_token}")

    def get_wiki_children(self, space_id: str, parent_node_token: str = "") -> List[Dict]:
        all_nodes: List[Dict] = []
        page_token = None

        while True:
            params = {}
            if page_token:
                params["page_token"] = page_token
            if parent_node_token:
                params["parent_node_token"] = parent_node_token

            data = self._request("GET", f"/wiki/v2/spaces/{space_id}/nodes", params=params)
            all_nodes.extend(data.get("items", []))

            if not data.get("has_more"):
                break

            page_token = data.get("page_token")
            time.sleep(0.1)

        return all_nodes

    def _should_probe_wiki_node_children(self, node: Dict) -> bool:
        return bool(node.get("node_token"))

    def get_all_wiki_nodes_recursive(
        self,
        space_id: str,
        root_token: str = "",
        root_node: Optional[Dict] = None,
    ) -> List[Dict]:
        all_nodes: List[Dict] = []
        seen_tokens = set()
        queued_tokens = set()
        fetched_parent_tokens = set()
        to_fetch: deque[str] = deque()

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
            except Exception as exc:
                print(f"  [RECURSIVE] Failed to fetch children of {parent_token or '(root)'}: {exc}")
                continue

            print(f"  [RECURSIVE] Got {len(children)} children")
            for child in children:
                child_token = child.get("node_token")
                print(
                    "    [RECURSIVE]   - "
                    f"{child_token} | {child.get('title', '')[:30]} | "
                    f"has_child={child.get('has_child')} | type={child.get('obj_type')}"
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
        response = self._raw_request("GET", f"/docx/v1/documents/{doc_token}/raw_content")
        if response.status_code == 404:
            return ""

        data = response.json()
        if data.get("code") != 0:
            return ""
        return data.get("data", {}).get("content", "")

    def get_doc_meta(self, doc_token: str) -> Dict:
        try:
            return self._request("GET", f"/docx/v1/documents/{doc_token}/meta")
        except Exception:
            return {}

    def get_doc_blocks(self, doc_token: str) -> List[Dict]:
        all_blocks: List[Dict] = []
        page_token = None

        while True:
            params = {}
            if page_token:
                params["page_token"] = page_token

            data = self._request("GET", f"/docx/v1/documents/{doc_token}/blocks", params=params)
            all_blocks.extend(data.get("items", []))
            if not data.get("has_more"):
                break

            page_token = data.get("page_token")
            time.sleep(0.1)

        return all_blocks

    def download_media(self, file_token: str) -> requests.Response:
        response = self._raw_request("GET", f"/drive/v1/medias/{file_token}/download", stream=True)
        response.raise_for_status()
        return response


def _extract_filename_from_disposition(content_disposition: str) -> Optional[str]:
    if not content_disposition:
        return None

    match = re.search(r"filename\*=UTF-8''([^;]+)", content_disposition)
    if match:
        return unquote(match.group(1))

    match = re.search(r'filename="([^"]+)"', content_disposition)
    if match:
        return match.group(1)

    return None


def _safe_filename(name: str) -> str:
    safe = re.sub(r"[<>:\"/\\\\|?*]+", "_", name).strip()
    return safe or "asset"


def _guess_extension(content_type: Optional[str], filename: Optional[str]) -> str:
    if filename:
        suffix = Path(filename).suffix
        if suffix:
            return suffix

    if not content_type:
        return ""

    content_type = content_type.split(";")[0].strip()
    guessed = mimetypes.guess_extension(content_type)
    if guessed == ".jpe":
        return ".jpg"
    return guessed or ""


def _download_asset(
    client: FeishuClient,
    asset_dir: Path,
    token: str,
    preferred_name: Optional[str] = None,
) -> Dict:
    asset_dir.mkdir(parents=True, exist_ok=True)

    response = client.download_media(token)
    content_type = response.headers.get("Content-Type")
    disposition_name = _extract_filename_from_disposition(response.headers.get("Content-Disposition", ""))
    filename = preferred_name or disposition_name or token
    extension = _guess_extension(content_type, filename)
    output_name = _safe_filename(f"{token}{extension}")
    output_path = asset_dir / output_name

    if not output_path.exists():
        output_path.write_bytes(response.content)

    return {
        "token": token,
        "name": preferred_name or disposition_name or output_name,
        "path": f"{ASSET_URL_PREFIX}/{output_name}",
        "content_type": content_type,
    }


def _wrap_inline_style(text: str, style: Dict) -> str:
    wrapped = text
    if style.get("inline_code"):
        wrapped = f"<code>{wrapped}</code>"
    if style.get("bold"):
        wrapped = f"<strong>{wrapped}</strong>"
    if style.get("italic"):
        wrapped = f"<em>{wrapped}</em>"
    if style.get("underline"):
        wrapped = f"<u>{wrapped}</u>"
    if style.get("strikethrough"):
        wrapped = f"<s>{wrapped}</s>"
    return wrapped


def _render_inline_elements(elements: Iterable[Dict], preserve_newlines: bool = False) -> str:
    parts: List[str] = []
    for element in elements or []:
        text_run = element.get("text_run")
        if not text_run:
            continue

        content = html.escape(text_run.get("content", ""))
        if preserve_newlines:
            content = content.replace("\n", "<br>")
        style = text_run.get("text_element_style", {})
        parts.append(_wrap_inline_style(content, style))

    return "".join(parts)


def _render_list_item(block: Dict, block_map: Dict[str, Dict], asset_map: Dict[str, Dict]) -> str:
    block_type = block.get("block_type")
    block_key = {12: "bullet", 13: "ordered"}.get(block_type)
    if not block_key:
        return ""

    content = _render_inline_elements(block.get(block_key, {}).get("elements", []), preserve_newlines=True)
    children = _render_children(block.get("children", []), block_map, asset_map)
    return f"<li>{content}{children}</li>"


def _render_table(block: Dict, block_map: Dict[str, Dict], asset_map: Dict[str, Dict]) -> str:
    table = block.get("table", {})
    property_data = table.get("property", {})
    row_size = property_data.get("row_size", 0)
    column_size = property_data.get("column_size", 0)
    cells = table.get("cells", [])
    merge_info = property_data.get("merge_info", [])

    if not row_size or not column_size or not cells:
        return ""

    occupied = [[False] * column_size for _ in range(row_size)]
    rendered_cells: Dict[tuple[int, int], str] = {}

    row = 0
    col = 0
    for index, cell_id in enumerate(cells):
        while row < row_size and occupied[row][col]:
            col += 1
            if col >= column_size:
                row += 1
                col = 0
        if row >= row_size:
            break

        merge = merge_info[index] if index < len(merge_info) else {}
        row_span = max(int(merge.get("row_span", 1) or 1), 1)
        col_span = max(int(merge.get("col_span", 1) or 1), 1)

        cell_block = block_map.get(cell_id, {})
        cell_html = _render_children(cell_block.get("children", []), block_map, asset_map)
        attributes = []
        if row_span > 1:
            attributes.append(f' rowspan="{row_span}"')
        if col_span > 1:
            attributes.append(f' colspan="{col_span}"')
        rendered_cells[(row, col)] = f"<td{''.join(attributes)}>{cell_html or '&nbsp;'}</td>"

        for r in range(row, min(row + row_span, row_size)):
            for c in range(col, min(col + col_span, column_size)):
                occupied[r][c] = True

    rows: List[str] = []
    for r in range(row_size):
        cells_html: List[str] = []
        for c in range(column_size):
            if (r, c) in rendered_cells:
                cells_html.append(rendered_cells[(r, c)])
        rows.append(f"<tr>{''.join(cells_html)}</tr>")

    return f"<div class=\"doc-table-wrap\"><table class=\"doc-table\">{''.join(rows)}</table></div>"


def _render_block(block: Dict, block_map: Dict[str, Dict], asset_map: Dict[str, Dict]) -> str:
    block_type = block.get("block_type")

    if block_type == 1:
        return _render_children(block.get("children", []), block_map, asset_map)

    if block_type == 2:
        text = _render_inline_elements(block.get("text", {}).get("elements", []), preserve_newlines=True)
        return f"<p>{text or '&nbsp;'}</p>"

    if block_type in {3, 4, 5, 6}:
        key = {3: "heading1", 4: "heading2", 5: "heading3", 6: "heading4"}[block_type]
        level = {3: 2, 4: 3, 5: 4, 6: 5}[block_type]
        text = _render_inline_elements(block.get(key, {}).get("elements", []), preserve_newlines=True)
        return f"<h{level}>{text}</h{level}>"

    if block_type == 14:
        code = _render_inline_elements(block.get("code", {}).get("elements", []))
        return f"<pre><code>{code or '&nbsp;'}</code></pre>"

    if block_type == 15:
        quote = _render_inline_elements(block.get("quote", {}).get("elements", []), preserve_newlines=True)
        children = _render_children(block.get("children", []), block_map, asset_map)
        return f"<blockquote>{quote}{children}</blockquote>"

    if block_type == 23:
        file_info = block.get("file", {})
        asset = asset_map.get(file_info.get("token"))
        name = html.escape(file_info.get("name", "Attachment"))
        if asset:
            return (
                "<p class=\"attachment\">"
                f"<a href=\"{html.escape(asset['path'])}\" target=\"_blank\" rel=\"noopener\">附件: {name}</a>"
                "</p>"
            )
        return f"<p class=\"attachment\">附件: {name}</p>"

    if block_type == 24:
        columns = _render_children(block.get("children", []), block_map, asset_map)
        column_size = block.get("grid", {}).get("column_size", 1)
        return f"<div class=\"doc-grid columns-{column_size}\">{columns}</div>"

    if block_type == 25:
        width_ratio = block.get("grid_column", {}).get("width_ratio", 100)
        children = _render_children(block.get("children", []), block_map, asset_map)
        return f"<div class=\"doc-grid-column\" style=\"flex:{width_ratio} 1 0\">{children}</div>"

    if block_type == 27:
        image = block.get("image", {})
        asset = asset_map.get(image.get("token"))
        if not asset:
            return "<p class=\"asset-missing\">图片同步失败</p>"

        width = image.get("width")
        height = image.get("height")
        attrs = []
        if width:
            attrs.append(f' width="{int(width)}"')
        if height:
            attrs.append(f' height="{int(height)}"')

        return (
            "<figure class=\"doc-image\">"
            f"<img src=\"{html.escape(asset['path'])}\" alt=\"image\" loading=\"lazy\"{''.join(attrs)}>"
            "</figure>"
        )

    if block_type == 31:
        return _render_table(block, block_map, asset_map)

    if block_type == 32:
        return _render_children(block.get("children", []), block_map, asset_map)

    if block_type == 33:
        return f"<div class=\"doc-view\">{_render_children(block.get('children', []), block_map, asset_map)}</div>"

    if block_type == 34:
        return (
            "<blockquote class=\"quote-container\">"
            f"{_render_children(block.get('children', []), block_map, asset_map)}"
            "</blockquote>"
        )

    return _render_children(block.get("children", []), block_map, asset_map)


def _render_children(children_ids: Iterable[str], block_map: Dict[str, Dict], asset_map: Dict[str, Dict]) -> str:
    children_ids = list(children_ids or [])
    parts: List[str] = []
    index = 0

    while index < len(children_ids):
        block = block_map.get(children_ids[index])
        if not block:
            index += 1
            continue

        block_type = block.get("block_type")
        if block_type in {12, 13}:
            list_tag = "ul" if block_type == 12 else "ol"
            items: List[str] = []
            while index < len(children_ids):
                current = block_map.get(children_ids[index])
                if not current or current.get("block_type") != block_type:
                    break
                items.append(_render_list_item(current, block_map, asset_map))
                index += 1
            parts.append(f"<{list_tag}>{''.join(items)}</{list_tag}>")
            continue

        parts.append(_render_block(block, block_map, asset_map))
        index += 1

    return "".join(parts)


def render_blocks_to_html(blocks: List[Dict], doc_id: str, asset_map: Dict[str, Dict]) -> str:
    if not blocks:
        return ""

    block_map = {block["block_id"]: block for block in blocks if block.get("block_id")}
    root = block_map.get(doc_id) or next((block for block in blocks if block.get("block_type") == 1), blocks[0])
    return _render_children(root.get("children", []), block_map, asset_map)


def _collect_assets_for_blocks(
    client: FeishuClient,
    blocks: List[Dict],
    asset_dir: Optional[Path],
) -> List[Dict]:
    if not asset_dir:
        return []

    assets: List[Dict] = []
    seen_tokens = set()

    for block in blocks:
        block_type = block.get("block_type")
        if block_type == 27:
            token = block.get("image", {}).get("token")
            preferred_name = None
            asset_type = "image"
        elif block_type == 23:
            token = block.get("file", {}).get("token")
            preferred_name = block.get("file", {}).get("name")
            asset_type = "file"
        else:
            continue

        if not token or token in seen_tokens:
            continue

        try:
            asset = _download_asset(client, asset_dir, token, preferred_name=preferred_name)
            asset["type"] = asset_type
            assets.append(asset)
            seen_tokens.add(token)
        except Exception as exc:
            print(f"    Failed to download asset {token}: {exc}")

        time.sleep(0.05)

    return assets


def _build_doc_payload(
    client: FeishuClient,
    doc: Dict,
    asset_dir: Optional[Path],
) -> Dict:
    doc_id = doc["obj_token"]
    meta = client.get_doc_meta(doc_id)
    raw_content = client.get_doc_raw_content(doc_id)
    blocks = client.get_doc_blocks(doc_id)
    assets = _collect_assets_for_blocks(client, blocks, asset_dir)
    asset_map = {asset["token"]: asset for asset in assets}
    render_html = render_blocks_to_html(blocks, doc_id, asset_map)

    return {
        "node_token": doc["node_token"],
        "parent_node_token": doc.get("parent_node_token"),
        "id": doc_id,
        "title": doc["title"],
        "type": doc["type"],
        "meta": meta,
        "raw_content": raw_content,
        "render_html": render_html,
        "assets": assets,
        "updated_at": meta.get("document", {}).get("updated_at") or doc.get("obj_edit_time"),
        "space_id": doc.get("space_id"),
        "wiki_token": doc["wiki_token"],
        "sync_format_version": SYNC_FORMAT_VERSION,
    }


def fetch_wiki_docs(
    app_id: str,
    app_secret: str,
    wiki_token: str,
    asset_dir: Optional[os.PathLike[str] | str] = None,
) -> List[Dict]:
    client = FeishuClient(app_id, app_secret)
    asset_dir_path = Path(asset_dir) if asset_dir else None

    wiki_tokens = [token.strip() for token in wiki_token.split(",") if token.strip()]
    print(f"Fetching {len(wiki_tokens)} wiki(s)")

    all_results: List[Dict] = []
    seen_doc_ids = set()

    for index, token in enumerate(wiki_tokens, start=1):
        print(f"\n[{index}/{len(wiki_tokens)}] Processing wiki: {token}")

        try:
            root = client.get_wiki_node(token)
            root_node = root.get("node", {})
            space_id = root_node.get("space_id")
            root_title = root_node.get("title", "Wiki Root")
        except Exception as exc:
            print(f"  Failed to get wiki node: {exc}")
            continue

        print(f"  Wiki space ID: {space_id}")
        print(f"  Root node: {root_title}")
        print("  Fetching all nodes in wiki space (recursive)...")

        try:
            all_nodes = client.get_all_wiki_nodes_recursive(space_id, token, root_node)
            print(f"  Found {len(all_nodes)} nodes total")
        except Exception as exc:
            print(f"  Failed to get children: {exc}")
            continue

        doc_nodes: List[Dict] = []
        type_stats: Dict[str, int] = {}
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
                        "obj_edit_time": node.get("obj_edit_time"),
                        "space_id": space_id,
                        "type": obj_type,
                        "wiki_token": token,
                    }
                )

        print(f"  Node type distribution: {type_stats}")
        print(f"  Found {len(doc_nodes)} documents")

        for doc_index, doc in enumerate(doc_nodes, start=1):
            doc_id = doc.get("obj_token")
            if not doc_id:
                print(f"  [{doc_index}/{len(doc_nodes)}] Skip node without obj_token: {doc.get('title')}")
                continue

            if doc_id in seen_doc_ids:
                print(f"  [{doc_index}/{len(doc_nodes)}] Skip duplicate: {doc['title']}")
                continue

            print(f"  [{doc_index}/{len(doc_nodes)}] Fetching: {doc['title']}")

            try:
                all_results.append(_build_doc_payload(client, doc, asset_dir_path))
                seen_doc_ids.add(doc_id)
            except Exception as exc:
                print(f"    Error fetching {doc['title']}: {exc}")
                continue

            time.sleep(0.2)

    return all_results


def fetch_folder_docs(
    app_id: str,
    app_secret: str,
    folder_token: str,
    asset_dir: Optional[os.PathLike[str] | str] = None,
) -> List[Dict]:
    raise NotImplementedError("Folder mode is not implemented in this repository yet.")


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
