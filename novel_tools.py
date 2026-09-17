import re

from config import BookPaths
from summaries import get_summary as _get_summary
from embedding import search
from tool_results import ToolResultData, error_result
embedding_search = search

chapter_cache={}
titles_by_book={}

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
def get_chapter_list(book_path: BookPaths) -> ToolResultData:
    """获取小说章节列表"""
    return {
        "kind": "chapter_list",
        "chapters": [
            {"chapter_id": chapter_id, "title": title}
            for chapter_id, title in sorted(load_titles(book_path).items())
        ],
    }


def get_chapter(chapter_id:int, book_path: BookPaths) -> ToolResultData:
    """获取指定章节正文"""
    chapter=read_chapter(chapter_id, book_path)
    if chapter is None:
        return error_result(f"不存在第 {chapter_id} 章")

    return {
        "kind": "chapter",
        "chapter_id": chapter_id,
        "title": chapter["title"],
        "content": chapter["content"],
    }


def iter_chapters(book_path: BookPaths):
    """按章节号顺序遍历全书，按需读取（利用 read_chapter 的缓存）。"""
    for chapter_id in sorted(load_titles(book_path)):
        chapter=read_chapter(chapter_id, book_path)
        if chapter is not None:
            yield chapter_id, chapter


def search_keyword(keyword:str, book_path: BookPaths) -> ToolResultData:
    """搜索关键词出现的章节"""
    result=[]
    for chapter_id, chapter in iter_chapters(book_path):
        text=chapter["content"]
        count=text.count(keyword)
        if count>0:
            result.append({
                "chapter_id": chapter_id,
                "title": chapter["title"],
                "count": count,
            })
    return {"kind": "keyword_search", "keyword": keyword, "matches": result}


def search_keyword_in_chapter(chapter_id:int, keyword:str, book_path: BookPaths) -> ToolResultData:
    """搜索指定章节关键词上下文"""
    if not keyword:
        return error_result("关键词不能为空")
    
    chapter=read_chapter(chapter_id, book_path)
    if chapter is None:
        return error_result(f"不存在第 {chapter_id} 章")

    text=chapter["content"]

    result=[]
    start=0
    length=30
    while True:
        index=text.find(keyword,start)

        if index==-1:
            break

        left=max(0,index-length//2)
        right=min(len(text),index+len(keyword)+length//2)

        result.append({
            "start": index,
            "end": index + len(keyword),
            "excerpt": text[left:right],
        })

        start=index+len(keyword)
    return {
        "kind": "chapter_keyword_search",
        "chapter_id": chapter_id,
        "title": chapter["title"],
        "keyword": keyword,
        "matches": result,
    }

def semantic_search(query:str,book_path: BookPaths,n:int=10) -> ToolResultData:
    """使用embedding进行小说语义检索，返回最相关文本片段"""
    global embedding_search

    results=embedding_search(query,n=n,book_path=book_path)

    matches=[]
    for item in results:
        metadata = item["metadata"]
        matches.append({
            "chapter_id": int(metadata["chapter"]),
            "title": str(metadata["title"]),
            "chunk": int(metadata["chunk"]),
            "score": float(item["score"]),
            "text": item["text"][:500],
        })
    return {"kind": "semantic_search", "query": query, "matches": matches}


def get_summary(level: str,book_path: BookPaths, start: int | None = None) -> ToolResultData:
    return {
        "kind": "summary",
        "level": level,
        "start": start,
        "content": _get_summary(level, book_path, start),
    }


TOOLS=[
    {
        "type":"function",
        "function":{
            "name":"get_chapter_list",
            "description":"获取小说所有章节列表",
            "parameters":{
                "type":"object",
                "properties":{}
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
            "name":"search_keyword",
            "description":"在所有章节中搜索关键词，只能搜索一个关键词，返回出现过的章节、标题和次数",
            "parameters":{
                "type":"object",
                "properties":{
                    "keyword":{
                        "type":"string",
                        "description":"要搜索的关键词（禁止输入多个关键词）"
                    }
                },
                "required":["keyword"]
            }
        }
    },
    {
        "type":"function",
        "function":{
            "name":"search_keyword_in_chapter",
            "description":"在指定章节搜索关键词，只能搜索一个关键词，并返回出现位置附近的上下文",
            "parameters":{
                "type":"object",
                "properties":{
                    "chapter_id":{
                        "type":"integer",
                        "description":"章节编号"
                    },
                    "keyword":{
                        "type":"string",
                        "description":"要搜索的关键词（禁止输入多个关键词）"
                    }
                },
                "required":[
                    "chapter_id",
                    "keyword"
                ]
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
                        "description":"用一句话描述像检索的剧情"
                    },
                    "n":{
                        "type":"integer",
                        "description":"返回结果数量，默认为10"
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
    "search_keyword":search_keyword,
    "search_keyword_in_chapter":search_keyword_in_chapter,
    "semantic_search":semantic_search,
    "get_summary":get_summary
}


def build_tools(use_summary_tool=True):
    if use_summary_tool:
        return list(TOOLS)
    return [tool for tool in TOOLS if tool["function"]["name"] != "get_summary"]
