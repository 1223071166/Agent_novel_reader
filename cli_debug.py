import ast
import re

from config import BOOK_ID, BookPaths
from summaries import generate_summary
from tool_results import ToolResult, make_tool_result

book_path = BookPaths(BOOK_ID)


def display(result: ToolResult):
    print(result["display"])


def parse_user_tool_command(command, available_tools):
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
        except Exception:
            raise ValueError("参数解析失败，请检查格式")

    return name,args


def execute_user_tool(command, available_tools):
    try:
        name,args=parse_user_tool_command(command,available_tools)
        result=make_tool_result(available_tools[name](*args, book_path=book_path))

        print(f"\n[tool:{name}]")
        display(result)

    except Exception as e:
        print(f"\n[tool error] {e}")


def execute_summary_command(command, book_path: BookPaths):
    """人类专属的总结生成指令：/summary "mid" 21 / /summary "big" 1 / /summary "whole"。AI 无权调用。"""
    try:
        match=re.match(r'/summary\s+"?(\w+)"?(?:\s+(\d+))?\s*$',command.strip())
        if not match:
            raise ValueError('格式错误，应为 /summary "mid" 21 或 /summary "big" 1 或 /summary "whole"')

        level=match.group(1)
        start=int(match.group(2)) if match.group(2) is not None else None

        print(f"\n[summary:{level}] 生成中，可能耗时较长，请稍候...")
        result=generate_summary(level,book_path,start)
        print(result)

    except Exception as e:
        print(f"\n[summary error] {e}")


def show_help(tools):
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
