# -*- coding: utf-8 -*-
"""验证 LangGraph END 常量的真实身份和 add_conditional_edges 路由机制。"""
from langgraph.graph import END, START, StateGraph

print(f"END type: {type(END).__name__}")
print(f"END repr: {repr(END)}")
print(f"END value: {END!r}")
print(f"END == 'END': {END == 'END'}")
print(f"END is 'END': {END is 'END'}")  # noqa: F632 - 故意验证 is 语义
print(f"hash(END) == hash('END'): {hash(END) == hash('END')}")
print()

# 测试 add_conditional_edges 的 path_map 查找
# 如果 path_map 是 {END: END}，而 _should_continue 返回 "END" 字符串
# 那么 path_map["END"] 会 KeyError（因为 key 是 END 对象，不是字符串）
path_map = {"tools": "tools", END: END}
print(f"path_map keys: {list(path_map.keys())}")
print(f"path_map key types: {[type(k).__name__ for k in path_map.keys()]}")

# 模拟 LangGraph 内部查找
test_return = "END"
try:
    result = path_map[test_return]
    print(f"path_map['END'] (string) = {result}")
except KeyError as e:
    print(f"path_map['END'] (string) -> KeyError: {e}")

test_return2 = END
try:
    result = path_map[test_return2]
    print(f"path_map[END] (object) = {result}")
except KeyError as e:
    print(f"path_map[END] (object) -> KeyError: {e}")
