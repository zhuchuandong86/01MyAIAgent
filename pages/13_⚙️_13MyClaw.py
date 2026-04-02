"""
pages/13_⚙️_13MyClaw.py — ZClaw 主控端（zclaw升级版）
────────────────────────────────────────────────────────────
升级说明（对比旧版）：

[修复 #3] 消息列表滑动窗口
  - 旧版：zclaw_messages 无限增长，长任务必定 Context 溢出崩溃
  - 新版：超过 MAX_MSG_HISTORY 条时自动截断，永远保留 index=0 的 system prompt

[Phase 1] System Prompt 按需记忆注入
  - 旧版：把 experience_log.md 全文塞入 System Prompt（随时间爆炸）
  - 新版：每次用户发言时用 search_memory(prompt) 检索最相关的经验，
          仅把相关记忆注入 System Prompt

[Phase 2] 技能库清单自动注入
  - 每次刷新 System Prompt 时同步扫描 skills/ 目录
  - 让模型在推理前就知道"我已经有哪些轮子了"

[Phase 3] install_new_tool 已在工具列表中
  - 模型可在任意轮次调用，热装载新工具无需重启
"""

import json
import time
import os
import streamlit as st
from openai import OpenAI
from core.token_tracker import log_usage

import core.paths
from core.settings import settings

# 工具矩阵（从注册中心统一导入）
from modules.zclaw import ZCLAW_TOOLS_SCHEMA, TOOL_DISPATCHER

# 按需记忆检索 & 技能扫描（供 System Prompt 热组装）
from modules.zclaw.memory_tools import search_memory
from modules.zclaw.skill_tools  import scan_skills

# ══════════════════════════════════════════════════════════
# 0. 基础环境配置
# ══════════════════════════════════════════════════════════
API_KEY  = settings.API_KEY
API_BASE = settings.API_BASE

b_model    = settings.MODEL_TEXT
v_model    = settings.MODEL_VISION
c_model    = getattr(settings, "MODEL_CODER",  settings.MODEL_TEXT)
fallback_1 = getattr(settings, "MODEL_EDITOR", settings.MODEL_TEXT)
fallback_2 = getattr(settings, "MODEL_BLUE",   settings.MODEL_TEXT)
fallback_3 = getattr(settings, "MODEL_RED",    settings.MODEL_TEXT)

brain_client = OpenAI(api_key=API_KEY, base_url=API_BASE, timeout=60.0)

# ══════════════════════════════════════════════════════════
# 1. 物理工作区初始化
# ══════════════════════════════════════════════════════════
WORKSPACE  = os.path.join(core.paths.GLOBAL_DATA_DIR, "zclaw_workspace")
SKILLS_DIR = os.path.join(WORKSPACE, "skills")
MEMORY_FILE = os.path.join(WORKSPACE, "experience_log.md")   # 人读备份

for d in [WORKSPACE, SKILLS_DIR]:
    os.makedirs(d, exist_ok=True)

if not os.path.exists(MEMORY_FILE):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        f.write("# 全局经验法则与底层认知\n\n")

# ══════════════════════════════════════════════════════════
# 2. 鲁棒性核心：多模型 Fallback 轮询机制
# ══════════════════════════════════════════════════════════
def call_llm_with_fallback(messages, tools=None, primary_model=None,
                           fallback_models=None, temperature=0.2):
    """优雅降级引擎：主模型崩溃，自动无缝切换备用模型"""
    models_to_try = [primary_model] if primary_model else []
    if fallback_models:
        models_to_try.extend([m for m in fallback_models if m])

    # 去重并过滤空值，保持顺序
    seen = set()
    models_to_try = [x for x in models_to_try if x and not (x in seen or seen.add(x))]

    if not models_to_try:
        raise ValueError("🚨 严重错误：未配置任何可用的模型环境变量！")

    last_error = ""
    for current_model in models_to_try:
        try:
            kwargs = {
                "model":       current_model,
                "messages":    messages,
                "temperature": temperature,
            }
            if tools:
                kwargs["tools"] = tools

            response = brain_client.chat.completions.create(**kwargs)

            if hasattr(response, "usage") and response.usage:
                log_usage("ZClaw-自主引擎", current_model, response.usage.total_tokens)

            return response.choices[0].message

        except Exception as e:
            last_error = str(e)
            print(f"⚠️ 模型 [{current_model}] 调用失败: {last_error}。尝试降级切换...")
            time.sleep(1)
            continue

    raise Exception(f"🚨 灾难性故障：所有备用模型均调用失败！最后报错: {last_error}")


# ══════════════════════════════════════════════════════════
# 3. 消息滑动窗口（修复 #3：防止 Context 溢出）
# ══════════════════════════════════════════════════════════
MAX_MSG_HISTORY = 40   # 保留最近 40 条（不含 system prompt）


def _trim_messages() -> None:
    """安全的滑动窗口截断，防止破坏 Tool Call 链条"""
    msgs = st.session_state.zclaw_messages
    if len(msgs) <= MAX_MSG_HISTORY + 1:
        return

    sys_msg = msgs[0]
    # 取最后 MAX_MSG_HISTORY 条，但要做安全边界检查
    keep_msgs = msgs[-(MAX_MSG_HISTORY):]
    
    # 【核心防御】：如果保留下来的第一条是 tool，说明它的 "爸爸" (assistant) 被切掉了
    # 我们必须把这条孤儿 tool 也丢弃，直到第一条是一个正常的 user 或 assistant 消息
    while keep_msgs and keep_msgs[0].get("role") == "tool":
        keep_msgs.pop(0)
        
    st.session_state.zclaw_messages = [sys_msg] + keep_msgs

# ══════════════════════════════════════════════════════════
# 4. 动态 System Prompt（按需记忆 + 技能清单注入）
# ══════════════════════════════════════════════════════════
def get_system_prompt(user_query: str = "") -> str:
    """
    每次调用时实时组装 System Prompt：
    - 相关记忆：search_memory 按 user_query 检索（Phase 1：按需注入）
    - 技能清单：scan_skills 扫描当前 skills/ 目录（Phase 2：主动感知）
    """
    relevant_memory = search_memory(user_query) if user_query.strip() else "（暂无相关历史经验）"
    skill_inventory = scan_skills()

    return f"""You are ZClaw (zclawEdition), an autonomous AI engineer. Your secure sandbox is `{WORKSPACE}`.

【Relevant Memory — Lessons from past tasks】:
{relevant_memory}

【Current Skill Inventory — Reuse before rewriting】:
{skill_inventory}

【Core Directives】:
1. **Explore first**: Use read_file / execute_bash (ls, cat) to understand the environment before acting. Never guess file structures.
2. **Memory first**: At the start of every task, call search_memory with task keywords to retrieve relevant lessons. Then call list_skills to check reusable code.
3. **Coding (CRITICAL)**: ALWAYS use delegate_to_coder to write Python scripts to .py files. Save reusable logic into skills/. In future tasks, use `from skills.xxx import yyy` instead of rewriting.
4. **Self-evolution (CRITICAL)**: If you encounter errors, debug autonomously. If you go through "fail → new approach → success", you MUST call append_memory (with tags) before reporting completion. Attach the lesson permanently.
5. **Memory hygiene**: The memory system auto-deduplicates. Periodically call evaluate_and_prune_memory to remove stale lessons.
6. **Tool expansion (OpenClaw)**: If you face a task requiring a capability you don't have, call install_new_tool to write and hot-load a new tool. The tool is immediately available in the next reasoning round.
7. **Tool formatting (CRITICAL)**: Use native API function calling ONLY. Never output raw JSON, <tool_call> tags, or code blocks as your tool invocation.
8. **Validation**: Before declaring success, verify output files exist and contain real data using read_file or execute_bash.
9. **Prune memory when needed**: If you notice memory quality degrading (contradictions, redundancy), call evaluate_and_prune_memory.
"""


# ══════════════════════════════════════════════════════════
# 5. Streamlit UI
# ══════════════════════════════════════════════════════════
st.set_page_config(page_title="ZClaw 智能执行器", page_icon="⚙️", layout="wide")
st.title("⚙️ ZClaw: zclaw自主演进引擎")

with st.sidebar:
    st.header("📂 数据坞站")
    # st.caption(f"工作区: `{WORKSPACE}`")

    uploaded_file = st.file_uploader("文件投放入口", accept_multiple_files=False, label_visibility="collapsed")
    if uploaded_file:
        file_path = os.path.join(WORKSPACE, uploaded_file.name)
        with open(file_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        st.success(f"✅ 已入仓: `{uploaded_file.name}`")

    st.markdown("---")
    st.markdown("### 🧬 模型矩阵")
    st.info(f"🧠 **Brain**: {b_model or '未配置'}")
    st.info(f"💻 **Coder**: {c_model or '未配置'}")
    st.info(f"👁️ **Vision**: {v_model or '未配置'}")

    st.markdown("---")
    # st.markdown("### 🔧 运行时工具统计")
    st.metric("已注册工具数", len(TOOL_DISPATCHER))

    with st.expander("查看已注册工具列表"):
        for name in sorted(TOOL_DISPATCHER.keys()):
            is_dynamic = name not in {
                "execute_bash", "read_file", "search_web", "read_webpage",
                "append_memory", "search_memory", "evaluate_and_prune_memory",
                "delegate_to_coder", "ask_vision", "list_skills", "install_new_tool",
            }
            st.write(f"{'🆕 ' if is_dynamic else ''}• `{name}`")

    st.markdown("---")
    # st.markdown("### 🗂️ 消息历史")
    msg_count = len(st.session_state.get("zclaw_messages", [])) - 1
    st.metric("当前消息数", f"{max(0, msg_count)} / {MAX_MSG_HISTORY}")
    if msg_count >= MAX_MSG_HISTORY * 0.8:
        st.warning(f"⚠️ 消息接近上限（{MAX_MSG_HISTORY}），旧消息将被自动滑出。")

    if st.button("🧹 剪枝记忆库"):
        from modules.zclaw.memory_tools import evaluate_and_prune_memory
        result = evaluate_and_prune_memory()
        st.info(result)

# ══════════════════════════════════════════════════════════
# 6. 会话状态初始化
# ══════════════════════════════════════════════════════════
if "zclaw_messages" not in st.session_state:
    st.session_state.zclaw_messages = [{"role": "system", "content": get_system_prompt()}]
if "zclaw_history" not in st.session_state:
    st.session_state.zclaw_history = []

# 渲染历史对话
for msg in st.session_state.zclaw_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ══════════════════════════════════════════════════════════
# 7. 主推理循环
# ══════════════════════════════════════════════════════════
if prompt := st.chat_input("向 zclaw下发任务，或指出它的错误..."):

    # 【Phase 1 热更新】：用用户输入检索相关记忆，重组 System Prompt
    st.session_state.zclaw_messages[0]["content"] = get_system_prompt(user_query=prompt)

    # 【修复 #3】：追加用户消息前先检查并截断历史
    _trim_messages()

    st.chat_message("user").markdown(prompt)
    st.session_state.zclaw_history.append({"role": "user", "content": prompt})
    st.session_state.zclaw_messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        status = st.status("🚀 zclaw全功率运转...", expanded=True)
        MAX_STEPS = 100

        for step in range(MAX_STEPS):
            status.update(
                label=(
                    f"🔄 第 {step + 1} 轮：ZClaw 正在后台推演"
                    f"（当前工具数: {len(TOOL_DISPATCHER)}）... "
                    "请耐心等待 10~30 秒"
                ),
                state="running",
            )

            try:
                msg = call_llm_with_fallback(
                    messages=st.session_state.zclaw_messages,
                    tools=ZCLAW_TOOLS_SCHEMA,   # 热注册的新工具会自动包含在内
                    primary_model=b_model,
                    fallback_models=[fallback_1, fallback_2, fallback_3],
                )
            except Exception as e:
                status.error(f"严重系统级崩溃: {str(e)}")
                break

            st.session_state.zclaw_messages.append(msg)

            # 区分【中间思考】与【最终输出】
            if msg.tool_calls:
                # 场景 A：带有工具调用，说明是中间推演过程（思考）
                if msg.content:
                    # 写入 status 内部（浅蓝色背景）。任务完成后会连同工具日志一起被折叠隐藏
                    status.markdown(f"**🧠 第 {step + 1} 轮推演思考:**")
                    status.info(msg.content)
            else:
                # 场景 B：无工具调用，说明大模型得出了最终结论！
                # 1. 关闭状态框，将之前所有的思考、日志全部折叠收起
                status.update(label="✅ 任务完成", state="complete", expanded=False)
                
                # 2. 将最终答案高亮展示在状态框外部的主对话流中
                if msg.content:
                    st.markdown(msg.content)
                    st.session_state.zclaw_history.append({"role": "assistant", "content": msg.content})
                
                # 3. 提示新工具扩展
                if len(TOOL_DISPATCHER) > 11:
                    st.info(f"🆕 本次任务后工具库扩展至 {len(TOOL_DISPATCHER)} 个工具！")
                break

            # 执行工具调用
            for tool_call in msg.tool_calls:
                func_name = tool_call.function.name
                tool_call_id = tool_call.id

                # ── 参数解析（带防呆包装）──
                try:
                    args = json.loads(tool_call.function.arguments)
                    if isinstance(args, str):
                        # 大模型抽风只传字符串时的兜底
                        _str_fallbacks = {
                            "append_memory":    {"lesson": args},
                            "execute_bash":     {"command": args},
                            "search_web":       {"query": args},
                            "search_memory":    {"query": args},
                            "read_file":        {"filepath": args},
                            "read_webpage":     {"url": args},
                            "list_skills":      {},
                        }
                        args = _str_fallbacks.get(func_name, {})
                except Exception as e:
                    st.session_state.zclaw_messages.append({
                        "role":        "tool",
                        "tool_call_id": tool_call_id,
                        "content":     f"参数解析失败: {e}。工具参数必须是标准 JSON Object！",
                    })
                    continue

                # ── UI 状态显示 ──
                if func_name == "delegate_to_coder":
                    status.write(f"🤝 **调度 [Coder]:** `{args.get('filepath', '未知')}`")
                elif func_name == "ask_vision":
                    status.write(f"👁️ **视觉探测:** `{args.get('image_filename', '未知')}`")
                elif func_name == "install_new_tool":
                    status.write(f"🔧 **自扩展：安装新工具** `{args.get('tool_name', '未知')}`")
                elif func_name == "append_memory":
                    status.write(f"🧠 **写入记忆:** `{str(args.get('lesson', ''))[:60]}...`")
                elif func_name == "search_memory":
                    status.write(f"🔍 **检索记忆:** `{args.get('query', '')}`")
                else:
                    status.write(f"🛠️ **原子动作:** `{func_name}`")

                with status.expander(f"📥 传递给 `{func_name}` 的参数"):
                    # 长代码不要全量显示，截断保护
                    display_args = {
                        k: (v[:500] + "...[截断]" if isinstance(v, str) and len(v) > 500 else v)
                        for k, v in args.items()
                    }
                    st.json(display_args)

                # ── 工具分发执行 ──
                try:
                    if func_name in TOOL_DISPATCHER:
                        action_result = TOOL_DISPATCHER[func_name](**args)
                    else:
                        action_result = (
                            f"❌ 系统中不存在工具: {func_name}。"
                            f"当前可用工具: {list(TOOL_DISPATCHER.keys())}"
                        )
                except TypeError as e:
                    action_result = (
                        f"❌ 工具 [{func_name}] 参数错误: {e}\n"
                        f"   传入参数: {args}"
                    )
                except Exception as e:
                    action_result = f"❌ 工具执行异常: {str(e)}"

                # 结果反馈给模型
                st.session_state.zclaw_messages.append({
                    "role":        "tool",
                    "tool_call_id": tool_call_id,
                    "content":     str(action_result),
                })

                with status.expander("👀 执行结果"):
                    res_text = str(action_result)
                    st.text(res_text[:2000] + ("...\n[长文本已截断]" if len(res_text) > 2000 else ""))

                # 【修复 #3】：工具执行后也检查一次滑动窗口
                _trim_messages()

                time.sleep(0.5)

        else:
            status.update(label="❌ 触碰 100 轮安全阀", state="error")
            st.error("防死循环物理熔断触发。请检查是否遭遇了无法解决的环境依赖死锁。")
