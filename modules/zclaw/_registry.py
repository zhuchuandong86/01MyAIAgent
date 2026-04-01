"""
全局工具注册中心 (_registry.py)
────────────────────────────────────────────────────────────
独立存放 TOOL_DISPATCHER 和 ZCLAW_TOOLS_SCHEMA，
使 __init__.py 和 skill_tools.py 都能安全导入并原地修改，
彻底规避循环导入问题。

外部代码应从这里导入这两个对象的引用，
然后直接对 dict/list 进行 in-place 操作（update / append），
而不是重新赋值，否则其他模块持有的引用会失效。
"""

# 物理路由表：tool_name -> callable
TOOL_DISPATCHER: dict = {}

# 大模型看到的工具说明书（JSON Schema 列表）
ZCLAW_TOOLS_SCHEMA: list = []
