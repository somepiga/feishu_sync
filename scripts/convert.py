"""
飞书文档格式转换脚本
将飞书文档块结构转换为统一的数据结构
"""

import json
from typing import Dict, List, Any
from datetime import datetime


def convert_feishu_doc(doc_data: Dict) -> Dict:
    """
    将飞书文档转换为统一格式

    输出格式:
    {
        "id": "文档ID",
        "title": "文档标题",
        "updated_at": "更新时间（ISO格式）",
        "blocks": [
            {
                "type": "paragraph|heading|list|code|...",
                "content": "文本内容",
                "children": [...]  // 嵌套块
            }
        ]
    }
    """
    title = doc_data.get("title", "Untitled")
    doc_id = doc_data.get("id", "")
    updated_at = doc_data.get("updated_at")

    # 转换更新时间
    if updated_at:
        updated_at = datetime.fromtimestamp(updated_at / 1000).isoformat()

    # 获取文档内容
    content = doc_data.get("content", {})
    blocks = content.get("blocks", [])

    # 转换块结构
    converted_blocks = []
    for block in blocks:
        converted_block = convert_block(block)
        if converted_block:
            converted_blocks.append(converted_block)

    return {
        "id": doc_id,
        "title": title,
        "updated_at": updated_at,
        "blocks": converted_blocks
    }


def convert_block(block: Dict) -> Optional[Dict]:
    """转换单个块"""
    block_type = block.get("type", "")
    block_id = block.get("id", "")

    # 获取块内容
    element = block.get("element", {})
    children = block.get("children", [])

    # 根据块类型提取文本内容
    content = extract_text_content(element, block_type)

    result = {
        "id": block_id,
        "type": block_type,
        "content": content
    }

    # 递归处理子块
    if children:
        result["children"] = children

    return result


def extract_text_content(element: Dict, block_type: str) -> str:
    """从元素中提取文本内容"""
    text_content = []

    # 飞书文档的文本内容在 elements 数组中
    elements = element.get("elements", [])

    for elem in elements:
        # 文本元素
        if "text_elements" in elem:
            for te in elem["text_elements"]:
                if "text" in te:
                    text_content.append(te["text"]["content"])
        #  mention 元素
        elif "mention" in elem:
            mention = elem["mention"]
            if mention.get("type") == "user":
                text_content.append(f"@{mention.get('name', 'Unknown')}")
            elif mention.get("type") == "doc":
                text_content.append(f"[[{mention.get('title', 'Doc')}]]")
        # 方程元素
        elif "equation" in elem:
            text_content.append(f"$${elem['equation'].get('content', '')}")

    return "".join(text_content)


def load_existing_docs(content_dir: str) -> Dict[str, Dict]:
    """加载已存在的文档，用于增量同步"""
    existing = {}

    import os
    if not os.path.exists(content_dir):
        return existing

    for filename in os.listdir(content_dir):
        if filename.endswith(".json"):
            filepath = os.path.join(content_dir, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                doc = json.load(f)
                existing[doc["id"]] = doc

    return existing


def save_doc(doc: Dict, content_dir: str):
    """保存文档到文件"""
    import os
    os.makedirs(content_dir, exist_ok=True)

    # 使用安全的文件名
    safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in doc["title"])
    filename = f"{doc['id']}_{safe_title}.json"
    filepath = os.path.join(content_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    # 测试代码
    test_doc = {
        "id": "test123",
        "title": "测试文档",
        "updated_at": 1709308800000,
        "content": {
            "blocks": [
                {
                    "id": "block1",
                    "type": "paragraph",
                    "element": {
                        "elements": [
                            {
                                "text_elements": [
                                    {"text": {"content": "Hello World"}}
                                ]
                            }
                        ]
                    }
                }
            ]
        }
    }

    converted = convert_feishu_doc(test_doc)
    print(json.dumps(converted, ensure_ascii=False, indent=2))
