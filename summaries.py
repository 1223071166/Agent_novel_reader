import os
import math
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Callable
from pathlib import Path
from typing import Any
from config import (
    BIG_SIZE,
    BIG_SUMMARY_CHARS,
    CHAPTER_SUMMARY_CHARS,
    MAX_WORKERS,
    MID_SIZE,
    MID_SUMMARY_CHARS,
    WHOLE_SUMMARY_CHARS,
    BookPaths,
)
from services.model_provider import ModelConnection, get_selected_model_connection

# 多线程下保证 print 不互相打断
_print_lock=threading.Lock()
MAX_EMPTY_SUMMARY_ATTEMPTS = 3
SummaryProgressCallback = Callable[[str, str], None]


def _log(msg):
    with _print_lock:
        print(msg)


def total_chapters(book_path: BookPaths):
    """以 chapters/ 里的 .txt 文件数为准（chapters.txt 末行无换行，不可靠）。"""
    return len([
        f for f in os.listdir(book_path.chapter_dir)
        if f.endswith(".txt")
    ])


def read_chapter_text(chapter_id, book_path: BookPaths):
    path=book_path.chapter_dir / f"{chapter_id}.txt"
    if not os.path.isfile(path):
        return None
    with open(path,"r",encoding="utf-8") as f:
        return f.read()


def _summary_path(name, book_path: BookPaths):
    return book_path.summary_dir / name


def _read_summary(path: Path):
    if not path.is_file():
        return None
    content = path.read_text(encoding="utf-8")
    return content if content.strip() else None


def _write_summary(path: Path, content: str):
    if not isinstance(content, str) or not content.strip():
        raise ValueError("摘要内容不能为空")

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_file.write(content)
            temporary_path = Path(temporary_file.name)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


# ---------- 分块数学 ----------

def block_range(start, size, book_path: BookPaths):
    """返回区块的起止章号，末章按全书实际章数截断。"""
    total=total_chapters(book_path)
    end=min(start+size-1,total)
    return start,end


def is_block_start(start, size, book_path: BookPaths):
    total=total_chapters(book_path)
    return start>=1 and start<=total and (start-1)%size==0


def big_starts(book_path: BookPaths):
    total=total_chapters(book_path)
    return list(range(1,total+1,BIG_SIZE))


def block_name(level, start, size, book_path: BookPaths):
    s,e=block_range(start, size, book_path)
    return f"{level}_{s}-{e}.txt"


WHOLE_NAME="whole.txt"


# ---------- LLM 摘要底层 ----------

def _summarize(
    system_prompt,
    user_text,
    on_progress: SummaryProgressCallback | None = None,
    label: str = "正在生成总结",
    model_connection: ModelConnection | None = None,
):
    """用独立的临时 messages 调用摘要模型"""
    connection = model_connection or get_selected_model_connection()
    for attempt in range(1, MAX_EMPTY_SUMMARY_ATTEMPTS + 1):
        if on_progress is not None:
            on_progress("start", label)
        response = connection.client.chat.completions.create(
            model=connection.model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}
            ],
            stream=True
        )

        full_content = ""
        for chunk in response:
            # 经代理/隧道转发时，首帧或末帧的 choices 可能为空（例如只带 usage 的帧）
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            # 根据 OpenAI SDK 格式，delta.content 可能为 None
            if delta and delta.content:
                full_content += delta.content

        summary = full_content.strip()
        if summary:
            if on_progress is not None:
                on_progress("complete", label)
            return summary
        if attempt < MAX_EMPTY_SUMMARY_ATTEMPTS:
            _log(f"模型返回空摘要，正在进行第 {attempt + 1} 次尝试……")

    raise RuntimeError(f"模型连续 {MAX_EMPTY_SUMMARY_ATTEMPTS} 次返回空摘要")


def _chapter_summary_path(chapter_id, book_path: BookPaths):
    return book_path.summary_dir / "chapters" / f"chapter_{chapter_id}.txt"


def _summarize_chapter(
    chapter_id,
    text,
    on_progress: SummaryProgressCallback | None = None,
    model_connection: ModelConnection | None = None,
):
    system=(
        f"你是小说摘要器。请把下面这一章的内容压缩成约 {CHAPTER_SUMMARY_CHARS} 字的中文情节摘要，"
        "保留关键人物、事件、转折和结果，不要加入原文没有的推测，不要使用markdown格式。"
    )
    return _summarize(
        system,
        f"第 {chapter_id} 章正文：\n{text}",
        on_progress,
        f"正在生成第 {chapter_id} 章摘要",
        model_connection,
    )


def _ensure_chapter_summary(
    chapter_id,
    book_path: BookPaths,
    on_progress: SummaryProgressCallback | None = None,
    model_connection: ModelConnection | None = None,
):
    """生成或复用单章摘要。已落盘则直接读，否则现场生成并落盘。
    返回 (chapter_id, 摘要文本 或 None)。None 表示该章不存在或生成失败。"""
    path=_chapter_summary_path(chapter_id, book_path)
    cached=_read_summary(path)
    if cached is not None:
        return chapter_id,cached

    text=read_chapter_text(chapter_id, book_path)
    if text is None:
        return chapter_id,None

    _log(f"正在生成第 {chapter_id} 章总结......")
    try:
        summary=_summarize_chapter(chapter_id,text,on_progress,model_connection)
    except Exception as e:
        _log(f"第 {chapter_id} 章总结生成失败：{e}")
        return chapter_id,None

    _write_summary(path,summary)
    _log(f"第 {chapter_id} 章总结已生成完毕")
    return chapter_id,summary


def _combine(
    system_prompt,
    parts,
    on_progress: SummaryProgressCallback | None = None,
    label: str = "正在合并总结",
    model_connection: ModelConnection | None = None,
):
    """parts 是若干 (标签, 文本) 段落，拼接后交给模型合并。"""
    if not parts:
        raise ValueError("没有可用于生成总结的内容")
    joined="\n\n".join(
        f"【{part_label}】\n{content}"
        for part_label,content in parts
    )
    return _summarize(system_prompt,joined,on_progress,label,model_connection)


# ---------- 生成：mid / big / whole ----------

def build_mid(
    start,
    book_path: BookPaths,
    on_progress: SummaryProgressCallback | None = None,
    model_connection: ModelConnection | None = None,
):
    """生成一个 mid 块总结（先章后合）。返回 (成品文本, 是否新建)。"""
    name=block_name("mid", start, MID_SIZE, book_path)
    path=_summary_path(name, book_path)
    existing=_read_summary(path)
    if existing is not None:
        return existing,False

    s,e=block_range(start, MID_SIZE, book_path)

    # 多线程并发生成块内每章摘要；结果先按 chapter_id 收进 dict，稍后按序取用
    results={}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures={
            executor.submit(
                _ensure_chapter_summary,
                cid,
                book_path,
                on_progress,
                model_connection,
            ):cid
            for cid in range(s,e+1)
        }
        for future in as_completed(futures):
            cid,summary=future.result()
            results[cid]=summary

    failed=[cid for cid in range(s,e+1) if results.get(cid) is None and read_chapter_text(cid, book_path) is not None]
    if failed:
        raise RuntimeError(
            f"第 {s}-{e} 章中以下章节摘要生成失败：{failed}；未写出 {name}，请重试（已成功的章会复用缓存）"
        )

    # 按章节顺序还原（as_completed 是乱序的），跳过不存在的章
    chapter_summaries=[
        (f"第{cid}章",results[cid])
        for cid in range(s,e+1)
        if results.get(cid) is not None
    ]

    system=(
        f"你是小说摘要器。下面是第 {s}-{e} 章各章的摘要，请把它们合并成一段约 {MID_SUMMARY_CHARS} 字的"
        "连贯中文情节总结，按时间顺序讲清这一段的主要剧情发展，不要逐章罗列，不要使用markdown格式。"
    )
    content=_combine(
        system,
        chapter_summaries,
        on_progress,
        f"正在合并第 {s}-{e} 章摘要",
        model_connection,
    )
    _write_summary(path,content)
    return content,True


def build_big(
    start,
    book_path: BookPaths,
    on_progress: SummaryProgressCallback | None = None,
    model_connection: ModelConnection | None = None,
):
    """生成一个 big 块总结，缺失的 mid 自动递归生成。返回 (成品文本, 是否新建)。"""
    name=block_name("big", start, BIG_SIZE, book_path)
    path=_summary_path(name, book_path)
    existing=_read_summary(path)
    if existing is not None:
        return existing,False

    s,e=block_range(start, BIG_SIZE, book_path)

    mid_parts=[]
    for mstart in range(s,e+1,MID_SIZE):
        mcontent,_=build_mid(mstart, book_path, on_progress, model_connection)
        ms,me=block_range(mstart, MID_SIZE, book_path)
        mid_parts.append((f"第{ms}-{me}章",mcontent))

    system=(
        f"你是小说摘要器。下面是第 {s}-{e} 章范围内若干段落总结，请合并成一段约 {BIG_SUMMARY_CHARS} 字的"
        "连贯中文情节总结，讲清这一大段的整体剧情脉络，不要使用markdown格式。"
    )
    content=_combine(
        system,
        mid_parts,
        on_progress,
        f"正在合并第 {s}-{e} 章大段总结",
        model_connection,
    )
    _write_summary(path,content)
    return content,True


def build_whole(
    book_path: BookPaths,
    on_progress: SummaryProgressCallback | None = None,
    model_connection: ModelConnection | None = None,
):
    """生成全书总结，缺失的 big（连带 mid）自动递归生成。返回 (成品文本, 是否新建)。"""
    path=_summary_path(WHOLE_NAME, book_path)
    existing=_read_summary(path)
    if existing is not None:
        return existing,False

    big_parts=[]
    for bstart in big_starts(book_path):
        bcontent,_=build_big(bstart, book_path, on_progress, model_connection)
        bs,be=block_range(bstart, BIG_SIZE, book_path)
        big_parts.append((f"第{bs}-{be}章",bcontent))

    system=(
        f"你是小说摘要器。下面是全书各大段的总结，请合并成一篇约 {WHOLE_SUMMARY_CHARS} 字的"
        "完整中文剧情总结，梳理全书主线、主要人物和关键转折，不要使用markdown格式。"
    )
    content=_combine(
        system,
        big_parts,
        on_progress,
        "正在合并全书总结",
        model_connection,
    )
    _write_summary(path,content)
    return content,True


# ---------- 人类生成入口（/summary 调用） ----------

def generate_summary(
    level,
    book_path: BookPaths,
    start=None,
    on_progress: SummaryProgressCallback | None = None,
    model_connection: ModelConnection | None = None,
):
    """人类手动生成。返回给终端打印的状态文本。"""
    connection = model_connection or get_selected_model_connection()
    if level=="whole":
        _,created=build_whole(book_path,on_progress,connection)
        if created:
            return "已生成全书总结 whole.txt"
        return "whole.txt 已存在，如需重建请先删除该文件"

    if start is None:
        return f"生成 {level} 需要提供起始章号"

    if level=="mid":
        if not is_block_start(start, MID_SIZE, book_path):
            return f"起始章号 {start} 不是合法的 mid 块首，应为 1,{1+MID_SIZE},{1+2*MID_SIZE}... 这样每 {MID_SIZE} 章对齐的章号"
        name=block_name("mid", start, MID_SIZE, book_path)
        if _read_summary(_summary_path(name, book_path)) is not None:
            return f"{name} 已存在，如需重建请先删除该文件"
        _,created=build_mid(start, book_path,on_progress,connection)
        return f"已生成 {name}"

    if level=="big":
        if not is_block_start(start, BIG_SIZE, book_path):
            return f"起始章号 {start} 不是合法的 big 块首，应为 1,{1+BIG_SIZE},{1+2*BIG_SIZE}... 这样每 {BIG_SIZE} 章对齐的章号"
        name=block_name("big", start, BIG_SIZE, book_path)
        if _read_summary(_summary_path(name, book_path)) is not None:
            return f"{name} 已存在，如需重建请先删除该文件"
        _,created=build_big(start, book_path,on_progress,connection)
        return f"已生成 {name}"

    return f"未知的总结层级：{level}（可用：mid / big / whole）"


# ---------- 前端规划与估算 ----------

def normalize_summary_targets(
    targets: list[dict[str, Any]],
    book_path: BookPaths,
) -> list[dict[str, Any]]:
    """校验、去重并按 mid -> big -> whole 排列用户选择的成品总结。"""
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, int | None]] = set()
    level_order = {"mid": 0, "big": 1, "whole": 2}

    for target in targets:
        level = target.get("level")
        start = target.get("start")
        if level not in level_order:
            raise ValueError(f"未知的总结层级：{level}")
        if level == "whole":
            start = None
        else:
            if not isinstance(start, int) or isinstance(start, bool):
                raise ValueError(f"生成 {level} 需要提供起始章号")
            size = MID_SIZE if level == "mid" else BIG_SIZE
            if not is_block_start(start, size, book_path):
                raise ValueError(f"起始章号 {start} 不是合法的 {level} 块首")

        key = (level, start)
        if key not in seen:
            seen.add(key)
            normalized.append({"level": level, "start": start})

    return sorted(
        normalized,
        key=lambda target: (level_order[target["level"]], target["start"] or 0),
    )


def summary_inventory(book_path: BookPaths) -> list[dict[str, Any]]:
    """列出前端可选择的 mid、big 和 whole 成品。"""
    total = total_chapters(book_path)
    items: list[dict[str, Any]] = []

    for start in range(1, total + 1, MID_SIZE):
        end = block_range(start, MID_SIZE, book_path)[1]
        path = _summary_path(block_name("mid", start, MID_SIZE, book_path), book_path)
        items.append({
            "level": "mid",
            "start": start,
            "end": end,
            "exists": _read_summary(path) is not None,
        })

    for start in range(1, total + 1, BIG_SIZE):
        end = block_range(start, BIG_SIZE, book_path)[1]
        path = _summary_path(block_name("big", start, BIG_SIZE, book_path), book_path)
        items.append({
            "level": "big",
            "start": start,
            "end": end,
            "exists": _read_summary(path) is not None,
        })

    items.append({
        "level": "whole",
        "start": None,
        "end": total,
        "exists": _read_summary(_summary_path(WHOLE_NAME, book_path)) is not None,
    })
    return items


def _estimate_tokens(character_count: int) -> int:
    """中文小说的粗略估算；实际计费以模型返回的 usage 为准。"""
    return max(1, math.ceil(character_count * 1.1))


def _summary_text_length(path: Path, fallback: int) -> int:
    content = _read_summary(path)
    return len(content) if content is not None else fallback


def plan_summary_targets(
    targets: list[dict[str, Any]],
    book_path: BookPaths,
) -> dict[str, Any]:
    """展开缺失依赖，返回真正需要执行的 AI 调用及 Token 估算。"""
    normalized = normalize_summary_targets(targets, book_path)
    planned: set[tuple[str, int | None]] = set()
    total_calls = 0
    estimated_input_tokens = 0
    estimated_output_tokens = 0

    def add_call(input_tokens: int, output_tokens: int) -> None:
        nonlocal total_calls, estimated_input_tokens, estimated_output_tokens
        total_calls += 1
        estimated_input_tokens += input_tokens
        estimated_output_tokens += output_tokens

    def add_chapter(chapter_id: int) -> None:
        key = ("chapter", chapter_id)
        if key in planned or _read_summary(_chapter_summary_path(chapter_id, book_path)) is not None:
            return
        text = read_chapter_text(chapter_id, book_path)
        if text is None:
            return
        planned.add(key)
        add_call(
            _estimate_tokens(len(text) + 120),
            _estimate_tokens(CHAPTER_SUMMARY_CHARS),
        )

    def add_mid(start: int) -> None:
        key = ("mid", start)
        path = _summary_path(block_name("mid", start, MID_SIZE, book_path), book_path)
        if key in planned or _read_summary(path) is not None:
            return
        begin, end = block_range(start, MID_SIZE, book_path)
        for chapter_id in range(begin, end + 1):
            add_chapter(chapter_id)
        source_chars = sum(
            _summary_text_length(
                _chapter_summary_path(chapter_id, book_path),
                CHAPTER_SUMMARY_CHARS,
            ) + 16
            for chapter_id in range(begin, end + 1)
            if (book_path.chapter_dir / f"{chapter_id}.txt").is_file()
        )
        planned.add(key)
        add_call(
            _estimate_tokens(source_chars + 150),
            _estimate_tokens(MID_SUMMARY_CHARS),
        )

    def add_big(start: int) -> None:
        key = ("big", start)
        path = _summary_path(block_name("big", start, BIG_SIZE, book_path), book_path)
        if key in planned or _read_summary(path) is not None:
            return
        begin, end = block_range(start, BIG_SIZE, book_path)
        mid_starts = list(range(begin, end + 1, MID_SIZE))
        for mid_start in mid_starts:
            add_mid(mid_start)
        source_chars = sum(
            _summary_text_length(
                _summary_path(block_name("mid", mid_start, MID_SIZE, book_path), book_path),
                MID_SUMMARY_CHARS,
            ) + 20
            for mid_start in mid_starts
        )
        planned.add(key)
        add_call(
            _estimate_tokens(source_chars + 150),
            _estimate_tokens(BIG_SUMMARY_CHARS),
        )

    def add_whole() -> None:
        key = ("whole", None)
        path = _summary_path(WHOLE_NAME, book_path)
        if key in planned or _read_summary(path) is not None:
            return
        starts = big_starts(book_path)
        for big_start in starts:
            add_big(big_start)
        source_chars = sum(
            _summary_text_length(
                _summary_path(block_name("big", big_start, BIG_SIZE, book_path), book_path),
                BIG_SUMMARY_CHARS,
            ) + 22
            for big_start in starts
        )
        planned.add(key)
        add_call(
            _estimate_tokens(source_chars + 150),
            _estimate_tokens(WHOLE_SUMMARY_CHARS),
        )

    for target in normalized:
        if target["level"] == "mid":
            add_mid(target["start"])
        elif target["level"] == "big":
            add_big(target["start"])
        else:
            add_whole()

    return {
        "targets": normalized,
        "total_calls": total_calls,
        "estimated_input_tokens": estimated_input_tokens,
        "estimated_output_tokens": estimated_output_tokens,
        "estimated_tokens": estimated_input_tokens + estimated_output_tokens,
    }


# ---------- AI 读取入口（get_summary 工具，只读） ----------

def get_summary(level: str, book_path: BookPaths, start: int | None = None):
    """读取已生成的总结。只读，不会触发生成。"""
    if level=="whole":
        content=_read_summary(_summary_path(WHOLE_NAME, book_path))
        if content is None:
            return "全书总结尚未生成"
        return content

    if level=="mid":
        if start is None:
            return "查询 mid 总结需要提供起始章号"
        if not is_block_start(start, MID_SIZE, book_path):
            s=((start-1)//MID_SIZE)*MID_SIZE+1
            e=block_range(s, MID_SIZE, book_path)[1]
            return f"起始章号 {start} 未按 {MID_SIZE} 章对齐；第 {start} 章属于 {s}-{e} 块，请用起始章号 {s} 查询"
        name=block_name("mid", start, MID_SIZE, book_path)
        content=_read_summary(_summary_path(name, book_path))
        if content is None:
            return "该部分尚未总结"
        return content

    if level=="big":
        if start is None:
            return "查询 big 总结需要提供起始章号"
        if not is_block_start(start, BIG_SIZE, book_path):
            s=((start-1)//BIG_SIZE)*BIG_SIZE+1
            e=block_range(s, BIG_SIZE, book_path)[1]
            return f"起始章号 {start} 未按 {BIG_SIZE} 章对齐；第 {start} 章属于 {s}-{e} 块，请用起始章号 {s} 查询"
        name=block_name("big", start, BIG_SIZE, book_path)
        content=_read_summary(_summary_path(name, book_path))
        if content is None:
            return "该部分尚未总结"
        return content

    return f"未知的总结层级：{level}（可用：mid / big / whole）"
