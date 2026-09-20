import argparse
import re
import shutil

from config import BookPaths


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


def save_chapters(chapters, book_path: BookPaths):
    if book_path.chapter_dir.exists():
        shutil.rmtree(book_path.chapter_dir)
    book_path.chapter_dir.mkdir(parents=True)

    chapter_list=[]

    for index,chapter in enumerate(chapters):
        filename=f"{index+1}.txt"
        path=book_path.chapter_dir / filename

        with open(path,"w",encoding="utf-8") as f:
            f.write(chapter["content"])

        chapter_list.append(
            f"{index+1}，{chapter['title']}"
        )

    with open(book_path.chapter_list,"w",encoding="utf-8") as f:
        f.write("\n".join(chapter_list))


def split_book(book_path: BookPaths) -> int:
    text = book_path.novel_file.read_text(encoding="utf-8")
    chapters = find_chapters(text)
    if not chapters:
        raise ValueError("没有识别到章节，请确认正文使用“第X章”格式")
    save_chapters(chapters, book_path)
    return len(chapters)


def main():
    parser = argparse.ArgumentParser(description="将指定书籍的原文切分为章节文件")
    parser.add_argument("book_id", help="data/books 下的书籍目录名")
    args = parser.parse_args()

    print("正在读取小说...")

    book_path = BookPaths(args.book_id)
    print("正在分析章节...")
    chapter_count = split_book(book_path)
    print(f"发现 {chapter_count} 个章节")

    print("完成！")


if __name__=="__main__":
    main()
