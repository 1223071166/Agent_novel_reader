import os
import json
import re
import ast
from config import INFO_FILE, MODEL, SHOW_USAGE, USE_SUMMARY_TOOL, client
from summaries import generate_summary

from prompts import get_system_prompt
from novel_tools import AVAILABLE_TOOLS, build_tools, get_title, load_titles

SYSTEM_PROMPT = get_system_prompt(USE_SUMMARY_TOOL)
tools=build_tools(USE_SUMMARY_TOOL)
available_tools=AVAILABLE_TOOLS

usage_total={"input":0,"output":0,"total":0,"cached_input":0,"cache_miss_input":0,"reasoning":0}
def get_field(value,name,default=None):
    if value is None:
        return default
    if isinstance(value,dict):
        return value.get(name,default)
    return getattr(value,name,default)


def first_number(*values):
    for value in values:
        if isinstance(value,(int,float)):
            return int(value)
    return 0


def read_usage(usage):
    prompt_details=get_field(usage,"prompt_tokens_details")
    completion_details=get_field(usage,"completion_tokens_details")
    return {
        "input":get_field(usage,"prompt_tokens",0) or 0,
        "output":get_field(usage,"completion_tokens",0) or 0,
        "total":get_field(usage,"total_tokens",0) or 0,
        "cached_input":first_number(get_field(usage,"cached_tokens"),get_field(usage,"cache_read_input_tokens"),get_field(usage,"prompt_cache_hit_tokens"),get_field(prompt_details,"cached_tokens"),get_field(prompt_details,"cache_read_input_tokens"),get_field(prompt_details,"prompt_cache_hit_tokens")),
        "cache_miss_input":first_number(get_field(usage,"prompt_cache_miss_tokens"),get_field(prompt_details,"prompt_cache_miss_tokens")),
        "reasoning":get_field(completion_details,"reasoning_tokens",0) or 0,
    }


def display_usage(current):
    for key in usage_total:
        usage_total[key]+=current[key]
    print(f"[usage] input={current['input']} output={current['output']} total={current['total']} cached_input={current['cached_input']} cache_miss_input={current['cache_miss_input']} reasoning={current['reasoning']}")
    print(f"[usage cumulative] input={usage_total['input']} output={usage_total['output']} total={usage_total['total']} cached_input={usage_total['cached_input']} cache_miss_input={usage_total['cache_miss_input']} reasoning={usage_total['reasoning']}")


#工具调用后的输出显示函数
def display(name:str, args:dict, result:str):
    if name=="get_chapter_list":
        print("已获取小说章节列表")
    elif name=="get_chapter":
        chapter_id=args.get("chapter_id")
        print(f"已获取第 {chapter_id} 章（{get_title(chapter_id, '未知章节') }）的内容")
    elif name=="search_keyword":
        keyword=args.get("keyword")
        print(f"已搜索关键词 '{keyword}'，共找到 {len(result)} 个章节")
    elif name=="search_keyword_in_chapter":
        chapter_id=args.get("chapter_id")
        keyword=args.get("keyword")
        print(f"已搜索第 {chapter_id} 章（{get_title(chapter_id, '未知章节') }）的关键词 '{keyword}'，共找到 {len(result['contexts'])} 个匹配项")
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

messages=[
    {
        "role":"system",
        "content":SYSTEM_PROMPT
    }
]
def chat():
    global messages

    while True:
        try:
            user_input=input("\n[user]:")
        except (EOFError, KeyboardInterrupt):
            print("\n[chat ended]")
            break

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
            request_args={"model":MODEL,"messages":messages,"tools":tools,"stream":True}
            if SHOW_USAGE:
                request_args["stream_options"]={"include_usage":True}
            try:
                response=client.chat.completions.create(**request_args)
            except Exception as e:
                print(f"[API error] {e}")
                break

            full_content=""
            tool_calls=[]          # 按 index 累积的工具调用分片
            printed_header=False   # 是否已打印 [assistant]: 头
            current_usage=None

            for chunk in response:
                if SHOW_USAGE:
                    usage=get_field(chunk,"usage")
                    if usage is not None:
                        current_usage=read_usage(usage)
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

            if SHOW_USAGE:
                if current_usage is None:
                    print("[usage] 服务端没有返回 usage 数据")
                else:
                    display_usage(current_usage)

            # 3) 重建标准 assistant 消息
            assistant_message={"role":"assistant","content":full_content or None}
            if tool_calls:
                assistant_message["tool_calls"]=tool_calls
            messages.append(assistant_message)

            # 4) 有工具调用则执行，然后继续下一轮；否则本轮回答结束
            if tool_calls:
                for tool_call in tool_calls:
                    name=tool_call["function"]["name"]
                    try:
                        args=json.loads(tool_call["function"]["arguments"] or "{}")
                        if not isinstance(args,dict):
                            raise ValueError("Tool arguments must be a JSON object.")
                        if name not in available_tools:
                            raise ValueError(f"Unknown tool: {name}")
                    except (json.JSONDecodeError, TypeError, ValueError) as e:
                        args={}
                        result=f"Tool execution failed: {e}"
                        messages.append({
                            "role":"tool",
                            "tool_call_id":tool_call["id"],
                            "content":json.dumps(result,ensure_ascii=False)
                        })
                        print(f"[tool error] {result}")
                        continue

                    status=True

                    try:
                        result=available_tools[name](**args)
                    except Exception as e:
                        result=f"工具执行失败:{e}"
                        status=False

                    messages.append({
                        "role":"tool",
                        "tool_call_id":tool_call["id"],
                        "content":json.dumps(result,ensure_ascii=False,default=str)
                    })

                    if status:
                        display(name,args,result)

                continue

            break
if __name__=="__main__":
    #读取小说的基本信息
    with open(INFO_FILE, "r", encoding="utf-8") as f:
            txt = f.read()
    messages.append({
        "role":"system",
        "content":"这是小说的基本信息："+txt
    })
    #将小说章节目录预加载到内存中
    load_titles()
    chat()
