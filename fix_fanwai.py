import re
import shutil

SRC="novel.txt"
BACKUP="novel.txt.bak"

# 备份原文（若已存在备份则不覆盖，避免二次运行把改过的当原始）
import os
if not os.path.exists(BACKUP):
    shutil.copy2(SRC,BACKUP)
    print(f"已备份原文到 {BACKUP}")
else:
    print(f"备份 {BACKUP} 已存在，跳过备份")

with open(SRC,"r",encoding="utf-8",newline="") as f:
    text=f.read()

# 只匹配行首的 “番外-1-NNN标题”，NNN 后紧跟标题正文
# 捕获: (卷号)(番外序号)(标题正文)
pat=re.compile(r"^番外-(\d+)-(\d+)(.*)$",re.MULTILINE)

count=0
def repl(m):
    global count
    count+=1
    juan=int(m.group(1))     # 卷号（这里只有 1）
    num=int(m.group(2))      # 番外序号
    title=m.group(3)         # 标题正文
    fake_no=10000+num        # 占位章号，避开真实章号区间
    return f"第{fake_no}章番外·{title}"

new_text=pat.sub(repl,text)

with open(SRC,"w",encoding="utf-8",newline="") as f:
    f.write(new_text)

print(f"共改写 {count} 条番外标题")
