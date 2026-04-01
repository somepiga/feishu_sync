#!/usr/bin/env python3
"""
飞书文档同步主脚本
支持 Wiki 知识库和文件夹两种模式
"""

import os
import sys
import json
from pathlib import Path

# 添加脚本目录到路径
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from fetch_docs import fetch_wiki_docs, fetch_folder_docs
from convert import convert_feishu_doc, load_existing_docs, save_doc


def main():
    # 获取环境变量
    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")
    wiki_token = os.environ.get("FEISHU_WIKI_TOKEN") or os.environ.get("FEISHU_FOLDER_TOKEN")

    if not all([app_id, app_secret, wiki_token]):
        print("Error: Missing required environment variables")
        print("Need: FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_WIKI_TOKEN (or FEISHU_FOLDER_TOKEN)")
        sys.exit(1)

    # 内容目录（相对于脚本目录）
    content_dir = script_dir.parent / "content" / "documents"

    print("=" * 50)
    print("Feishu Document Sync")
    print("=" * 50)

    # 加载已存在的文档（用于统计）
    existing_docs = load_existing_docs(str(content_dir))
    print(f"Found {len(existing_docs)} existing documents")

    # 判断是 Wiki 还是文件夹模式
    # 如果设置了 FEISHU_WIKI_TOKEN，使用 Wiki 模式
    mode = "wiki" if os.environ.get("FEISHU_WIKI_TOKEN") else "folder"
    print(f"Mode: {mode}")

    # 获取所有文档
    print("\nFetching documents from Feishu...")

    if mode == "wiki":
        docs = fetch_wiki_docs(app_id, app_secret, wiki_token)
    else:
        docs = fetch_folder_docs(app_id, app_secret, wiki_token)

    if not docs:
        print("No documents found!")
        return

    # 转换并保存文档
    print("\nConverting and saving documents...")
    saved_count = 0
    skipped_count = 0

    for doc in docs:
        try:
            # 转换格式
            converted = convert_feishu_doc(doc)

            # 检查是否有更新（增量同步）
            doc_id = converted["id"]
            if doc_id in existing_docs:
                old_updated = existing_docs[doc_id].get("updated_at")
                new_updated = converted.get("updated_at")
                if old_updated == new_updated:
                    print(f"  Skip (unchanged): {converted['title']}")
                    skipped_count += 1
                    continue

            # 保存文档
            save_doc(converted, str(content_dir))
            print(f"  Saved: {converted['title']}")
            saved_count += 1

        except Exception as e:
            print(f"  Error processing {doc.get('title', 'Unknown')}: {e}")
            continue

    # 统计
    print("\n" + "=" * 50)
    print(f"Sync complete!")
    print(f"  Saved: {saved_count}")
    print(f"  Skipped (unchanged): {skipped_count}")
    print(f"  Total processed: {len(docs)}")
    print("=" * 50)


if __name__ == "__main__":
    main()
