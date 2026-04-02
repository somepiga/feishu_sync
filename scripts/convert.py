"""
Helpers for converting fetched Feishu documents into the repository JSON format.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional


def normalize_updated_at(updated_at) -> Optional[str]:
    """Normalize second or millisecond timestamps into ISO strings."""
    if updated_at in (None, ""):
        return None

    try:
        numeric = float(updated_at)
        if numeric > 1_000_000_000_000:
            numeric /= 1000
        return datetime.fromtimestamp(numeric, tz=timezone.utc).isoformat()
    except Exception:
        return str(updated_at)


def convert_feishu_doc(doc_data: Dict) -> Dict:
    converted = {
        "id": doc_data.get("id", ""),
        "title": doc_data.get("title", "Untitled"),
        "updated_at": normalize_updated_at(doc_data.get("updated_at")),
        "raw_content": doc_data.get("raw_content", ""),
        "render_html": doc_data.get("render_html", ""),
        "assets": doc_data.get("assets", []),
        "blocks": [],
    }

    for field in (
        "node_token",
        "parent_node_token",
        "wiki_token",
        "space_id",
        "type",
        "sync_format_version",
    ):
        value = doc_data.get(field)
        if value is not None:
            converted[field] = value

    return converted


def load_existing_docs(content_dir: str) -> Dict[str, Dict]:
    existing: Dict[str, Dict] = {}
    content_path = Path(content_dir)
    if not content_path.exists():
        return existing

    for file_path in content_path.glob("*.json"):
        try:
            doc = json.loads(file_path.read_text(encoding="utf-8"))
            existing[doc["id"]] = doc
        except Exception:
            continue

    return existing


def save_doc(doc: Dict, content_dir: str) -> None:
    content_path = Path(content_dir)
    content_path.mkdir(parents=True, exist_ok=True)
    output_path = content_path / f"{doc['id']}.json"
    output_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
