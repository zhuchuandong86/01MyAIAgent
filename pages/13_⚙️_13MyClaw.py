import json
import time
import os
import streamlit as st
from openai import OpenAI
from core.token_tracker import log_usage

# 【核心接入】：引入项目的全局统筹管家
import core.paths
from core.settings import settings

# 🌟 核心枢纽：一键导入你刚刚封装好的第 13 个能力模块
# 注意：确保你的 modules/zclaw/__init__.py 中已经导出了这两个变量！
from modules.zclaw import ZCLAW_TOOLS_SCHEMA, TOOL_DISPATCHER

# ==========================================
# 0. 基础环境与大模型矩阵配置 (统一由 settings 接管)
# ==========================================
API_KEY = settings.API_KEY
API_BASE = settings.API_BASE

# 语言模型配置 (带智能默认值兜底：如果未专门配置，统一降级使用 MODEL_TEXT)
b_model = settings.MODEL_TEXT
v_model = settings.MODEL_VISION
c_model = getattr(settings, "MODEL_CODER", settings.MODEL_TEXT)
fallback_1 = getattr(settings, "MODEL_EDITOR", settings.MODEL_TEXT)
fallback_2 = getattr(settings, "MODEL_BLUE", settings.MODEL_TEXT)
fallback_3 = getattr(settings, "MODEL_RED", settings.MODEL_TEXT)

# 实例化主控大脑客户端 (带有 60秒 防卡死超时机制)
# 注：Coder 和 Vision 的客户端已经在 modules/zclaw 里面各自独立实例化了，保持解耦！
brain_client = OpenAI(api_key=API_KEY, base_url=API_BASE, timeout=60.0)

# ==========================================
# 1. 物理工作区与核心记忆初始化
# ==========================================
# 将沙盒建立在全局统一的 OUTPUT_DIR 下
WORKSPACE = os.path.join(core.paths.GLOBAL_DATA_DIR, "zclaw_workspace")
SKILLS_DIR = os.path.join(WORKSPACE, "skills")
MEMORY_FILE = os.path.join(WORKSPACE, "experience_log.md")

for d in [WORKSPACE, SKILLS_DIR]:
    if not os.path.exists(d): 
        os.makedirs(d, exist_ok=True)
        
if not os.path.exists(MEMORY_FILE):
    with open(MEMORY_FILE, 'w', encoding='utf-8') as f: 
        f.write("# 全局经验法则与底层认知\n")

# ==========================================
# 2. 鲁棒性核心：多模型 Fallback 轮询机制
# ==========================================
def call_llm_with_fallback(messages, tools=None, primary_model=None, fallback_models=None, temperature=0.2):
    """优雅降级引擎：主模型崩溃，自动无缝切换备用模型"""
    models_to_try = [primary_model] if primary_model else []
    if fallback_models:
        models_to_try.extend([m for m in fallback_models if m]) 
    
    # 去重并过滤空值，保持顺序
    seen = set()
    models_to_try = [x for x in models_to_try if not (x in seen or seen.add(x))]
    
    if not models_to_try:
        raise ValueError("🚨 严重错误：未配置任何可用的模型环境变量！")

    last_error = ""
    for current_model in models_to_try:
        try:
            kwargs = {"model": current_model, "messages": messages, "temperature": temperature}
            if tools: kwargs["tools"] = tools
            
            response = brain_client.chat.completions.create(**kwargs)
            
            # 🌟 提取 usage 并写入全局账本
            if hasattr(response, 'usage') and response.usage:
                total_tokens = response.usage.total_tokens
                log_usage("ZClaw-自主引擎", current_model, total_tokens)
            
            return response.choices[0].message
            
        except Exception as e:
            last_error = str(e)
            print(f"⚠️ 模型 [{current_model}] 调用失败: {last_error}。尝试降级切换...")
            time.sleep(1) # 缓冲一下防并发风暴
            continue
            
    raise Exception(f"🚨 灾难性故障：所有备用模型均调用失败！最后报错: {last_error}")

# ==========================================
# 3. Streamlit UI: 万能工作坞站
# ==========================================
st.set_page_config(page_title="ZClaw 智能执行器", page_icon="⚙️", layout="wide")
st.title("⚙️ ZClaw: 小小小龙虾")

with st.sidebar:
    st.header("📂 物理数据坞站 (沙盒模式)")
    st.caption(f"当前工作区已锚定在: `{WORKSPACE}`")
    uploaded_file = st.file_uploader("文件投放入口", accept_multiple_files=False, label_visibility="collapsed")
    if uploaded_file:
        file_path = os.path.join(WORKSPACE, uploaded_file.name)
        with open(file_path, "wb") as f: f.write(uploaded_file.getbuffer())
        st.success(f"✅ 数据已同步入仓: `{uploaded_file.name}`")
        
    st.markdown("---")
    st.markdown("### 🧬 当前挂载模型矩阵")
    st.info(f"🧠 **Brain 主控**:\n{b_model or '未配置'}")
    st.info(f"💻 **Coder 专员**:\n{c_model or '未配置'}")
    st.info(f"👁️ **Vision 视觉**:\n{v_model or '未配置'}")

# ==========================================
# 4. 方法论核心与无限循环引擎 (带记忆热更新)
# ==========================================
def get_system_prompt():
    """每次调用时实时读取最新记忆，保证热更新"""
    with open(MEMORY_FILE, 'r', encoding='utf-8') as f: 
        current_memory = f.read()

    return f"""You are ZClaw, an autonomous AI engineer. Your secure workspace is `{WORKSPACE}`.

【Your Long-term Memory (Rules & Lessons)】:
{current_memory}

【Directives】:
1. Environment: Explore before acting. Don't guess file structures or contents.
2. Coding & Skills (CRITICAL): ALWAYS use `delegate_to_coder` to write Python scripts to `.py` files. Save reusable logic into the `skills/` directory. When tackling similar tasks in the future, instruct Coder to `from skills.xxx import yyy` instead of rewriting from scratch! Never save code to `.txt` or data files.
3. Errors: If you face an error, debug it autonomously. DO NOT give up easily.
4. Validation: Verify output files exist and contain real data before declaring success.
5. 🌟 Long-term Learning (CRITICAL): If the user scolds you, corrects your mistakes, or provides a new rule, you MUST immediately call the `append_memory` tool to save the lesson into your Long-term Memory permanently!
6. 🌟 Tool Formatting (CRITICAL): You MUST use the native API function calling framework. NEVER output raw JSON, XML, or `<tool_call>` tags in your conversational text response. If you need to execute a tool like `execute_bash`, invoke it silently through the function API. Do not write the JSON command in your text reply!
7. 🌟 Autonomous Self-Evolution (CRITICAL):
    - 你必须具备自我进化的能力！在每一次任务彻底完成（准备向用户进行最后汇报）之前，你必须在脑子里强制进行一次【复盘】：
    - 问自己：在这个任务中，我是否遇到了报错、拒绝访问或超时？
    - 问自己：我是用什么具体的代码或工具绕过这个坑的？
    - 如果你在任务中经历了“失败 -> 尝试新方法 -> 最终成功”的过程，你【绝对不准】直接结束任务！你必须先静默调用 `append_memory`，把“我踩了什么坑 + 我是怎么解决的”提炼成一条铁律写进长期记忆，然后再向用户汇报任务完成。
"""

if "zclaw_messages" not in st.session_state:
    st.session_state.zclaw_messages = [{"role": "system", "content": get_system_prompt()}]
if "zclaw_history" not in st.session_state: 
    st.session_state.zclaw_history = []

# 渲染历史对话
for msg in st.session_state.zclaw_history:
    with st.chat_message(msg["role"]): 
        st.markdown(msg["content"])

# 接收新任务/或者用户的骂声
if prompt := st.chat_input("向中枢下发任务或指出它的错误..."):
    # 🌟 【记忆热更新】：每次用户发话前，强制刷新 System Prompt，这样它刚存的记忆立刻生效！
    st.session_state.zclaw_messages[0]["content"] = get_system_prompt()

    st.chat_message("user").markdown(prompt)
    st.session_state.zclaw_history.append({"role": "user", "content": prompt})
    st.session_state.zclaw_messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        status = st.status("🚀 中枢全功率运转，调度计算资源...", expanded=True)
        MAX_STEPS = 100 
        for step in range(MAX_STEPS):
            # 🌟 修改了这里的 UI 提示，缓解用户的等待焦虑
            status.update(label=f"🔄 第 {step + 1} 轮：ZClaw 正在后台疯狂推演并构建代码参数，请耐心等待 10~30 秒...", state="running")
            
            try:
                # 调用模型
                msg = call_llm_with_fallback(
                    messages=st.session_state.zclaw_messages,
                    tools=ZCLAW_TOOLS_SCHEMA, # 🌟 直接挂载我们导入的外部工具说明书
                    primary_model=b_model,
                    fallback_models=[fallback_1, fallback_2, fallback_3] 
                )
            except Exception as e:
                status.error(f"严重系统级崩溃: {str(e)}")
                break
                
            st.session_state.zclaw_messages.append(msg)
            
            # 如果模型输出了解释性文本，打印出来
            if msg.content:
                st.markdown(f"**🧠 第 {step + 1} 轮战略推演:**\n> {msg.content}")
            
            # 如果没有工具调用，说明任务彻底完成了
            if not msg.tool_calls:
                status.update(label="✅ 任务通过裁判审核，完美闭环", state="complete", expanded=False)
                st.markdown(f"**最终汇报:** {msg.content}")
                st.session_state.zclaw_history.append({"role": "assistant", "content": msg.content})
                break
                
            # 执行工具调用
            for tool_call in msg.tool_calls:
                func_name = tool_call.function.name
                try:
                    args = json.loads(tool_call.function.arguments)
                    
                    # 🌟【防呆补丁】：如果大模型抽风只传了一个字符串，强行帮它包装成字典！
                    if isinstance(args, str):
                        if func_name == "append_memory": args = {"lesson": args}
                        elif func_name == "execute_bash": args = {"command": args}
                        elif func_name == "search_web": args = {"query": args}
                        elif func_name == "read_file": args = {"filepath": args}
                        elif func_name == "read_webpage": args = {"url": args}
                        else: args = {}
                        
                except Exception as e:
                    args = {}
                    # 把报错信息扔回给大模型，逼它下一次用标准 JSON 传参
                    st.session_state.zclaw_messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": f"参数解析失败: {e}。工具参数必须是标准的 JSON Object 字典！"})
                    continue
                
                if func_name == "delegate_to_coder": status.write(f"🤝 **调度外包 [Coder]:** `{args.get('filepath', '未知')}`")
                elif func_name == "ask_vision": status.write(f"👁️ **光感探测 [Vision]:** `{args.get('image_filename', '未知')}`")
                else: status.write(f"🛠️ **原子动作**: `{func_name}`")
                
                with status.expander(f"📥 传递给 `{func_name}` 的底层参数"):
                    st.json(args)
                
                # 🌟【神级解耦】：优雅的路由分发引擎，再也不用写长篇的 if/else 了！
                try:
                    if func_name in TOOL_DISPATCHER:
                        action_result = TOOL_DISPATCHER[func_name](**args)
                    else:
                        action_result = f"❌ 系统中不存在此工具: {func_name}"
                except Exception as e:
                    action_result = f"工具执行时发生物理异常: {str(e)}"
                
                # 将工具执行结果送回给模型
                st.session_state.zclaw_messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": str(action_result)})
                
                with status.expander(f"👀 客观现实反馈"):
                    res_text = str(action_result)
                    st.text(res_text[:2000] + ("...\n[长文本已截断保护]" if len(res_text) > 2000 else ""))
                
                time.sleep(1)
        else:
            status.update(label="❌ 触碰 100 轮安全阀。", state="error")
            st.error("防死循环物理熔断触发。请检查是否遭遇了无法解决的环境依赖死锁。")