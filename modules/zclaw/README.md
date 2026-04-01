# ZClaw → OpenClaw 升级包

## 目录结构（按此放置文件）

```
your_project/
├── pages/
│   └── 13_⚙️_13MyClaw.py          ← 主 Streamlit 入口（替换原文件）
│
└── modules/
    └── zclaw/
        ├── __init__.py             ← 工具总装配线（替换）
        ├── _registry.py            ← 🆕 全局注册中心（新增）
        ├── memory_tools.py         ← 🆕 Phase 1：结构化记忆引擎（新增）
        ├── skill_tools.py          ← 🆕 Phase 2+3：技能感知+工具自扩展（新增）
        ├── system_tools.py         ← 安全加固版（替换）
        ├── coder_tools.py          ← 细节修复版（替换）
        ├── vision_tools.py         ← MIME 修复版（替换）
        └── web_tools.py            ← 降级兜底版（替换）
```

---

## 各文件变更速查

| 文件 | 状态 | 核心变更 |
|---|---|---|
| `_registry.py` | 🆕 新增 | 全局 TOOL_DISPATCHER + ZCLAW_TOOLS_SCHEMA，防循环导入 |
| `memory_tools.py` | 🆕 新增 | JSONL 结构化记忆、去重、按需检索、定期剪枝 |
| `skill_tools.py` | 🆕 新增 | scan_skills、list_skills、install_new_tool（AST 安全审计） |
| `system_tools.py` | 🔧 修改 | execute_bash 双层命令过滤；read_file os.sep 路径修复；移除 append_memory |
| `vision_tools.py` | 🔧 修改 | MIME 类型从硬编码 image/jpeg 改为动态推断 |
| `coder_tools.py` | 🔧 修改 | 路径越权检查与 system_tools 对齐；Markdown 清理更健壮 |
| `web_tools.py` | 🔧 修改 | read_webpage 增加 Jina → requests+BS4 → urllib 三级降级 |
| `__init__.py` | 🔧 修改 | 新增 7 个工具的 Schema + Dispatcher 注册 |
| `13_⚙️_13MyClaw.py` | 🔧 修改 | 滑动窗口 + 按需记忆注入 + 技能清单注入 + 侧边栏工具统计 |

---

## 全部修复与升级清单

### 🔴 安全修复
1. **execute_bash 命令过滤**：灾难级黑名单（rm -rf /、fork bomb 等）直接拒绝；高危警告级追加提示
2. **路径越权修复**：旧版 `startswith(WORKSPACE)` 会把 `/workspace2` 误判为子目录，新版追加 `os.sep` 后再比较
3. **MIME 类型修复**：vision_tools 不再硬编码 image/jpeg，改用 mimetypes 动态推断

### 🟠 稳定性修复
4. **消息滑动窗口**：zclaw_messages 超过 40 条时自动丢弃最老消息，永远保留 index=0 的 system prompt
5. **read_webpage 三级降级**：Jina 不可用时自动降级到 requests+BS4，再降级到 urllib

### 🟡 质量修复
6. **append_memory 自动去重**：Jaccard 相似度 > 70% 的记忆自动跳过，防记忆污染

### 🚀 Phase 1：结构化记忆引擎
- `append_memory`：JSONL 存储，带标签、使用计数、成功/失败标记
- `search_memory`：按需关键词检索，返回 top-k 相关记忆（替代全量注入）
- `evaluate_and_prune_memory`：定期清理超期低频记忆，防止记忆库无限膨胀

### 🚀 Phase 2：技能库主动感知
- `scan_skills()`：扫描 skills/ 目录，提取每个脚本的首行注释作为描述
- `list_skills`：工具接口，模型任务开始前调用，避免重复造轮子

### 🚀 Phase 3：工具自扩展（OpenClaw 核心）
- `install_new_tool`：模型发现能力缺口 → 写代码 → 调用此函数 → 热装载到运行时
- 三层防护：① 标识符合法性 ② AST 级危险节点扫描 ③ importlib 隔离加载
- 热注册后下一轮推理即可调用新工具，无需重启 Streamlit

### 🚀 Phase 4：演进质量闭环
- `evaluate_and_prune_memory`：可手动（侧边栏按钮）或由模型自主调用
- 记忆按使用频次加权检索，高价值经验自动浮出，低价值经验定期淘汰

---

## 注意事项

1. `_registry.py` 是新增文件，**必须**放入 `modules/zclaw/` 目录，否则所有模块启动时会报 ImportError
2. `system_tools.py` 不再定义 `append_memory`，如果你有其他地方直接 import 了旧版的 `append_memory`，需要改成从 `memory_tools` 导入
3. 建议执行 `pip install requests beautifulsoup4` 以启用 read_webpage 降级功能
4. `install_new_tool` 的 AST 审计会拒绝使用 subprocess/os.system 的代码，这是故意的安全设计
