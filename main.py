import os
import json
from config import INFO_FILE, MODEL, SHOW_USAGE, USE_SUMMARY_TOOL, client

from prompts import get_system_prompt
from novel_tools import AVAILABLE_TOOLS, build_tools, load_titles
from usage_stats import display_usage, read_usage,get_field
from cli_debug import display, execute_summary_command, execute_user_tool, show_help

SYSTEM_PROMPT = get_system_prompt(USE_SUMMARY_TOOL)
tools=build_tools(USE_SUMMARY_TOOL)
available_tools=AVAILABLE_TOOLS

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
            show_help(tools)
            continue
        if user_input.startswith("/tool"):
            execute_user_tool(user_input,available_tools)
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
