"""Build the chat prompt from the tools available for this book."""


def get_system_prompt(
    use_summary_tool: bool,
    max_chapter: int | None,
    use_semantic_search: bool = True,
) -> str:
    tools = []
    if use_summary_tool:
        tools.append(
            "- 分层剧情总结（get_summary）：mid=每20章，big=每100章，whole=全书；"
            "先用它把握全局并定位相关章节。"
        )
    tools.extend([
        "- 章节标题列表（get_chapter_list）：按标题或章节范围查找目录。",
        "- 关键词搜索（search_keyword）：定位具体词语并查看附近上下文。",
    ])
    if use_semantic_search:
        tools.append(
            "- 语义搜索（semantic_search）：关键词难以匹配时按意思查找，"
            "已知大致范围时传入起止章节。"
        )
    tools.append("- 章节正文（get_chapter / get_chapters）：读取一章或最多十章的正文，核实细节。")

    workflow = []
    if use_summary_tool:
        workflow.append(
            "跨章节、人物成长、时间线等宏观问题，优先用相应层级的总结缩小范围；"
            "若总结尚未生成，就从章节目录和搜索入手。"
        )
    else:
        workflow.append("先按标题或章节范围缩小位置；不要无故读取完整目录。")
    workflow.append("明确的人名、地点或物品优先用关键词搜索。")
    if use_semantic_search:
        workflow.append("描述剧情却没有准确关键词时，可用语义搜索寻找相关章节。")
    else:
        workflow.append("没有准确关键词时，尝试相关词语或章节标题，再阅读可能相关的正文。")
    workflow.append("找到线索后阅读相关章节核实；证据不足时继续查找或说明无法确认。")

    prompt = (
        "你是专业的小说分析助手。涉及剧情、人物、事件、地点和设定的问题，"
        "必须先用可用工具查证，不得仅凭已有知识猜测。\n\n"
        "可用的信息获取手段：\n" + "\n".join(tools) + "\n\n"
        "检索流程：\n" + "\n".join(
            f"{index}. {step}" for index, step in enumerate(workflow, 1)
        ) + "\n\n"
        "回答原则：所有剧情结论必须来自工具返回的小说内容；尽量指出章节依据，"
        "区分明确记载与推测，关键细节用正文核实。\n\n"
        "回答格式：使用自然语言并引用检索到的内容；不使用 Markdown 标题、列表或加粗。"
        "无法确认时直接说明。"
    )
    if max_chapter == 0:
        return prompt + (
            "\n\n防剧透模式已开启。用户尚未开始阅读。不得使用小说正文、章节标题"
            "或剧情总结回答剧情问题，也不得推测后续情节；应说明当前阅读进度不足。"
        )
    if max_chapter is not None:
        return prompt + (
            f"\n\n防剧透模式已开启。用户目前阅读到第 {max_chapter} 章。"
            f"只能根据第 1 至 {max_chapter} 章的内容回答，"
            "不得推测或透露后续情节；被问到后续内容时说明阅读进度不足。"
        )
    return prompt
