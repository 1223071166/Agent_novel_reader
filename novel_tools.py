import re
from dataclasses import dataclass

from config import BookPaths
from summaries import (
    BIG_SIZE,
    MID_SIZE,
    block_range,
    get_summary as _get_summary,
    is_block_start,
    total_chapters,
)
from embedding import search
from tool_results import ToolResultData, error_result
embedding_search = search

chapter_cache={}
titles_by_book={}


@dataclass(frozen=True)
class NovelToolContext:
    book_path: BookPaths
    max_chapter: int | None


def _spoiler_error(context: NovelToolContext) -> ToolResultData:
    return error_result(
        f"防剧透模式已开启，目前只能查看到第 {context.max_chapter} 章"
    )


def _chapter_allowed(context: NovelToolContext, chapter_id: int) -> bool:
    return context.max_chapter is None or chapter_id <= context.max_chapter

def load_titles(book_path: BookPaths):
    if book_path.book_id in titles_by_book:
        return titles_by_book[book_path.book_id]

    titles = {}
    with open(book_path.chapter_list,"r",encoding="utf-8") as f:
        lines=f.read().splitlines()

    for line in lines:
        match=re.match(r"(\d+)，?(.*)",line)
        if match:
            titles[int(match.group(1))]=match.group(2).strip()
    titles_by_book[book_path.book_id] = titles
    return titles


def read_chapter(chapter_id, book_path: BookPaths):
    """按需读取单章正文，读过的缓存起来。返回 None 表示章节不存在。"""
    cache_key = (book_path.book_id, chapter_id)
    if cache_key in chapter_cache:
        return chapter_cache[cache_key]

    path=book_path.chapter_dir / f"{chapter_id}.txt"
    if not path.is_file():
        return None

    with open(path,"r",encoding="utf-8") as f:
        content=f.read()

    chapter=chapter_cache[cache_key]={
        "title":load_titles(book_path).get(chapter_id,""),
        "content":content
    }
    return chapter

#可用工具
def get_chapter_list(
    query: str | None = None,
    start_chapter: int | None = None,
    end_chapter: int | None = None,
    *,
    context: NovelToolContext,
) -> ToolResultData:
    """获取全部章节，或按标题文字和章节范围筛选。"""
    query = query.strip() if isinstance(query, str) else query
    if query == "":
        query = None
    if query is not None and not isinstance(query, str):
        return error_result("章节标题关键词必须是字符串")
    for name, value in (("起始章号", start_chapter), ("结束章号", end_chapter)):
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 1):
            return error_result(f"{name}必须是正整数")
    if start_chapter is not None and end_chapter is not None and start_chapter > end_chapter:
        return error_result("起始章号不能大于结束章号")
    chapters = [
        {"chapter_id": chapter_id, "title": title}
        for chapter_id, title in sorted(load_titles(context.book_path).items())
        if _chapter_allowed(context, chapter_id)
        and (start_chapter is None or chapter_id >= start_chapter)
        and (end_chapter is None or chapter_id <= end_chapter)
        and (query is None or query.casefold() in title.casefold())
    ]
    return {
        "kind": "chapter_list",
        "query": query,
        "start_chapter": start_chapter,
        "end_chapter": end_chapter,
        "chapters": chapters,
    }


def get_chapter(chapter_id:int, context: NovelToolContext) -> ToolResultData:
    """获取指定章节正文"""
    if not _chapter_allowed(context, chapter_id):
        return _spoiler_error(context)
    chapter=read_chapter(chapter_id, context.book_path)
    if chapter is None:
        return error_result(f"不存在第 {chapter_id} 章")

    return {
        "kind": "chapter",
        "chapter_id": chapter_id,
        "title": chapter["title"],
        "content": chapter["content"],
    }


def get_chapters(chapter_ids: list[int], context: NovelToolContext) -> ToolResultData:
    """一次读取最多十个指定章节，按传入顺序返回。"""
    if not isinstance(chapter_ids, list) or not chapter_ids:
        return error_result("请提供至少一个章节编号")
    if len(chapter_ids) > 10:
        return error_result("一次最多读取 10 章")
    if any(
        not isinstance(chapter_id, int)
        or isinstance(chapter_id, bool)
        or chapter_id < 1
        for chapter_id in chapter_ids
    ):
        return error_result("章节编号必须是正整数")
    if any(not _chapter_allowed(context, chapter_id) for chapter_id in chapter_ids):
        return _spoiler_error(context)

    chapters = []
    missing_chapter_ids = []
    for chapter_id in dict.fromkeys(chapter_ids):
        chapter = read_chapter(chapter_id, context.book_path)
        if chapter is None:
            missing_chapter_ids.append(chapter_id)
            continue
        chapters.append({
            "chapter_id": chapter_id,
            "title": chapter["title"],
            "content": chapter["content"],
        })
    return {
        "kind": "chapters",
        "chapters": chapters,
        "missing_chapter_ids": missing_chapter_ids,
    }


def iter_chapters(context: NovelToolContext):
    """按章节号顺序遍历全书，按需读取（利用 read_chapter 的缓存）。"""
    for chapter_id in sorted(load_titles(context.book_path)):
        if not _chapter_allowed(context, chapter_id):
            continue
        chapter=read_chapter(chapter_id, context.book_path)
        if chapter is not None:
            yield chapter_id, chapter


def search_keyword(
    keyword: str,
    context: NovelToolContext,
    start_chapter: int | None = None,
    end_chapter: int | None = None,
    context_chars: int = 20,
) -> ToolResultData:
    """在全书或指定章节范围搜索关键词，最多返回五十条上下文。"""
    if not keyword:
        return error_result("关键词不能为空")
    for name, value in (("起始章号", start_chapter), ("结束章号", end_chapter)):
        if value is not None and (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 1
        ):
            return error_result(f"{name}必须是正整数")
    if start_chapter is not None and end_chapter is not None and start_chapter > end_chapter:
        return error_result("起始章号不能大于结束章号")
    if (
        not isinstance(context_chars, int)
        or isinstance(context_chars, bool)
        or context_chars < 0
    ):
        return error_result("上下文字数必须是非负整数")
    if context.max_chapter is not None and start_chapter is not None and start_chapter > context.max_chapter:
        return _spoiler_error(context)

    effective_end = end_chapter
    if context.max_chapter is not None:
        effective_end = min(end_chapter, context.max_chapter) if end_chapter is not None else context.max_chapter

    before = context_chars // 2
    after = context_chars - before
    matches = []
    returned_contexts = 0
    truncated = False
    for matched_chapter_id, chapter in iter_chapters(context):
        if start_chapter is not None and matched_chapter_id < start_chapter:
            continue
        if effective_end is not None and matched_chapter_id > effective_end:
            break
        text = chapter["content"]
        count = text.count(keyword)
        if count == 0:
            continue
        remaining = 50 - returned_contexts
        if remaining == 0:
            truncated = True
            break
        occurrences = []
        start = 0
        while len(occurrences) < remaining:
            index = text.find(keyword, start)
            if index == -1:
                break
            occurrences.append({
                "start": index,
                "end": index + len(keyword),
                "excerpt": text[
                    max(0, index - before):
                    min(len(text), index + len(keyword) + after)
                ],
            })
            start = index + len(keyword)
        returned_contexts += len(occurrences)
        matches.append({
            "chapter_id": matched_chapter_id,
            "title": chapter["title"],
            "count": count,
            "occurrences": occurrences,
        })
        if count > len(occurrences):
            truncated = True
            break
    return {
        "kind": "keyword_search",
        "keyword": keyword,
        "start_chapter": start_chapter,
        "end_chapter": effective_end,
        "context_chars": context_chars,
        "matches": matches,
        "truncated": truncated,
    }

def semantic_search(
    query: str,
    context: NovelToolContext,
    n: int = 10,
    start_chapter: int | None = None,
    end_chapter: int | None = None,
) -> ToolResultData:
    """使用embedding进行小说语义检索，返回最相关文本片段"""
    global embedding_search

    if not context.book_path.vector_db_dir.exists():
        return error_result("暂未完成书籍向量化，无法模糊搜索")

    for name, value in (("起始章号", start_chapter), ("结束章号", end_chapter)):
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 1):
            return error_result(f"{name}必须是正整数")
    if start_chapter is not None and end_chapter is not None and start_chapter > end_chapter:
        return error_result("起始章号不能大于结束章号")
    if context.max_chapter is not None and start_chapter is not None and start_chapter > context.max_chapter:
        return _spoiler_error(context)

    effective_end = end_chapter
    if context.max_chapter is not None:
        effective_end = min(end_chapter, context.max_chapter) if end_chapter is not None else context.max_chapter

    search_arguments = {
        "n": n,
        "book_path": context.book_path,
        "max_chapter": effective_end,
    }
    if start_chapter is not None:
        search_arguments["min_chapter"] = start_chapter
    results=embedding_search(query, **search_arguments)

    matches=[]
    for item in results:
        metadata = item["metadata"]
        chapter_id = int(metadata["chapter"])
        if (
            not _chapter_allowed(context, chapter_id)
            or (start_chapter is not None and chapter_id < start_chapter)
            or (effective_end is not None and chapter_id > effective_end)
        ):
            continue
        matches.append({
            "chapter_id": chapter_id,
            "title": str(metadata["title"]),
            "chunk": int(metadata["chunk"]),
            "score": float(item["score"]),
            "text": item["text"][:500],
        })
    return {
        "kind": "semantic_search",
        "query": query,
        "start_chapter": start_chapter,
        "end_chapter": effective_end,
        "matches": matches,
    }


def get_summary(level: str,context: NovelToolContext, start: int | None = None) -> ToolResultData:
    book_path = context.book_path
    size = MID_SIZE if level == "mid" else BIG_SIZE if level == "big" else None
    if context.max_chapter is not None:
        if level == "whole" and context.max_chapter < total_chapters(book_path):
            return _spoiler_error(context)
        if (
            size is not None
            and start is not None
            and is_block_start(start, size, book_path)
            and block_range(start, size, book_path)[1] > context.max_chapter
        ):
            return _spoiler_error(context)

    result: ToolResultData = {
        "kind": "summary",
        "level": level,
        "start": start,
        "content": _get_summary(level, book_path, start),
    }
    if size is not None and start is not None and is_block_start(start, size, book_path):
        result["end"] = block_range(start, size, book_path)[1]
    return result


TOOLS=[
    {
        "type":"function",
        "function":{
            "name":"get_chapter_list",
            "description":"获取小说章节标题列表。完全不传参数时返回所有章节，也可以按标题关键词或章节范围筛选。",
            "parameters":{
                "type":"object",
                "properties":{
                    "query":{
                        "type":"string",
                        "description":"可选，按章节标题中包含的文字筛选"
                    },
                    "start_chapter":{
                        "type":"integer",
                        "minimum":1,
                        "description":"可选，只返回此章及之后的章节"
                    },
                    "end_chapter":{
                        "type":"integer",
                        "minimum":1,
                        "description":"可选，只返回此章及之前的章节"
                    }
                }
            }
        }
    },
    {
        "type":"function",
        "function":{
            "name":"get_chapter",
            "description":"获取指定章节的完整正文",
            "parameters":{
                "type":"object",
                "properties":{
                    "chapter_id":{
                        "type":"integer",
                        "description":"章节编号，例如193"
                    }
                },
                "required":["chapter_id"]
            }
        }
    },
    {
        "type":"function",
        "function":{
            "name":"get_chapters",
            "description":"一次读取多个指定章节的完整正文，适合核实分散在不同章节的内容。一次最多读取10章。",
            "parameters":{
                "type":"object",
                "properties":{
                    "chapter_ids":{
                        "type":"array",
                        "items":{"type":"integer", "minimum":1},
                        "minItems":1,
                        "maxItems":10,
                        "description":"要读取的章节编号列表，按需要阅读的顺序填写"
                    }
                },
                "required":["chapter_ids"]
            }
        }
    },
    {
        "type":"function",
        "function":{
            "name":"search_keyword",
            "description":"在全书或指定章节中搜索一个关键词，并返回每次出现位置附近的上下文",
            "parameters":{
                "type":"object",
                "properties":{
                    "keyword":{
                        "type":"string",
                        "description":"要搜索的关键词（禁止输入多个关键词）"
                    },
                    "start_chapter":{
                        "type":"integer",
                        "minimum":1,
                        "description":"可选，只搜索此章及之后的内容"
                    },
                    "end_chapter":{
                        "type":"integer",
                        "minimum":1,
                        "description":"可选，只搜索此章及之前的内容"
                    },
                    "context_chars":{
                        "type":"integer",
                        "minimum":0,
                        "default":20,
                        "description":"关键词周围的上下文总字数，默认20，即向前10字、向后10字"
                    }
                },
                "required":["keyword"]
            }
        }
    },
    {
        "type":"function",
        "function":{
            "name":"semantic_search",
            "description":"使用语义搜索查找小说中与问题相关的内容，适合关键词难以匹配但意思相近的查询，最好只输入一句话",
            "parameters":{
                "type":"object",
                "properties":{
                    "query":{
                        "type":"string",
                        "description":"用一句话描述想检索的剧情"
                    },
                    "n":{
                        "type":"integer",
                        "description":"返回结果数量，默认为10"
                    },
                    "start_chapter":{
                        "type":"integer",
                        "minimum":1,
                        "description":"可选，只搜索此章及之后的内容"
                    },
                    "end_chapter":{
                        "type":"integer",
                        "minimum":1,
                        "description":"可选，只搜索此章及之前的内容"
                    }
                },
                "required":["query"]
            }
        }
    },
    {
        "type":"function",
        "function":{
            "name":"get_summary",
            "description":"读取已生成的分层剧情总结。分三层：mid=每20章一个总结，big=每100章一个总结，whole=全书总结。想快速了解某一段整体走向用mid或big，想把握全书主线用whole。只能读取人类已经生成的总结，未生成会返回提示，AI无法自行生成。",
            "parameters":{
                "type":"object",
                "properties":{
                    "level":{
                        "type":"string",
                        "enum":["mid","big","whole"],
                        "description":"总结层级：mid(20章)、big(100章)、whole(全书)"
                    },
                    "start":{
                        "type":"integer",
                        "description":"块的起始章号，必须对齐块首：mid为1,21,41...；big为1,101,201...。whole不需要此参数。范围不对齐会返回提示。"
                    }
                },
                "required":["level"]
            }
        }
    }
]


AVAILABLE_TOOLS={
    "get_chapter_list":get_chapter_list,
    "get_chapter":get_chapter,
    "get_chapters":get_chapters,
    "search_keyword":search_keyword,
    "semantic_search":semantic_search,
    "get_summary":get_summary
}


def build_tools(use_summary_tool=True):
    if use_summary_tool:
        return list(TOOLS)
    return [tool for tool in TOOLS if tool["function"]["name"] != "get_summary"]
