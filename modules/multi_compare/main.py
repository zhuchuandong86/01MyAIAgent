# modules/multi_compare/main.py
import os
import time
import json
import re  

# [核心优化] 统一引入配置与兵工厂，彻底移除陈旧的 api_client 和 os.getenv
import core.paths
from core.settings import settings
from core.llm_factory import get_llm
from core.parsers.vision_engine import encode_and_compress_image
from core.prompts import DOC_VISION_EXTRACT, DOC_BLUE_AGENT, DOC_RED_AGENT, DOC_EDITOR_SYSTEM, DOC_EDITOR_USER

def process_single_page(image_path, page_num):
    print(f"👉 {settings.MODEL_VISION}正在深度解析并清洗页面 {page_num}: {os.path.basename(image_path)}...")
    try:
        base64_img = encode_and_compress_image(image_path)
    except Exception as e:
        return f"--- ⚠️ 图片预处理失败: {e} ---"
    
    messages = [{"role": "user", "content": [
        {"type": "text", "text": DOC_VISION_EXTRACT.format(page_num=page_num)},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}}
    ]}]
    
    # [优化] 使用兵工厂，开启流式防止 504 超时，静默接收数据
    llm = get_llm(model_name=settings.MODEL_VISION, temperature=0.1, streaming=True)
    res = ""
    for chunk in llm.stream(messages):
        if chunk.content: res += chunk.content
    return res.strip()

def get_safe_text_for_model(text, model_name):
    limit = 30000 
    name_lower = model_name.lower()
    if "deepseek-v3" in name_lower: limit = 20000   
    elif "deepseek-r1" in name_lower: limit = 20000   
    elif "72b" in name_lower or "30b" in name_lower or "256k" in name_lower: limit = 20000  
        
    if len(text) > limit:
        print(f"✂️ [防 504 截断] {model_name} 触发阈值，动态截断至 {limit} 字符...")
        return text[:limit] + f"\n\n...[警告：为防网关超时，尾部已安全截断]..."
    return text

def _call_specialist_agent(role_prompt, full_text, model_name, agent_name, status_ui=None):
    msg_start = f"[{agent_name}] 启动独立阅卷，开始无损穿透阅读..."
    print(msg_start)
    if status_ui: status_ui.write(f"🕵️‍♂️ {msg_start}")
    
    chunk_size = 20000 
    chunks = [full_text[i:i+chunk_size] for i in range(0, len(full_text), chunk_size)]
    
    all_reports = []
    for idx, chunk in enumerate(chunks):
        msg_chunk = f"   -> 🔍 [{agent_name}] 正在深挖第 {idx+1}/{len(chunks)} 块核心数据 (流式保活中)..."
        print(msg_chunk)
        if status_ui: status_ui.write(msg_chunk)
        
        messages = [
            {"role": "system", "content": role_prompt},
            {"role": "user", "content": f"【当前阅读进度: 第 {idx+1}/{len(chunks)} 部分】\n请严格按照你的角色设定，深挖以下数据中的问题与细节（务必标明页码）：\n\n{chunk}"}
        ]
        
        try:
            # [优化] 使用兵工厂流式保活
            llm = get_llm(model_name=model_name, temperature=0.1, streaming=True)
            part_res = ""
            for res_chunk in llm.stream(messages):
                if res_chunk.content: part_res += res_chunk.content
                
            if not part_res or part_res.strip() == "":
                part_res = f"⚠️ {agent_name} 未能返回有效分析。"
            all_reports.append(part_res)
        except Exception as e:
            error_msg = f"⚠️ {agent_name} 在处理该区块时触发 API 限制或超时: {str(e)}"
            print(error_msg)
            if status_ui: status_ui.write(error_msg)
            all_reports.append(error_msg)
            
        time.sleep(2) 
        
    return "\n\n".join(all_reports)

# 🌟 新增：快速研判专属 Agent 调用
def _call_quick_agent(full_text, model_name, status_ui=None):
    msg = "⚡ 正在执行快速扫描解析..."
    print(msg)
    if status_ui: status_ui.write(msg)
    
    safe_text = get_safe_text_for_model(full_text, model_name)
    messages = [
        {"role": "system", "content": "你是一个高效的文档分析助手。请对提供的文本进行快速结构化解读，提取核心要点、关键数据和潜在风险，无需进行多轮推演。"},
        {"role": "user", "content": f"请对以下文档进行快速解读：\n\n{safe_text}"}
    ]
    
    llm = get_llm(model_name=model_name, temperature=0.1, streaming=True)
    res = ""
    for chunk in llm.stream(messages):
        if chunk.content: res += chunk.content
    return res

def _detect_doc_type(full_text, model_name):
    sample = full_text[:2000] 
    messages = [{
        "role": "user",
        "content": f"""请用 JSON 格式输出以下文档的元信息，不要任何多余文字：
{{"industry": "所属行业", "doc_type": "文档类型", "reader": "核心读者", "key_focus": "一句话核心点"}}
文档样本：\n{sample}"""
    }]
    try:
        # 非流式调用直接 invoke 获取 JSON
        llm = get_llm(model_name=model_name, temperature=0.1, streaming=False)
        result = llm.invoke(messages).content
        json_str = re.search(r'\{.*\}', result, re.DOTALL)
        return json.loads(json_str.group()) if json_str else {}
    except:
        return {}

# 🌟 核心修改：增加 mode 参数支持分流
def generate_final_summary(full_text, user_req="", style_instruction="", status_ui=None, mode="deep"):
    if status_ui: status_ui.write(f"\n🤖 [AI 启动] 模式：{mode}研判 | 正在准备引擎...")
    print(f"\n🤖 [AI 启动] 模式：{mode}研判 | 正在唤醒虚拟专家团队...")
    
    # 1. 文档定性 (通用能力保留)
    doc_meta = _detect_doc_type(full_text, settings.MODEL_TEXT)
    industry = doc_meta.get("industry", "通用")
    doc_type = doc_meta.get("doc_type", "报告")
    reader = doc_meta.get("reader", "管理层")
    key_focus = doc_meta.get("key_focus", "")
    
    if status_ui: status_ui.write(f"✅ 定性完成：{industry}行业 | {doc_type}")
    
    doc_context = (
        f"行业={industry}，类型={doc_type}，核心读者={reader}，核心价值点={key_focus}\n"
        f"请基于以上定性结论，自动切换为最匹配的专业分析视角！"
    )

    user_directive_editor = ""
    if user_req and user_req.strip():
        user_directive_editor = f'【🌟 客户核心需求】：\u201c{user_req.strip()}\u201d。请在报告中优先、重点回应。\n\n'

    blue_report = ""
    red_report = ""
    
    # 2. 逻辑分流
    if mode == "quick":
        # --- 快速研判模式 ---
        if status_ui: status_ui.write("🚀 正在跨过红蓝军演练，执行高效直接解读...")
        quick_report = _call_quick_agent(full_text, settings.MODEL_EDITOR, status_ui)
        editor_safe_text = get_safe_text_for_model(full_text, settings.MODEL_EDITOR)
        editor_messages = [
            {"role": "system", "content": DOC_EDITOR_SYSTEM},
            {"role": "user", "content": style_instruction + "\n\n请参考以下快速解析初稿，结合原文件，生成最终报告：\n" + 
             f"【快速解析初稿】：\n{quick_report}\n\n【原文件底稿】：\n{editor_safe_text}\n\n{user_directive_editor}"}
        ]
    else:
        # --- 深度研判模式 (原红蓝军逻辑) ---
        user_directive_agent = f'\n\n【🌟 客户核心需求】：\u201c{user_req.strip()}\u201d。' if user_req else ""
        agent_style_hint = ""
        if style_instruction:
            agent_style_hint = (
                f"\n\n【🏆 金牌分析框架指引】："
                f"\n最终的主编会采用以下框架和视角来撰写报告。请你在阅读原文档时，"
                f"务必带上这些视角，优先提取能支撑该框架的核心数据、矛盾点与论据：\n"
                f"---框架内容---\n{style_instruction[:1500]}\n------------" 
            )

        blue_prompt = DOC_BLUE_AGENT + f"\n\n【文档定性结论】：{doc_context}" + user_directive_agent + agent_style_hint
        red_prompt = DOC_RED_AGENT + f"\n\n【文档定性结论】：{doc_context}" + user_directive_agent + agent_style_hint
        blue_report = _call_specialist_agent(blue_prompt, full_text, settings.MODEL_BLUE, "🔵 蓝军风控官", status_ui)
        if status_ui: status_ui.write("⏳ 蓝军查阅完毕，缓冲避震中...")
        time.sleep(5)
        red_report = _call_specialist_agent(red_prompt, full_text, settings.MODEL_RED, "🔴 红军战略官", status_ui)
        
        editor_safe_text = get_safe_text_for_model(full_text, settings.MODEL_EDITOR)
        editor_messages = [
            {"role": "system", "content": DOC_EDITOR_SYSTEM},
            {"role": "user", "content": style_instruction + "\n\n" + DOC_EDITOR_USER.format(
                editor_safe_text=editor_safe_text,
                blue_report=blue_report,
                red_report=red_report,
                user_directive_editor=user_directive_editor,
                doc_context=doc_context 
            )}
        ]

    # 3. 首席主编统一输出
    if status_ui: status_ui.write("👨‍⚖️ 正在进行最终研判融合输出...")
    llm_editor = get_llm(model_name=settings.MODEL_EDITOR, temperature=0.1, streaming=True)
    final_summary = ""
    for chunk in llm_editor.stream(editor_messages):
        if chunk.content:
            final_summary += chunk.content
            print(chunk.content, end="", flush=True) # 控制台实时保活
    print() # 换行
    
    if "⚠️ 本次提取彻底失败" in final_summary: 
        return final_summary, None

    # =====================================================================
    # 🌟 核心拦截：把大模型原生的 <think> 替换为前端可折叠的标签
    # =====================================================================
    pattern = r"<(think|thinking|thought_process)>(.*?)</\1>"
    def thought_replacer(match):
        thought_content = match.group(2).strip()
        return (
            f"\n<details>\n"
            f"<summary>🧠 <b>点击展开：查看 AI 深度思考与推演过程</b></summary>\n\n"
            f"> {thought_content.replace(chr(10), chr(10)+'> ')}\n" 
            f"\n</details>\n\n"
        )
    final_summary = re.sub(pattern, thought_replacer, final_summary, flags=re.DOTALL | re.IGNORECASE)

    # 🛡️ 极限兜底
    if "<think>" in final_summary.lower() and "</think>" not in final_summary.lower():
        final_summary = re.sub(r"(?i)<think>", "\n<details>\n<summary>🧠 <b>点击展开：AI 深度思考过程</b></summary>\n\n> ", final_summary)
        final_summary += "\n\n</details>\n"
    # =====================================================================

    # # 4. 后台 Word 特工 (外挂逻辑保留)
    # docx_path = None
    # try:
    #     from modules.zclaw._registry import ZCLAW_TOOLS_SCHEMA, TOOL_DISPATCHER
    #     workspace_dir = os.path.join(str(core.paths.GLOBAL_DATA_DIR), "zclaw_workspace")
    #     os.makedirs(workspace_dir, exist_ok=True)
    #     docx_filename = f"Auto_Report_{int(time.time())}.docx"
    #     docx_full_path = os.path.join(workspace_dir, docx_filename).replace("\\", "/")

    #     export_client = OpenAI(api_key=settings.API_KEY, base_url=settings.API_BASE, timeout=90.0)
    #     export_msgs = [
    #         {"role": "system", "content": "任务：将Markdown正文打包成 DOCX 文件。请调用 invoke_anthropic_skill('docx') 查阅规范。确保安装 python-docx。"},
    #         {"role": "user", "content": f"目标保存路径: {docx_full_path}。\n\n需要写入的报告正文：\n{final_summary[:15000]}"}
    #     ]

    #     for step in range(4): 
    #         res = export_client.chat.completions.create(model=settings.MODEL_EDITOR, messages=export_msgs, tools=ZCLAW_TOOLS_SCHEMA, temperature=0.1)
    #         msg = res.choices[0].message
    #         export_msgs.append(msg)
    #         if not msg.tool_calls:
    #             if os.path.exists(docx_full_path): docx_path = docx_full_path
    #             break
    #         for tool in msg.tool_calls:
    #             func_name = tool.function.name
    #             args = json.loads(tool.function.arguments)
    #             action_res = TOOL_DISPATCHER.get(func_name, lambda **kw: "工具不存在")(**args)
    #             export_msgs.append({"role": "tool", "tool_call_id": tool.id, "content": str(action_res)})
    # except Exception as e:
    #     if status_ui: status_ui.write(f"⚠️ Word 封装跳过：{e}")

    # 5. 底稿拼接逻辑 (仅在深度模式下添加)
    preserved_agent_reports = ""
    if mode == "deep":
        preserved_agent_reports = (
            f"\n\n---\n### 📑 专家组独立研判底稿 (Multi-Agent 对抗记录)\n"
            f"> 💡 点击下方页签可查看 AI 专家团在生成报告前的原始碰撞过程。\n\n"
            f"<details>\n"
            f"<summary>🔍 <b>展开查看：🔵 蓝军风控官 - 深度挑刺报告</b></summary>\n\n"
            f"{blue_report}\n\n"
            f"</details>\n\n"
            f"<details>\n"
            f"<summary>🔍 <b>展开查看：🔴 红军战略官 - 增长建议报告</b></summary>\n\n"
            f"{red_report}\n\n"
            f"</details>\n"
        )
    
    return final_summary + preserved_agent_reports, None # 原代码里元组被注释了，如果需要开启 Word 功能可恢复