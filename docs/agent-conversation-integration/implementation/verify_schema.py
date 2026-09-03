# -*- coding: utf-8 -*-
"""
验收辅助：检查 conversation_sessions.title 列是否存在。

应用补丁 + 重启后端后，fix_database 会自动补加该列。
本脚本只读 SQLite，不修改任何数据 / 代码。

用法：python docs/agent-conversation-integration/implementation/verify_schema.py
"""

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DB_PATH = ROOT / "backend" / "database" / "auto_geo_v3.db"


def main():
    if not DB_PATH.exists():
        print(f"[!] 数据库不存在：{DB_PATH}")
        print("    请先启动一次后端（init_db 创建库），或确认路径。")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    try:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(conversation_sessions)")]
    finally:
        conn.close()

    if not cols:
        print(f"[!] 表 conversation_sessions 不存在（库可能尚未初始化）。")
        sys.exit(1)

    print("conversation_sessions 列：", cols)
    if "title" in cols:
        print("\n[PASS] title 列已存在，列表展示可用。")
        sys.exit(0)
    else:
        print("\n[FAIL] title 列缺失。请确认：")
        print("  1) 已应用补丁（apply_patches.py）；")
        print("  2) 已重启后端，使 fix_database 自动补列。")
        sys.exit(1)


if __name__ == "__main__":
    main()
