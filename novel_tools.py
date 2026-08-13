import os
import re

from config import CHAPTER_DIR, CHAPTER_LIST
from summaries import get_summary

try:
    from embedding import search as embedding_search
except Exception:
    embedding_search = None

chapter_cache={}
titles={}
def load_titles():
    with open(CHAPTER_LIST,"r",encoding="utf-8") as f:
        lines=f.read().splitlines()

    for line in lines:
        match=re.match(r"(\d+)，?(.*)",line)
        if match:
            titles[int(match.group(1))]=match.group(2).strip()



def read_chapter(chapter_id):
    """按需读取单章正文，读过的缓存起来。返回 None 表示章节不存在。"""
    if chapter_id in chapter_cache:
        return chapter_cache[chapter_id]

    path=os.path.join(CHAPTER_DIR,f"{chapter_id}.txt")
    if not os.path.isfile(path):
        return None

    with open(path,"r",encoding="utf-8") as f:
        content=f.read()

    chapter=chapter_cache[chapter_id]={
        "title":titles.get(chapter_id,""),
        "content":content
    }
    return chapter


#可用工具列表
def get_chapter_list():
    """获取小说章节列表"""
    with open(CHAPTER_LIST,"r",encoding="utf-8") as f:
        return f.read()


def get_chapter(chapter_id:int):
    """获取指定章节正文"""
    chapter=read_chapter(chapter_id)
    if chapter is None:
        return f"不存在第 {chapter_id} 章"

    return chapter["content"]


def iter_chapters():
    """按章节号顺序遍历全书，按需读取（利用 read_chapter 的缓存）。"""
    for chapter_id in sorted(titles):
        chapter=read_chapter(chapter_id)
        if chapter is not None:
            yield chapter_id, chapter


def search_keyword(keyword:str):
    """搜索关键词出现的章节"""
    result=[]

    for chapter_id, chapter in iter_chapters():
        text=chapter["content"]

        count=text.count(keyword)

        if count>0:
            result.append({
                "chapter":chapter_id,
                "title":chapter["title"],
                "count":count
            })

    return result


def search_keyword_in_chapter(chapter_id:int, keyword:str):
    """搜索指定章节关键词上下文"""
    chapter=read_chapter(chapter_id)
    if chapter is None:
        return f"不存在第 {chapter_id} 章"

    text=chapter["content"]

    result=[]
    start=0
    length=30
    while True:
        index=text.find(keyword,start)

        if index==-1:
            break

        left=max(0,index-length)
        right=min(len(text),index+len(keyword)+length)

        result.append(
            text[left:right]
        )

        # if len(result)>=20:
        #     break

        start=index+len(keyword)

    return {
        "chapter":chapter_id,
        "keyword":keyword,
        "count":text.count(keyword),
        "contexts":result
    }


def semantic_search(query:str,n:int=10):
    """使用embedding进行小说语义检索，返回最相关文本片段"""

    if embedding_search is None:
        raise RuntimeError("embedding search is unavailable")
    results=embedding_search(query,n=n)

    output=[]

    for item in results:
        output.append({
            "text":item["text"][:500],
            "metadata":item["metadata"]
        })
    return output



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




def get_title(chapter_id, default=""):
    return titles.get(chapter_id, default)


def build_tools(use_summary_tool=True):
    if use_summary_tool:
        return list(TOOLS)
    return [tool for tool in TOOLS if tool["function"]["name"] != "get_summary"]
