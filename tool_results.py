"""Structured tool results and their text representation."""

from __future__ import annotations

import json
from typing import Any, TypedDict


ToolResultData = dict[str, Any]


class ToolResult(TypedDict):
    data: ToolResultData
    display: str


def error_result(message: str) -> ToolResultData:
    return {"kind": "error", "message": message}


def format_tool_result_data(data: ToolResultData) -> str:
    kind = data["kind"]

    if kind == "chapter_list":
        chapters = data["chapters"]
        if not chapters:
            return "没有可用章节"
        return "\n".join(
            f"第 {chapter['chapter_id']} 章：{chapter['title']}"
            for chapter in chapters
        )

    if kind == "chapter":
        return data["content"]

    if kind == "chapters":
        parts = [
            f"第 {chapter['chapter_id']} 章：{chapter['title']}\n{chapter['content']}"
            for chapter in data["chapters"]
        ]
        missing = data["missing_chapter_ids"]
        if missing:
            parts.append("不存在的章节：" + "、".join(map(str, missing)))
        return "\n\n".join(parts) if parts else "没有读取到任何章节"

    if kind == "keyword_search":
        matches = data["matches"]
        if not matches:
            return f"没有找到关键词“{data['keyword']}”"
        text = "\n\n".join(
            "\n".join([
                f"第 {match['chapter_id']} 章：{match['title']}，出现次数：{match['count']}",
                *(occurrence["excerpt"] for occurrence in match["occurrences"]),
            ])
            for match in matches
        )
        if data["truncated"]:
            text += "\n\n（搜索结果过多，已截断）"
        return text

    if kind == "semantic_search":
        return "\n".join(
            f"第{match['chapter_id']}章（{match['title']}）：\n{match['text']}\n"
            for match in data["matches"]
        )

    if kind == "summary":
        return data["content"]

    if kind == "error":
        return f"工具执行失败：{data['message']}"

    raise ValueError(f"未知的工具结果类型：{kind}")


def make_tool_result(data: ToolResultData) -> ToolResult:
    return {"data": data, "display": format_tool_result_data(data)}


def load_tool_result_data(content: str) -> ToolResultData:
    return json.loads(content)
