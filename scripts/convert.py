"""
飞书文档格式转换脚本
将飞书文档转换为统一的数据结构
"""

import json
from typing import Dict, List, Any, Optional
from datetime import datetime


def convert_feishu_doc(doc_data: Dict) -> Dict:
    """
    将飞书文档转换为统一格式

    输出格式:
    {
        "id": "文档ID",
        "title": "文档标题",
        "updated_at": "更新时间（ISO格式）",
        "raw_content": "原始文本内容",
        "blocks": []  // 保留为空，后续可扩展
    }
    """
    title = doc_data.get("title", "Untitled")
    doc_id = doc_data.get("id", "")
    updated_at = doc_data.get("updated_at")
    raw_content = doc_data.get("raw_content", "")

    # 转换更新时间
    if updated_at:
        try:
            updated_at = datetime.fromtimestamp(updated_at / 1000).isoformat()
        except:
            updated_at = str(updated_at)

    return {
        "id": doc_id,
        "title": title,
        "updated_at": updated_at,
        "raw_content": raw_content,
        "blocks": []
    }


def load_existing_docs(content_dir: str) -> Dict[str, Dict]:
    """加载已存在的文档，用于增量同步"""
    existing = {}

    import os
    if not os.path.exists(content_dir):
        return existing

    for filename in os.listdir(content_dir):
        if filename.endswith(".json"):
            filepath = os.path.join(content_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    doc = json.load(f)
                    existing[doc["id"]] = doc
            except:
                continue

    return existing


def save_doc(doc: Dict, content_dir: str):
    """保存文档到文件"""
    import os
    os.makedirs(content_dir, exist_ok=True)

    # 使用文档 ID 命名，避免文件名冲突
    filename = f"{doc['id']}.json"
    filepath = os.path.join(content_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    # 测试代码
    test_doc = {
        "id": "test123",
        "title": "测试文档",
        "updated_at": 1709308800000,
        "raw_content": "这是文档的原始文本内容\n包含多行文字"
    }

    converted = convert_feishu_doc(test_doc)
    print(json.dumps(converted, ensure_ascii=False, indent=2))
