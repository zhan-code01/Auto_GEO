"""
CSDN 发布器独立测试脚本
用法: python test_csdn_publish.py
前提: Windows 上浏览器已登录 CSDN，Chrome 开启 CDP 端口 9222
"""
import asyncio
import os
import sys
from pathlib import Path

# 将 backend 加到路径
sys.path.insert(0, str(Path(__file__).parent / "backend"))

async def main():
    from playwright.async_api import async_playwright
    
    async with async_playwright() as pw:
        # 连接已登录的浏览器（CDP 模式）
        browser = await pw.chromium.connect_over_cdp("http://localhost:9222")
        contexts = browser.contexts
        if not contexts:
            print("❌ 没有找到浏览器上下文，请确认 Chrome 已开启 CDP 端口 9222")
            return
        
        context = contexts[0]
        
        # 创建测试文章数据
        test_article = type('Article', (), {
            'title': '测试文章-自动化发布验证',
            'content': '''## 测试标题
这是一篇由 AI 自动生成的测试文章。

我们正在验证 CSDN 发布器的功能是否正常。这篇文章包含文字和链接，用于测试各个发布环节。

### 关键要点
- 自动填充标题
- 自动填充正文  
- 自动添加标签
- 点击发布按钮

感谢你的耐心！''',
        })()
        
        test_account = type('Account', (), {
            'id': 1,
            'platform': 'csdn',
            'platformUid': 'test',
            'nickname': '测试账号',
        })()
        
        # 导入发布器
        from services.playwright.publishers.csdn import CsdnPublisher
        
        publisher = CsdnPublisher()
        page = context.pages[0] if context.pages else await context.new_page()
        
        print("🚀 开始测试 CSDN 发布...")
        result = await publisher.publish(page, test_article, test_account)
        
        print(f"\n{'='*50}")
        print(f"结果: {'✅ 成功' if result.get('success') else '❌ 失败'}")
        print(f"消息: {result.get('error_msg', result.get('message', 'N/A'))}")
        print(f"URL: {result.get('platform_url', 'N/A')}")
        print(f"{'='*50}")

if __name__ == '__main__':
    asyncio.run(main())
