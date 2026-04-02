#!/usr/bin/env python3
"""
Sync Feishu docs into the static site content directory.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from convert import convert_feishu_doc, load_existing_docs, save_doc
from fetch_docs import SYNC_FORMAT_VERSION, fetch_folder_docs, fetch_wiki_docs


MANIFEST_FILENAME = "documents-index.json"
SYNC_METADATA_FIELDS = ("node_token", "wiki_token", "space_id", "type", "sync_format_version")
OPTIONAL_SYNC_METADATA_FIELDS = ("parent_node_token", "render_html", "assets")


def doc_needs_refresh(existing_doc: dict, converted_doc: dict) -> bool:
    for field in SYNC_METADATA_FIELDS:
        if converted_doc.get(field) is not None and existing_doc.get(field) != converted_doc.get(field):
            return True

    for field in OPTIONAL_SYNC_METADATA_FIELDS:
        if field in converted_doc and existing_doc.get(field) != converted_doc.get(field):
            return True

    return False


def build_embedded_doc(doc: dict) -> dict:
    return {
        "id": doc["id"],
        "title": doc.get("title"),
        "updated_at": doc.get("updated_at"),
        "type": doc.get("type"),
        "node_token": doc.get("node_token"),
        "parent_node_token": doc.get("parent_node_token"),
        "wiki_token": doc.get("wiki_token"),
        "space_id": doc.get("space_id"),
        "raw_content": doc.get("raw_content", ""),
        "render_html": doc.get("render_html", ""),
        "assets": doc.get("assets", []),
        "sync_format_version": doc.get("sync_format_version", SYNC_FORMAT_VERSION),
    }


def write_manifest(converted_docs: list[dict], manifest_path: Path) -> None:
    documents = []
    for order, doc in enumerate(converted_docs):
        documents.append(
            {
                "id": doc["id"],
                "title": doc.get("title"),
                "updated_at": doc.get("updated_at"),
                "type": doc.get("type"),
                "node_token": doc.get("node_token"),
                "parent_node_token": doc.get("parent_node_token"),
                "wiki_token": doc.get("wiki_token"),
                "space_id": doc.get("space_id"),
                "file": f"content/documents/{doc['id']}.json",
                "order": order,
                "embedded": build_embedded_doc(doc),
            }
        )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(documents),
        "documents": documents,
    }

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")
    wiki_token = os.environ.get("FEISHU_WIKI_TOKEN") or os.environ.get("FEISHU_FOLDER_TOKEN")

    if not all([app_id, app_secret, wiki_token]):
        print("Error: Missing required environment variables")
        print("Need: FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_WIKI_TOKEN (or FEISHU_FOLDER_TOKEN)")
        raise SystemExit(1)

    content_root = script_dir.parent / "content"
    content_dir = content_root / "documents"
    asset_dir = content_root / "media"
    manifest_path = content_root / MANIFEST_FILENAME

    print("=" * 50)
    print("Feishu Document Sync")
    print("=" * 50)

    existing_docs = load_existing_docs(str(content_dir))
    print(f"Found {len(existing_docs)} existing documents")

    mode = "wiki" if os.environ.get("FEISHU_WIKI_TOKEN") else "folder"
    print(f"Mode: {mode}")
    print("\nFetching documents from Feishu...")

    if mode == "wiki":
        docs = fetch_wiki_docs(app_id, app_secret, wiki_token, asset_dir=asset_dir)
    else:
        docs = fetch_folder_docs(app_id, app_secret, wiki_token, asset_dir=asset_dir)

    if not docs:
        print("No documents found!")
        return

    print("\nConverting and saving documents...")
    converted_docs: list[dict] = []
    saved_count = 0
    skipped_count = 0

    for doc in docs:
        try:
            converted = convert_feishu_doc(doc)
            converted_docs.append(converted)

            doc_id = converted["id"]
            if doc_id in existing_docs:
                old_doc = existing_docs[doc_id]
                old_updated = old_doc.get("updated_at")
                new_updated = converted.get("updated_at")

                if old_updated == new_updated and not doc_needs_refresh(old_doc, converted):
                    print(f"  Skip (unchanged): {converted['title']}")
                    skipped_count += 1
                    continue

            save_doc(converted, str(content_dir))
            print(f"  Saved: {converted['title']}")
            saved_count += 1
        except Exception as exc:
            print(f"  Error processing {doc.get('title', 'Unknown')}: {exc}")
            continue

    write_manifest(converted_docs, manifest_path)
    print(f"Manifest written: {manifest_path.relative_to(script_dir.parent)}")

    print("\n" + "=" * 50)
    print("Sync complete!")
    print(f"  Saved: {saved_count}")
    print(f"  Skipped (unchanged): {skipped_count}")
    print(f"  Total processed: {len(docs)}")
    print("=" * 50)


if __name__ == "__main__":
    main()
