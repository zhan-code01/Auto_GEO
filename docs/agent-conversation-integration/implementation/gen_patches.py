# -*- coding: utf-8 -*-
"""
基于当前源码生成标准 unified diff（.patch），作为 git 用户备选。

只读原文件 + 在内存做 find/replace，**不修改任何源码**。
每个 .patch 的换行符与对应目标文件一致（orchestrator.py=CRLF，其余=LF），
因此 `git apply --whitespace=fix` 即可应用。

用法：python docs/agent-conversation-integration/implementation/gen_patches.py
"""

import difflib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from apply_patches import PATCHES, ROOT, load_file  # noqa: E402

# 文件 → 输出 patch 名（编号与补丁首个 id 对齐）
NAMES = {
    "backend/database/models.py": "0001-models-title-column.patch",
    "backend/scripts/fix_database.py": "0002-fix-database-title-column.patch",
    "backend/services/agent/orchestrator.py": "0003-orchestrator-title-and-display-plan.patch",
    "backend/services/agent/schemas.py": "0004-schemas-display-dto.patch",
    "backend/api/conversation.py": "0005-conversation-api-display-isolation.patch",
}

OUT = HERE / "patches"
OUT.mkdir(exist_ok=True)


def gen_for_file(file_rel: str, patches_for_file: list):
    text_lf, nl = load_file(ROOT / file_rel)  # 归一化 LF + 原始换行符
    new_text = text_lf
    for p in patches_for_file:
        if p["find"] not in new_text:
            print(f"  [!] 锚点未命中，跳过 {p['id']}（文件可能已被改动）")
            return
        new_text = new_text.replace(p["find"], p["replace"], 1)

    diff = difflib.unified_diff(
        text_lf.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile=f"a/{file_rel}",
        tofile=f"b/{file_rel}",
    )
    patch_lf = f"diff --git a/{file_rel} b/{file_rel}\n" + "".join(diff)
    if not patch_lf.endswith("\n"):
        patch_lf += "\n"
    out = patch_lf.replace("\n", "\r\n") if nl == "\r\n" else patch_lf
    (OUT / NAMES[file_rel]).write_bytes(out.encode("utf-8"))
    print(f"  [生成] {NAMES[file_rel]}  (换行符={'CRLF' if nl==chr(13)+chr(10) else 'LF'})")


def main():
    print(f"生成标准 .patch 到 {OUT}\n")
    # 按 PATCHES 出现顺序去重得到文件序列，保持分组顺序
    files_in_order = []
    for p in PATCHES:
        if p["file"] not in files_in_order:
            files_in_order.append(p["file"])
    for file_rel in files_in_order:
        group = [p for p in PATCHES if p["file"] == file_rel]
        gen_for_file(file_rel, group)
    print("\n完成。git 用户可用：git apply --whitespace=fix <patch>")


if __name__ == "__main__":
    main()
