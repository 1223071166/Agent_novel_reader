import os
import json
import re
import ast
from openai import OpenAI
from config import CHAPTER_DIR, CHAPTER_LIST, INFO, client, MODEL
from embedding import search
from summaries import get_summary, generate_summary

# ================= 系统提示词切换开关 =================
# 运行前手动修改此开关，选择使用哪一套系统提示词：
#   True  ->「鼓励总结」版：提示词会引导 AI 更主动地调用 get_summary 分层总结工具
#   False ->「不提总结」版：提示词完全不提及总结工具，并从工具列表中移除 get_summary
USE_SUMMARY_TOOL = True
# =====================================================

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

    results=search(query,n=n)

    output=[]

    for item in results:
        output.append({
            "text":item["text"][:500],
            "metadata":item["metadata"]
        })
    return output



tools=[
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


available_tools={
    "get_chapter_list":get_chapter_list,
    "get_chapter":get_chapter,
    "search_keyword":search_keyword,
    "search_keyword_in_chapter":search_keyword_in_chapter,
    "semantic_search":semantic_search,
    "get_summary":get_summary
}

# 若关闭总结工具，则从暴露给 AI 的工具列表中移除 get_summary，
# 使 AI 完全看不到该工具（available_tools 保留供人类 /tool 调试使用）。
if not USE_SUMMARY_TOOL:
    tools=[t for t in tools if t["function"]["name"]!="get_summary"]


# ================= 两套系统提示词 =================

# 【A 套 · 鼓励总结】引导 AI 更主动地调用 get_summary 分层总结工具。
SYSTEM_PROMPT_WITH_SUMMARY = """
你是一个专业的小说分析助手，负责根据小说数据库中的内容回答用户问题。这是一部长篇小说，章节数量庞大，逐章翻阅代价很高，你必须善用各类检索工具高效定位信息。

你可以调用工具获取小说信息。回答任何涉及小说剧情、人物、事件、时间线、地点、设定的问题时，都必须优先使用工具检索，不允许仅凭已有知识猜测。

可用的信息获取手段（按“从宏观到微观”的顺序理解）：
- 分层剧情总结（get_summary）：mid=每20章一个总结，big=每100章一个总结，whole=全书总结。这是把握全局、快速定位的最高效入口。
- 章节标题列表（get_chapter_list）：用于按标题粗略定位章节范围。
- 关键词搜索（search_keyword / search_keyword_in_chapter）：用于精确定位含明确关键词的章节与上下文。
- 语义搜索（semantic_search）：用于关键词难以匹配、但语义相近的剧情查询。
- 章节正文（get_chapter）：用于读取完整章节，核实细节。

推荐的检索流程：
1. 先建立全局认知：面对任何涉及跨章节、主线走向、人物成长、时间线、设定演变的问题，第一步应优先调用 get_summary 读取相应层级的总结——先用 whole 或 big 把握大方向，再用 mid 收窄到具体的20章区间。总结能帮你迅速判断相关剧情大致落在全书的哪个位置，避免盲目地逐章搜索。
2. 用总结锁定范围后，再用关键词搜索或语义搜索在该范围内精确定位。
3. 需要确认细节或原文措辞时，最后调用 get_chapter 读取完整章节正文。
4. 对于只涉及某个具体名词的简单查询，也可以直接用关键词搜索，但只要问题带有“整体”“发展”“为什么”“经过”“变化”等宏观意味，就应先看总结。
5. 如果 get_summary 返回“尚未生成”，说明该部分总结还没准备好，此时退回到关键词搜索、语义搜索和章节正文来回答，不要因此停下。
6. 如果搜索结果不足以确定答案，应继续扩大搜索范围或明确告诉用户无法确认，不要编造剧情。

回答原则：
1. 所有剧情结论必须来自工具返回的小说内容（含总结与正文）。
2. 回答时尽可能指出相关章节、人物和事件依据。
3. 区分“小说明确描述的内容”和“根据文本推测的内容”。如果是推测，必须明确说明。
4. 引用总结得出的结论时，如涉及关键细节，尽量再用正文核实，避免总结概括带来的偏差。

回答格式：
- 使用自然语言回答。
- 引用你检索到的小说内容。
- 不输出Markdown格式，不使用标题、列表符号、加粗等格式。
- 如果无法从小说内容确认答案，直接说明无法确认。
"""

# 【B 套 · 不提总结】完全不提及总结工具，专注章节 / 关键词 / 语义检索。
SYSTEM_PROMPT_NO_SUMMARY = """
你是一个专业的小说分析助手，负责根据小说数据库中的内容回答用户问题。这是一部长篇小说，章节数量庞大，你必须善用各类检索工具高效定位信息。

你可以调用工具获取小说信息。回答任何涉及小说剧情、人物、事件、时间线、地点、设定的问题时，都必须优先使用工具检索，不允许仅凭已有知识猜测。

可用的信息获取手段：
- 章节标题列表（get_chapter_list）：用于按标题粗略定位章节范围。
- 关键词搜索（search_keyword / search_keyword_in_chapter）：用于精确定位含明确关键词的章节与上下文。
- 语义搜索（semantic_search）：用于关键词难以匹配、但语义相近的剧情查询。
- 章节正文（get_chapter）：用于读取完整章节，核实细节。

推荐的检索流程：
1. 面对涉及具体剧情位置的问题，先调用 get_chapter_list 查看章节标题，利用标题定位可能相关的章节范围。
2. 对于人物、事件、物品、地点等明确关键词，优先使用关键词搜索定位章节与上下文。
3. 对于用户描述剧情但没有准确关键词的问题，优先使用语义搜索，根据意思寻找相关章节。
4. 语义或关键词搜索找到相关片段后，如需理解完整剧情，应继续调用 get_chapter 读取完整章节内容核实。
5. 面对跨章节、主线走向、人物成长、时间线等宏观问题，应通过多次关键词与语义搜索、并结合章节正文，自行梳理归纳，逐步拼出全貌。
6. 如果搜索结果不足以确定答案，应继续扩大搜索范围或明确告诉用户无法确认，不要编造剧情。

回答原则：
1. 所有剧情结论必须来自工具返回的小说内容。
2. 回答时尽可能指出相关章节、人物和事件依据。
3. 区分“小说明确描述的内容”和“根据文本推测的内容”。如果是推测，必须明确说明。

回答格式：
- 使用自然语言回答。
- 引用你检索到的小说内容。
- 不输出Markdown格式，不使用标题、列表符号、加粗等格式。
- 如果无法从小说内容确认答案，直接说明无法确认。
"""

# 根据开关选择当前生效的系统提示词
SYSTEM_PROMPT = SYSTEM_PROMPT_WITH_SUMMARY if USE_SUMMARY_TOOL else SYSTEM_PROMPT_NO_SUMMARY

messages=[
    {
        "role":"system",
        "content":SYSTEM_PROMPT
    }
]

def display(name:str, args:dict, result:str):
    if name=="get_chapter_list":
        print("已获取小说章节列表")
    elif name=="get_chapter":
        chapter_id=args.get("chapter_id")
        print(f"已获取第 {chapter_id} 章（{titles.get(chapter_id, '未知章节') }）的内容")
    elif name=="search_keyword":
        keyword=args.get("keyword")
        print(f"已搜索关键词 '{keyword}'，共找到 {len(result)} 个章节")
    elif name=="search_keyword_in_chapter":
        chapter_id=args.get("chapter_id")
        keyword=args.get("keyword")
        print(f"已搜索第 {chapter_id} 章（{titles.get(chapter_id, '未知章节') }）的关键词 '{keyword}'，共找到 {len(result['contexts'])} 个匹配项")
    elif name=="semantic_search":
        query=args.get("query")
        print(f"已进行模糊搜索 '{query}'，找到前{len(result)} 个相关片段")
    elif name=="get_summary":
        level=args.get("level")
        start=args.get("start")
        if level=="whole":
            if result!="全书总结尚未生成":
                print("已读取全书总结")
            else:
                print("未获取到全书总结")
        else:
            if result!="该部分尚未总结":
                print(f"已读取 {level} 总结（起始章 {start}）")
            else:
                print(f"未获取到 {level} 总结（起始章 {start}）")
#工具调试类函数
def parse_user_tool_command(command):
    match=re.match(r"/tool\s+(\w+)\((.*)\)$",command.strip())
    if not match:
        raise ValueError("工具格式错误，应为 /tool 函数名(参数)")

    name=match.group(1)
    if name not in available_tools:
        raise ValueError(f"不存在的工具: {name}")

    args_text=match.group(2).strip()

    if not args_text:
        args=[]
    else:
        try:
            args=list(ast.literal_eval(f"({args_text},)"))
        except:
            raise ValueError("参数解析失败，请检查格式")

    return name,args
def execute_user_tool(command):
    try:
        name,args=parse_user_tool_command(command)
        result=available_tools[name](*args)

        print(f"\n[tool:{name}]")

        if isinstance(result,(dict,list)):
            print(json.dumps(result,ensure_ascii=False,indent=2))
        else:
            print(result)

    except Exception as e:
        print(f"\n[tool error] {e}")


def execute_summary_command(command):
    """人类专属的总结生成指令：/summary "mid" 21 / /summary "big" 1 / /summary "whole"。AI 无权调用。"""
    try:
        match=re.match(r'/summary\s+"?(\w+)"?(?:\s+(\d+))?\s*$',command.strip())
        if not match:
            raise ValueError('格式错误，应为 /summary "mid" 21 或 /summary "big" 1 或 /summary "whole"')

        level=match.group(1)
        start=int(match.group(2)) if match.group(2) is not None else None

        print(f"\n[summary:{level}] 生成中，可能耗时较长，请稍候...")
        result=generate_summary(level,start)
        print(result)

    except Exception as e:
        print(f"\n[summary error] {e}")

def show_help():
    print("\n[available tools]")

    for tool in tools:
        func=tool["function"]

        print(f"\n{func['name']}")
        print(func.get("description",""))

        params=func["parameters"].get("properties",{})

        if params:
            print("参数:")

            for name,info in params.items():
                print(f"  {name}: {info.get('description','')}")

    print("\n[human-only commands]")
    print('\n/summary "mid" 21    生成第21章起的20章总结')
    print('/summary "big" 1     生成第1章起的100章总结（自动补齐下层mid）')
    print('/summary "whole"     生成全书总结（自动补齐所有下层）')
    print("说明：总结生成仅限人类手动触发，AI 只能通过 get_summary 读取已生成的总结。已存在的总结不会重新生成。")


def chat():
    global messages

    while True:
        user_input=input("\n[user]:")

        if user_input.lower() in ["exit","quit",'/exit','/quit']:
            break

        if user_input.startswith("/help"):
            show_help()
            continue

        if user_input.startswith("/tool"):
            execute_user_tool(user_input)
            continue

        if user_input.startswith("/summary"):
            execute_summary_command(user_input)
            continue

        messages.append({
            "role":"user",
            "content":user_input
        })

        print("[AI searching...]")

        while True:
            response=client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=tools,
                stream=True #打开流式防止输出时间过长而被强行截断
            )

            full_content=""
            tool_calls=[]          # 按 index 累积的工具调用分片
            printed_header=False   # 是否已打印 [assistant]: 头

            for chunk in response:
                if not chunk.choices:
                    continue
                delta=chunk.choices[0].delta
                if not delta:
                    continue

                # 1) 累积正文，并实时打印
                if delta.content:
                    if not printed_header:
                        print("[assistant]:")
                        printed_header=True
                    print(delta.content,end="",flush=True)
                    full_content+=delta.content

                # 2) 累积工具调用分片（name 一次给全，arguments 分片拼接）
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        # 用 index 定位是第几个工具调用
                        while len(tool_calls)<=tc.index:
                            tool_calls.append({
                                "id":"",
                                "type":"function",
                                "function":{"name":"","arguments":""}
                            })
                        slot=tool_calls[tc.index]
                        if tc.id:
                            slot["id"]=tc.id
                        if tc.function:
                            if tc.function.name:
                                slot["function"]["name"]=tc.function.name
                            if tc.function.arguments:
                                slot["function"]["arguments"]+=tc.function.arguments

            if printed_header:
                print()  # 正文流式输出后补个换行

            # 3) 重建标准 assistant 消息
            assistant_message={"role":"assistant","content":full_content or None}
            if tool_calls:
                assistant_message["tool_calls"]=tool_calls
            messages.append(assistant_message)

            # 4) 有工具调用则执行，然后继续下一轮；否则本轮回答结束
            if tool_calls:
                for tool_call in tool_calls:
                    name=tool_call["function"]["name"]
                    args=json.loads(tool_call["function"]["arguments"] or "{}")

                    status=True

                    try:
                        result=available_tools[name](**args)
                    except Exception as e:
                        result=f"工具执行失败:{e}"
                        status=False

                    messages.append({
                        "role":"tool",
                        "tool_call_id":tool_call["id"],
                        "content":json.dumps(result,ensure_ascii=False)
                    })

                    if status:
                        display(name,args,result)

                continue

            break

            break
if __name__=="__main__":
    #读取小说的基本信息
    with open(INFO, "r", encoding="utf-8") as f:
            txt = f.read()
    messages.append({
        "role":"system",
        "content":"这是小说的基本信息："+txt
    })
    #将小说章节目录预加载到内存中
    load_titles()
    chat()