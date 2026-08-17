import os
import re

from config import CHAPTER_DIR, CHAPTER_LIST, NOVEL_FILE


def find_chapters(text):
    pattern=re.compile(
        r"^第\s*([0-9零一二三四五六七八九十百千万]+)\s*章([^\n]*)",
        re.MULTILINE
    )
    matches=list(pattern.finditer(text))
    chapters=[]

    for i,m in enumerate(matches):
        title=m.group(2).strip()
        start=m.start()
        end=matches[i+1].start() if i+1<len(matches) else len(text)

        content=text[start:end].strip()
        content=re.sub(
            r"^第\s*[0-9零一二三四五六七八九十百千万]+\s*章\s*",
            "",
            content,
            count=1
        ).strip()

        chapters.append({
            "number":i+1,
            "title":title,
            "content":content
        })

    return chapters


def save_chapters(chapters):
    if os.path.exists(CHAPTER_DIR):
        for f in os.listdir(CHAPTER_DIR):
            path=os.path.join(CHAPTER_DIR,f)
            if os.path.isfile(path):
                os.remove(path)
    else:
        os.makedirs(CHAPTER_DIR)

    chapter_list=[]

    for index,chapter in enumerate(chapters):
        filename=f"{index+1}.txt"
        path=os.path.join(CHAPTER_DIR,filename)

        with open(path,"w",encoding="utf-8") as f:
            f.write(chapter["content"])

        chapter_list.append(
            f"{index+1}，{chapter['title']}"
        )

    with open(CHAPTER_LIST,"w",encoding="utf-8") as f:
        f.write("\n".join(chapter_list))


def main():
    print("正在读取小说...")

    with open(NOVEL_FILE,"r",encoding="utf-8") as f:
        text=f.read()

    print("正在分析章节...")

    chapters=find_chapters(text)

    print(f"发现 {len(chapters)} 个章节")

    save_chapters(chapters)

    print("完成！")


if __name__=="__main__":
    main()
