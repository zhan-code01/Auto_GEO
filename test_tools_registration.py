#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试工具注册情况"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    # 尝试导入工具模块
    from backend.services.agent_v2.tools import list_tools, get_tool
    
    # 获取所有已注册工具
    tools = list_tools()
    
    print(f"✓ 成功导入工具模块")
    print(f"✓ 已注册工具数量: {len(tools)}")
    print(f"\n已注册工具列表:")
    for i, tool_name in enumerate(sorted(tools), 1):
        print(f"  {i}. {tool_name}")
    
    # 检查18个核心工具是否都已注册
    core_tools = [
        "create_client", "list_clients", "get_client_detail",
        "create_project", "list_projects", "get_project_detail",
        "generate_questions", "list_questions", "generate_articles", "list_articles",
        "bind_platform", "list_bindings",
        "publish_article", "list_publish_records",
        "create_baseline", "run_recheck", "get_diagnosis",
        "upload_documents"
    ]
    
    print(f"\n✓ 检查18个核心工具:")
    missing = []
    for tool_name in core_tools:
        if tool_name in tools:
            print(f"  ✓ {tool_name}")
        else:
            print(f"  ✗ {tool_name} (缺失)")
            missing.append(tool_name)
    
    if missing:
        print(f"\n✗ 缺失的核心工具: {missing}")
        sys.exit(1)
    else:
        print(f"\n✓ 所有18个核心工具都已注册!")
        
    # 测试获取工具
    print(f"\n✓ 测试获取工具:")
    for tool_name in core_tools[:3]:  # 测试前3个
        tool = get_tool(tool_name)
        if tool:
            print(f"  ✓ {tool_name}: {tool.__name__}")
        else:
            print(f"  ✗ {tool_name}: 无法获取")
    
    print(f"\n✓ 工具注册测试通过!")
    
except Exception as e:
    print(f"✗ 错误: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
