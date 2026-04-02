#!/usr/bin/env python3
"""
飞书文档同步主脚本
支持 Wiki 知识库和文件夹两种模式
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# 添加脚本目录到路径
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from fetch_docs import fetch_folder_docs, fetch_wiki_docs
from convert import convert_feishu_doc, load_existing_docs, save_doc


MANIFEST_FILENAME = "documents-index.json"
SYNC_METADATA_FIELDS = ("node_token", "wiki_token", "space_id", "type")
OPTIONAL_SYNC_METADATA_FIELDS = ("parent_node_token",)


def doc_needs_refresh(existing_doc: dict, converted_doc: dict) -> bool:
    """判断未更新的旧文档是否仍需按新格式重写。"""
    for field in SYNC_METADATA_FIELDS:
        if converted_doc.get(field) is not None and existing_doc.get(field) != converted_doc.get(field):
            return True

    for field in OPTIONAL_SYNC_METADATA_FIELDS:
        if field in converted_doc and existing_doc.get(field) != converted_doc.get(field):
            return True

    return False


def write_manifest(converted_docs: list[dict], manifest_path: Path) -> None:
    """写入供前端使用的文档清单。"""
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
            }
        )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(documents),
        "documents": documents,
    }

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")
    wiki_token = os.environ.get("FEISHU_WIKI_TOKEN") or os.environ.get("FEISHU_FOLDER_TOKEN")

    if not all([app_id, app_secret, wiki_token]):
        print("Error: Missing required environment variables")
        print("Need: FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_WIKI_TOKEN (or FEISHU_FOLDER_TOKEN)")
        sys.exit(1)

    content_dir = script_dir.parent / "content" / "documents"
    manifest_path = script_dir.parent / "content" / MANIFEST_FILENAME

    print("=" * 50)
    print("Feishu Document Sync")
    print("=" * 50)

    existing_docs = load_existing_docs(str(content_dir))
    print(f"Found {len(existing_docs)} existing documents")

    mode = "wiki" if os.environ.get("FEISHU_WIKI_TOKEN") else "folder"
    print(f"Mode: {mode}")

    print("\nFetching documents from Feishu...")
    if mode == "wiki":
        docs = fetch_wiki_docs(app_id, app_secret, wiki_token)
    else:
        docs = fetch_folder_docs(app_id, app_secret, wiki_token)

    if not docs:
        print("No documents found!")
        return

    print("\nConverting and saving documents...")
    converted_docs = []
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
        except Exception as e:
            print(f"  Error processing {doc.get('title', 'Unknown')}: {e}")
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
