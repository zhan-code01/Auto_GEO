# -*- coding: utf-8 -*-
"""微博头条文章编辑器选择器。"""

ARTICLE_ENTRY = [
    '[title*="文章"]',
    '[aria-label*="文章"]',
    'div:nth-child(5) > .woo-box-flex > [class*="_svg_"]',
]
WRITE_ARTICLE_BUTTON = ['button:has-text("写文章")', '[role="button"]:has-text("写文章")']
TITLE_INPUT = ['[placeholder="请输入标题"]']
EDITOR = [".tiptap", ".ProseMirror", '[contenteditable="true"]']
COVER_ENTRY = ['button:has-text("+")', '[role="button"]:has-text("+")', 'text="+"']
COVER_CANDIDATES = ['[role="dialog"] .select-mask', ".select-mask", '[role="dialog"] [class*="cover"] img']
FOLLOWERS_ONLY_LABEL = "仅粉丝阅读全文"
FINAL_PUBLISH_BUTTON = [
    '[role="dialog"] button:has-text("发布")',
    '[role="dialog"] [role="button"]:has-text("发布")',
]
SUCCESS_TEXT = ["发布成功", "发布完成"]
