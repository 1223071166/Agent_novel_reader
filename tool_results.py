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

    if kind == "keyword_search":
        matches = data["matches"]
        if not matches:
            return f"没有找到关键词“{data['keyword']}”"
        return "\n".join(
            f"第 {match['chapter_id']} 章：{match['title']}，出现次数：{match['count']}"
            for match in matches
        )

    if kind == "chapter_keyword_search":
        heading = (
            f"搜索了第{data['chapter_id']}章({data['title']})内的关键词"
            f"{data['keyword']},共找到{len(data['matches'])}个结果，以下为上下文："
        )
        excerpts = "\n".join(match["excerpt"] for match in data["matches"])
        return f"{heading}\n{excerpts}"

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
