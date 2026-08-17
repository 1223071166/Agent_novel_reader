import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import (
    BIG_SIZE,
    BIG_SUMMARY_CHARS,
    CHAPTER_DIR,
    CHAPTER_SUMMARY_CHARS,
    MAX_WORKERS,
    MID_SIZE,
    MID_SUMMARY_CHARS,
    SUMMARY_DIR,
    WHOLE_SUMMARY_CHARS,
    client_summary,
    MODEL_summary,
)


# 单章摘要落盘目录
CHAPTER_SUMMARY_DIR = SUMMARY_DIR / "chapters"

# 多线程下保证 print 不互相打断
_print_lock=threading.Lock()
def _log(msg):
    with _print_lock:
        print(msg)


def total_chapters():
    """以 chapters/ 里的 .txt 文件数为准（chapters.txt 末行无换行，不可靠）。"""
    return len([
        f for f in os.listdir(CHAPTER_DIR)
        if f.endswith(".txt")
    ])


def read_chapter_text(chapter_id):
    path=os.path.join(CHAPTER_DIR,f"{chapter_id}.txt")
    if not os.path.isfile(path):
        return None
    with open(path,"r",encoding="utf-8") as f:
        return f.read()


def _summary_path(name):
    return os.path.join(SUMMARY_DIR,name)


def _read_summary_file(name):
    path=_summary_path(name)
    if not os.path.isfile(path):
        return None
    with open(path,"r",encoding="utf-8") as f:
        return f.read()


def _write_summary_file(name,content):
    os.makedirs(SUMMARY_DIR,exist_ok=True)
    with open(_summary_path(name),"w",encoding="utf-8") as f:
        f.write(content)


# ---------- 分块数学 ----------

def mid_range(start):
    """给定 mid 块的起始章号，返回 (start, end)。end 按真实总章数截断。"""
    total=total_chapters()
    end=min(start+MID_SIZE-1,total)
    return start,end


def big_range(start):
    total=total_chapters()
    end=min(start+BIG_SIZE-1,total)
    return start,end


def is_mid_start(start):
    """合法的 mid 块首：1, 21, 41, ...，且不超过总章数。"""
    total=total_chapters()
    return start>=1 and start<=total and (start-1)%MID_SIZE==0


def is_big_start(start):
    total=total_chapters()
    return start>=1 and start<=total and (start-1)%BIG_SIZE==0


def mid_starts():
    """全书所有 mid 块的起始章号列表。"""
    total=total_chapters()
    return list(range(1,total+1,MID_SIZE))


def big_starts():
    total=total_chapters()
    return list(range(1,total+1,BIG_SIZE))


def mid_name(start):
    s,e=mid_range(start)
    return f"mid_{s}-{e}.txt"


def big_name(start):
    s,e=big_range(start)
    return f"big_{s}-{e}.txt"


WHOLE_NAME="whole.txt"


# ---------- LLM 摘要底层 ----------

def _summarize(system_prompt, user_text):
    """用独立的临时 messages 调用摘要模型，绝不触碰主对话历史。"""
    response = client_summary.chat.completions.create(
        model=MODEL_summary,
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
    return full_content.strip()


def _chapter_summary_path(chapter_id):
    return os.path.join(CHAPTER_SUMMARY_DIR,f"chapter_{chapter_id}.txt")


def _read_chapter_summary(chapter_id):
    path=_chapter_summary_path(chapter_id)
    if not os.path.isfile(path):
        return None
    with open(path,"r",encoding="utf-8") as f:
        return f.read()


def _write_chapter_summary(chapter_id,content):
    os.makedirs(CHAPTER_SUMMARY_DIR,exist_ok=True)
    with open(_chapter_summary_path(chapter_id),"w",encoding="utf-8") as f:
        f.write(content)


def _summarize_chapter(chapter_id,text):
    system=(
        f"你是小说摘要器。请把下面这一章的内容压缩成约 {CHAPTER_SUMMARY_CHARS} 字的中文情节摘要，"
        "保留关键人物、事件、转折和结果，不要加入原文没有的推测，不要使用markdown格式。"
    )
    return _summarize(system,f"第 {chapter_id} 章正文：\n{text}")


def _ensure_chapter_summary(chapter_id):
    """生成或复用单章摘要。已落盘则直接读，否则现场生成并落盘。
    返回 (chapter_id, 摘要文本 或 None)。None 表示该章不存在或生成失败。"""
    cached=_read_chapter_summary(chapter_id)
    if cached is not None:
        return chapter_id,cached

    text=read_chapter_text(chapter_id)
    if text is None:
        return chapter_id,None

    _log(f"正在生成第 {chapter_id} 章总结......")
    try:
        summary=_summarize_chapter(chapter_id,text)
    except Exception as e:
        _log(f"第 {chapter_id} 章总结生成失败：{e}")
        return chapter_id,None

    _write_chapter_summary(chapter_id,summary)
    _log(f"第 {chapter_id} 章总结已生成完毕")
    return chapter_id,summary


def _combine(system_prompt,parts):
    """parts 是若干 (标签, 文本) 段落，拼接后交给模型合并。"""
    joined="\n\n".join(
        f"【{label}】\n{content}"
        for label,content in parts
    )
    return _summarize(system_prompt,joined)


# ---------- 生成：mid / big / whole ----------

def build_mid(start):
    """生成一个 mid 块总结（先章后合）。返回 (成品文本, 是否新建)。"""
    name=mid_name(start)
    existing=_read_summary_file(name)
    if existing is not None:
        return existing,False

    s,e=mid_range(start)

    # 多线程并发生成块内每章摘要；结果先按 chapter_id 收进 dict，稍后按序取用
    results={}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures={
            executor.submit(_ensure_chapter_summary,cid):cid
            for cid in range(s,e+1)
        }
        for future in as_completed(futures):
            cid,summary=future.result()
            results[cid]=summary

    failed=[cid for cid in range(s,e+1) if results.get(cid) is None and read_chapter_text(cid) is not None]
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
    content=_combine(system,chapter_summaries)
    _write_summary_file(name,content)
    return content,True


def build_big(start):
    """生成一个 big 块总结，缺失的 mid 自动递归生成。返回 (成品文本, 是否新建)。"""
    name=big_name(start)
    existing=_read_summary_file(name)
    if existing is not None:
        return existing,False

    s,e=big_range(start)

    mid_parts=[]
    for mstart in range(s,e+1,MID_SIZE):
        mcontent,_=build_mid(mstart)
        ms,me=mid_range(mstart)
        mid_parts.append((f"第{ms}-{me}章",mcontent))

    system=(
        f"你是小说摘要器。下面是第 {s}-{e} 章范围内若干段落总结，请合并成一段约 {BIG_SUMMARY_CHARS} 字的"
        "连贯中文情节总结，讲清这一大段的整体剧情脉络，不要使用markdown格式。"
    )
    content=_combine(system,mid_parts)
    _write_summary_file(name,content)
    return content,True


def build_whole():
    """生成全书总结，缺失的 big（连带 mid）自动递归生成。返回 (成品文本, 是否新建)。"""
    existing=_read_summary_file(WHOLE_NAME)
    if existing is not None:
        return existing,False

    big_parts=[]
    for bstart in big_starts():
        bcontent,_=build_big(bstart)
        bs,be=big_range(bstart)
        big_parts.append((f"第{bs}-{be}章",bcontent))

    system=(
        f"你是小说摘要器。下面是全书各大段的总结，请合并成一篇约 {WHOLE_SUMMARY_CHARS} 字的"
        "完整中文剧情总结，梳理全书主线、主要人物和关键转折，不要使用markdown格式。"
    )
    content=_combine(system,big_parts)
    _write_summary_file(WHOLE_NAME,content)
    return content,True


# ---------- 人类生成入口（/summary 调用，AI 无权） ----------

def generate_summary(level,start=None):
    """人类手动生成。返回给终端打印的状态文本。"""
    if level=="whole":
        _,created=build_whole()
        if created:
            return "已生成全书总结 whole.txt"
        return "whole.txt 已存在，如需重建请先删除该文件"

    if start is None:
        return f"生成 {level} 需要提供起始章号"

    if level=="mid":
        if not is_mid_start(start):
            return f"起始章号 {start} 不是合法的 mid 块首，应为 1,{1+MID_SIZE},{1+2*MID_SIZE}... 这样每 {MID_SIZE} 章对齐的章号"
        name=mid_name(start)
        if _read_summary_file(name) is not None:
            return f"{name} 已存在，如需重建请先删除该文件"
        _,created=build_mid(start)
        return f"已生成 {name}"

    if level=="big":
        if not is_big_start(start):
            return f"起始章号 {start} 不是合法的 big 块首，应为 1,{1+BIG_SIZE},{1+2*BIG_SIZE}... 这样每 {BIG_SIZE} 章对齐的章号"
        name=big_name(start)
        if _read_summary_file(name) is not None:
            return f"{name} 已存在，如需重建请先删除该文件"
        _,created=build_big(start)
        return f"已生成 {name}"

    return f"未知的总结层级：{level}（可用：mid / big / whole）"


# ---------- AI 读取入口（get_summary 工具，只读） ----------

def get_summary(level:str,start:int=None):
    """读取已生成的总结。只读，不会触发生成。"""
    if level=="whole":
        content=_read_summary_file(WHOLE_NAME)
        if content is None:
            return "全书总结尚未生成"
        return content

    if level=="mid":
        if start is None:
            return "查询 mid 总结需要提供起始章号"
        if not is_mid_start(start):
            s=((start-1)//MID_SIZE)*MID_SIZE+1
            e=mid_range(s)[1]
            return f"起始章号 {start} 未按 {MID_SIZE} 章对齐；第 {start} 章属于 {s}-{e} 块，请用起始章号 {s} 查询"
        content=_read_summary_file(mid_name(start))
        if content is None:
            return "该部分尚未总结"
        return content

    if level=="big":
        if start is None:
            return "查询 big 总结需要提供起始章号"
        if not is_big_start(start):
            s=((start-1)//BIG_SIZE)*BIG_SIZE+1
            e=big_range(s)[1]
            return f"起始章号 {start} 未按 {BIG_SIZE} 章对齐；第 {start} 章属于 {s}-{e} 块，请用起始章号 {s} 查询"
        content=_read_summary_file(big_name(start))
        if content is None:
            return "该部分尚未总结"
        return content

    return f"未知的总结层级：{level}（可用：mid / big / whole）"
