import os
import re
import shutil

from config import NOVEL_BACKUP_FILE, NOVEL_FILE

def main():
    # 备份原文（若已存在备份则不覆盖，避免二次运行把改过的当原始）
    if not os.path.exists(NOVEL_BACKUP_FILE):
        shutil.copy2(NOVEL_FILE, NOVEL_BACKUP_FILE)
        print(f"已备份原文到 {NOVEL_BACKUP_FILE}")
    else:
        print(f"备份 {NOVEL_BACKUP_FILE} 已存在，跳过备份")

    with open(NOVEL_FILE, "r", encoding="utf-8", newline="") as f:
        text = f.read()

    # 只匹配行首的“番外-1-NNN标题”，NNN 后紧跟标题正文。
    pattern = re.compile(r"^番外-(\d+)-(\d+)(.*)$", re.MULTILINE)
    count = 0

    def repl(match):
        nonlocal count
        count += 1
        num = int(match.group(2))
        title = match.group(3)
        return f"第{10000 + num}章番外·{title}"

    new_text = pattern.sub(repl, text)

    with open(NOVEL_FILE, "w", encoding="utf-8", newline="") as f:
        f.write(new_text)

    print(f"共改写 {count} 条番外标题")


if __name__ == "__main__":
    main()
