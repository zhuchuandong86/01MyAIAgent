import json
import time
import os
import subprocess
import urllib.request
import urllib.parse
import re
import base64
from openai import OpenAI
import streamlit as st

# 【核心接入】：引入项目的全局统筹管家
import core.paths
from core.settings import settings

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

# 实例化客户端 (增加严格的物理超时防卡死！)
# timeout=60.0 表示：如果大模型 60 秒内连个屁都不放（没返回数据），直接抛出 Timeout 异常！
# 这样就能立刻触发我们的 try...except，从而无缝切换到备用模型！
brain_client = OpenAI(api_key=API_KEY, base_url=API_BASE, timeout=60.0)
coder_client = OpenAI(api_key=API_KEY, base_url=API_BASE, timeout=120.0) # 写代码可能比较慢，给 120 秒
vision_client = OpenAI(api_key=API_KEY, base_url=API_BASE, timeout=60.0)

# ==========================================
# 1. 物理工作区与核心记忆初始化 (统一由 paths 接管，防止污染源码目录)
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
            return response.choices[0].message
            
        except Exception as e:
            last_error = str(e)
            print(f"⚠️ 模型 [{current_model}] 调用失败: {last_error}。尝试降级切换...")
            time.sleep(1) # 缓冲一下防并发风暴
            continue
            
    raise Exception(f"🚨 灾难性故障：所有备用模型均调用失败！最后报错: {last_error}")

# ==========================================
# 3. 最小化原子工具集 (Tool Engineering)
# ==========================================
def execute_bash(command: str) -> str:
    try:
        result = subprocess.run(command, shell=True, cwd=WORKSPACE, capture_output=True, text=True, timeout=120)
        output = (result.stdout + "\n" + result.stderr).strip() or "执行成功，无输出。"
        # 【优化】：防止日志太长撑爆 Token，截取最后 4000 个字符
        if len(output) > 4000:
            output = "...[前文已省略]...\n" + output[-4000:]
        return output
    except Exception as e: return f"终端崩溃: {str(e)}"

def delegate_to_coder(filepath: str, task_description: str) -> str:
    sys_prompt = "你是底层算法架构师。只输出独立可运行的 Python 代码，绝对不要任何 Markdown 标记或多余的解释。如果涉及读写，注意编码(utf-8)。"
    try:
        msg = call_llm_with_fallback(
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": f"目标路径: {filepath}\n严苛需求:\n{task_description}"}],
            primary_model=c_model,
            fallback_models=[fallback_1, fallback_2, b_model], 
            temperature=0.1
        )
        code_content = msg.content.replace("```python", "").replace("```", "").strip()
        
        safe_path = os.path.abspath(os.path.join(WORKSPACE, filepath))
        if not safe_path.startswith(os.path.abspath(WORKSPACE)):
            return "❌ 代码注入越权拦截：禁止在工作区外写入文件！"
            
        # 【优化】：自动创建可能缺失的子目录，防止 FileNotFoundError
        os.makedirs(os.path.dirname(safe_path), exist_ok=True)
            
        with open(safe_path, 'w', encoding='utf-8') as f: f.write(code_content)
        return f"👨‍💻 Coder 已成功构建代码并保存至 {filepath}。Brain，请务必用 execute_bash 执行代码并检查结果。"
    except Exception as e: return f"Coder 脑力过载: {str(e)}"


def read_file(filepath: str) -> str:
    try:
        # 强制限定只能读取工作区内的文件，防止穿越读取系统敏感文件
        safe_path = os.path.abspath(os.path.join(WORKSPACE, filepath))
        if not safe_path.startswith(os.path.abspath(WORKSPACE)):
            return "❌ 越权读取被拦截：禁止访问工作区之外的文件！"
        with open(safe_path, 'r', encoding='utf-8') as f: return f.read()[:8000]
    except Exception as e: return f"读取失败: {str(e)}"

def search_web(query: str) -> str:
    """真正的全网搜索引擎，支持定向搜索 GitHub 等站点"""
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            # 搜索前 5 条结果
            results = list(ddgs.text(query, max_results=5))
            if not results:
                return "无检索结果"
            
            formatted_results = []
            for r in results:
                # 把标题、链接和摘要都返回给大模型
                formatted_results.append(f"【{r['title']}】({r['href']}): {r['body']}")
            return "\n---\n".join(formatted_results)
    except ImportError:
        return "❌ 缺少 duckduckgo-search 库，请先让 Coder 执行 pip install duckduckgo-search"
    except Exception as e: 
        return f"搜索链路断开: {str(e)}"

def append_memory(lesson: str) -> str:
    try:
        with open(MEMORY_FILE, 'a', encoding='utf-8') as f: f.write(f"- {lesson}\n")
        return f"✅ 认知升级完毕，经验已刻入: {lesson}"
    except Exception as e: return f"记忆刻录失败: {str(e)}"


def ask_vision(image_filename: str, question: str) -> str:
    if not v_model: return "视觉神经未接入 (模型为空)。"
    
    lower_filename = image_filename.lower()
    if lower_filename.endswith('.pdf'):
        return "❌ 工具致命报错：ask_vision 只能处理 .jpg / .png / .jpeg 等图片格式，无法直接把 .pdf 喂给视觉模型！\n【系统建议】：请立即调用 delegate_to_coder 写一个 Python 脚本将 PDF 转为图片后再处理。"
    elif not (lower_filename.endswith('.jpg') or lower_filename.endswith('.png') or lower_filename.endswith('.jpeg')):
        return f"❌ 工具报错：不支持的文件格式 {image_filename}。视觉模型只支持图片。"

    try:
        strict_prompt = question + "\n\n【最高优先级系统指令】：如果是表格或密集数据，你必须化身为无感情的机器。逐行逐列提取原文，用Markdown表格输出。严禁做归纳总结！"
        
        img_path = os.path.join(WORKSPACE, image_filename)
        with open(img_path, "rb") as f: b64_img = base64.b64encode(f.read()).decode('utf-8')
        
        response = vision_client.chat.completions.create(
            model=v_model,
            messages=[{"role": "user", "content": [{"type": "text", "text": strict_prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}}]}]
        )
        return f"👁️ 视觉中枢反馈: {response.choices[0].message.content}"
    except Exception as e: return f"视觉中枢崩溃: {str(e)}"

tools = [
    {"type": "function", "function": {"name": "execute_bash", "description": "系统终端权限。运行脚本、装包、查系统信息均用此工具。", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "read_file", "description": "文本阅读。非常重要！用于提取任务前的试探，以及代码执行后的【数据审核】！", "parameters": {"type": "object", "properties": {"filepath": {"type": "string"}}, "required": ["filepath"]}}},
    {"type": "function", "function": {
        "name": "search_web", 
        "description": "真正的全网搜索引擎。遇到写代码报错、缺库、反爬，立刻调用此工具。你可以使用高级搜索语法，例如加上 'site:github.com' 或 'site:stackoverflow.com' 来精准寻找程序员的解决方案！", 
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
    }},
    {"type": "function", "function": {"name": "append_memory", "description": "将花费极大精力排查出的经验沉淀下来。", "parameters": {"type": "object", "properties": {"lesson": {"type": "string"}}, "required": ["lesson"]}}},
    {"type": "function", "function": {"name": "ask_vision", "description": "面对扫描件、图片等调用此接口。", "parameters": {"type": "object", "properties": {"image_filename": {"type": "string"}, "question": {"type": "string"}}, "required": ["image_filename", "question"]}}},
    {"type": "function", "function": {
        "name": "delegate_to_coder", 
        "description": "算法外包接口。注意：【filepath 必须是以 .py 结尾的脚本文件名（如 skills/scraper.py）！绝对不能把代码直接保存到 .txt 或 .xlsx 等数据目标文件中！】你需要在 task_description 里告诉 Coder 脚本运行后要把数据存入哪个目标文件。", 
        "parameters": {"type": "object", "properties": {
            "filepath": {"type": "string", "description": "必须是 .py 结尾的文件路径"}, 
            "task_description": {"type": "string"}
        }, "required": ["filepath", "task_description"]}
    }}
]

# ==========================================
# 4. Streamlit UI: 万能工作坞站
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
# 5. 方法论核心与无限循环引擎 (带记忆热更新)
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
2. Coding: ALWAYS use `delegate_to_coder` to write Python scripts to `.py` files. Never save code to `.txt` or data files.
3. Errors: If you face an error, debug it autonomously. DO NOT give up easily.
4. Validation: Verify output files exist and contain real data before declaring success.
5. 🌟 Long-term Learning (CRITICAL): If the user scolds you, corrects your mistakes, or provides a new rule, you MUST immediately call the `append_memory` tool to save the lesson into your Long-term Memory permanently!
6. 🌟 Tool Formatting (CRITICAL): You MUST use the native API function calling framework. NEVER output raw JSON, XML, or `<tool_call>` tags in your conversational text response. If you need to execute a tool like `execute_bash`, invoke it silently through the function API. Do not write the JSON command in your text reply!
7. 🌟 Autonomous Self-Evolution (CRITICAL):
    -你必须具备自我进化的能力！在每一次任务彻底完成（准备向用户进行最后汇报）之前，你必须在脑子里强制进行一次【复盘】：
    -问自己：在这个任务中，我是否遇到了报错、拒绝访问或超时？
    -问自己：我是用什么具体的代码或工具绕过这个坑的？
    -如果你在任务中经历了“失败 -> 尝试新方法 -> 最终成功”的过程，你【绝对不准】直接结束任务！你必须先静默调用 append_memory，把“我踩了什么坑 + 我是怎么解决的”提炼成一条铁律写进长期记忆，然后再向用户汇报任务完成
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
        # ... (下方保留你原有的 MAX_STEPS 循环代码) ...
        MAX_STEPS = 100 
        for step in range(MAX_STEPS):
            status.update(label=f"🔄 深度反思与执行审查 (第 {step + 1}/{MAX_STEPS} 轮)...", state="running")
            
            try:
                # 调用模型
                msg = call_llm_with_fallback(
                    messages=st.session_state.zclaw_messages,
                    tools=tools,
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
                
                # 工具路由
                if func_name == "execute_bash": action_result = execute_bash(args.get("command", ""))
                elif func_name == "read_file": action_result = read_file(args.get("filepath", ""))
                elif func_name == "search_web": action_result = search_web(args.get("query", ""))
                elif func_name == "append_memory": action_result = append_memory(args.get("lesson", ""))
                elif func_name == "ask_vision": action_result = ask_vision(args.get("image_filename", ""), args.get("question", ""))
                elif func_name == "delegate_to_coder": action_result = delegate_to_coder(args.get("filepath", ""), args.get("task_description", ""))
                else: action_result = f"未知工具: {func_name}"
                
                # 将工具执行结果送回给模型
                st.session_state.zclaw_messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": str(action_result)})
                
                with status.expander(f"👀 客观现实反馈"):
                    res_text = str(action_result)
                    st.text(res_text[:2000] + ("...\n[长文本已截断保护]" if len(res_text) > 2000 else ""))
                
                time.sleep(1)
        else:
            status.update(label="❌ 触碰 100 轮安全阀。", state="error")
            st.error("防死循环物理熔断触发。请检查是否遭遇了无法解决的环境依赖死锁。")
