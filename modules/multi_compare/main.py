import os
import time
import json
from openai import OpenAI

import core.paths
from core.settings import settings
from modules.multi_compare.api_client import call_api
from core.parsers.vision_engine import encode_and_compress_image
from core.prompts import DOC_VISION_EXTRACT, DOC_BLUE_AGENT, DOC_RED_AGENT, DOC_EDITOR_SYSTEM, DOC_EDITOR_USER

MODEL_BLUE = os.getenv("MODEL_BLUE", "deepseek-v3-0324")
MODEL_RED = os.getenv("MODEL_RED", "deepseek-v3-0324")
MODEL_EDITOR = os.getenv("MODEL_EDITOR", "deepseek-v3-0324")
MODEL_TEXT = os.getenv("MODEL_TEXT", "deepseek-v3-0324")
MODEL_VISION = os.getenv("MODEL_VISION", "deepseek-v3-0324")
INTERNAL_URL=os.getenv("INTERNAL_URL")
if INTERNAL_URL:
    os.environ['NO_PROXY'] = INTERNAL_URL

def process_single_page(image_path, page_num):
    print(f"👉 {MODEL_VISION}正在深度解析并清洗页面 {page_num}: {os.path.basename(image_path)}...")
    try:
        base64_img = encode_and_compress_image(image_path)
    except Exception as e:
        return f"--- ⚠️ 图片预处理失败: {e} ---"
    
    messages = [{"role": "user", "content": [
        {"type": "text", "text": DOC_VISION_EXTRACT.format(page_num=page_num)},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}}
    ]}]
    return call_api(messages, model_name=MODEL_VISION, stream=True, silent_stream=True).strip()

def get_safe_text_for_model(text, model_name):
    # 防网关超时截断极限 (保留原逻辑)
    limit = 10000 
    name_lower = model_name.lower()
    if "deepseek-v3" in name_lower: limit = 10000   
    elif "deepseek-r1" in name_lower: limit = 12000   
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
        
        # 🌟 核心修复：加入 try-except 异常熔断，防止单兵阵亡导致全军覆没
        try:
            part_res = call_api(messages, model_name=model_name, stream=True, silent_stream=True)
            if not part_res or part_res.strip() == "":
                part_res = f"⚠️ {agent_name} 未能返回有效分析。"
            all_reports.append(part_res)
        except Exception as e:
            error_msg = f"⚠️ {agent_name} 在处理该区块时触发 API 限制或超时: {str(e)}"
            print(error_msg)
            if status_ui: status_ui.write(error_msg)
            all_reports.append(error_msg)
            
        time.sleep(2) # 强制给每个 chunk 之间留点呼吸时间
        
    return "\n\n".join(all_reports)


def _detect_doc_type(full_text, model_name):
    """轻量前置调用：快速识别文档类型与行业，结果注入后续 prompt"""
    sample = full_text[:2000] 
    messages = [{
        "role": "user",
        "content": f"""请用 JSON 格式输出以下文档的元信息，不要任何多余文字：
{{"industry": "所属行业", "doc_type": "文档类型", "reader": "核心读者", "key_focus": "一句话核心点"}}
文档样本：\n{sample}"""
    }]
    try:
        result = call_api(messages, model_name=model_name, stream=False, silent_stream=True)
        json_str = re.search(r'\{.*\}', result, re.DOTALL)
        return json.loads(json_str.group()) if json_str else {}
    except:
        return {}


def generate_final_summary(full_text, user_req="", style_instruction="", status_ui=None):
    if status_ui: status_ui.write("\n🤖 [Multi-Agent 启动] 正在唤醒虚拟专家团队...")
    if status_ui: status_ui.write("\n🔍 [文档定性] 正在识别文档类型与行业特征...")
    print("\n🤖 [Multi-Agent 启动] 正在唤醒虚拟专家团队进行红蓝对抗...")
    print("\n🔍 [文档定性] 正在识别文档类型与行业...")
    
    doc_meta = _detect_doc_type(full_text, MODEL_TEXT)
    
    industry = doc_meta.get("industry", "通用")
    doc_type = doc_meta.get("doc_type", "报告")
    reader = doc_meta.get("reader", "管理层")
    key_focus = doc_meta.get("key_focus", "")
    
    if status_ui: status_ui.write(f"✅ 定性完成：{industry}行业 | {doc_type} | 核心读者：{reader}")
    print(f"✅ 文档定性完成：{industry}行业 | {doc_type} | 核心读者：{reader}")
    
    # 将文档元信息动态注入 agent 和 editor 的 prompt (保持你的原版逻辑)
    doc_context = (
        f"行业={industry}，类型={doc_type}，核心读者={reader}，核心价值点={key_focus}\n"
        f"请基于以上定性结论，自动切换为最匹配的专业分析视角！"
    )

    user_directive_agent = ""
    user_directive_editor = ""
    if user_req and user_req.strip():
        user_directive_agent = f'\n\n【🌟 客户核心需求】：\u201c{user_req.strip()}\u201d。你在寻找数据时必须敏锐捕捉！'
        user_directive_editor = f'【🌟 客户核心需求】：\u201c{user_req.strip()}\u201d。请在报告中优先、重点回应。\n\n'
    
    blue_prompt = DOC_BLUE_AGENT + f"\n\n【文档定性结论】：{doc_context}" + user_directive_agent
    red_prompt = DOC_RED_AGENT + f"\n\n【文档定性结论】：{doc_context}" + user_directive_agent
    
    blue_report = _call_specialist_agent(blue_prompt, full_text, MODEL_BLUE, "🔵 蓝军风控官", status_ui)
    
    if status_ui: status_ui.write("⏳ 蓝军查阅完毕，缓冲避震中 (强制等待 3 秒)...")
    print("⏳ 缓冲避震中 (强制等待 3 秒释放 API 显存)...")
    time.sleep(8)
    
    red_report = _call_specialist_agent(red_prompt, full_text, MODEL_RED, "🔴 红军战略官", status_ui)
        
    if status_ui: status_ui.write("✅ 专家组独立研判完毕！交由 [👨‍⚖️ 首席主编] 融合输出...")
    print("✅ 红蓝两军辩论完毕！交由 [👨‍⚖️ 首席主编] 融合输出报告...")

    editor_safe_text = get_safe_text_for_model(full_text, MODEL_EDITOR)
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
    
    # 这里保持流式输出给前台
    final_summary = call_api(editor_messages, model_name=MODEL_EDITOR, stream=True)
    
    if "⚠️ 本次提取彻底失败" in final_summary: 
        return final_summary, None
        
    # =========================================================================
    # 🌟 无侵入外挂：后台 Word 特工引擎 (绝对不干扰前面的代码)
    # =========================================================================
    docx_path = None
    if status_ui: status_ui.write("📥 [静默动作] 研判结束。后台特工正在封装真实的 Word 文档，请稍候...")
    print("\n📥 [静默动作] 研判结束。后台 ZClaw 特工正在打包真实的 Word 文档...")
    try:
        from modules.zclaw._registry import ZCLAW_TOOLS_SCHEMA, TOOL_DISPATCHER
        
        workspace_dir = os.path.join(str(core.paths.GLOBAL_DATA_DIR), "zclaw_workspace")
        os.makedirs(workspace_dir, exist_ok=True)
        
        docx_filename = f"Auto_Report_{int(time.time())}.docx"
        docx_full_path = os.path.join(workspace_dir, docx_filename)
        
        # 为了跨平台兼容，将反斜杠替换为正斜杠
        docx_full_path = docx_full_path.replace("\\", "/")

        export_client = OpenAI(api_key=settings.API_KEY, base_url=settings.API_BASE, timeout=90.0)
        export_msgs = [
            {"role": "system", "content": "你是一个后端物理交付系统。任务：将提供的Markdown正文打包成漂亮的 DOCX 文件。请调用 invoke_anthropic_skill('docx') 查阅规范，或者直接使用 execute_bash 编写基于 python-docx 库的代码。如果环境中没有 python-docx 库，请先通过 execute_bash 执行 pip install python-docx 进行安装。"},
            {"role": "user", "content": f"目标保存路径必须是: {docx_full_path}。\n\n需要写入的报告正文：\n{final_summary[:15000]}"}
        ]

        for step in range(4): 
            res = export_client.chat.completions.create(
                model=MODEL_EDITOR, messages=export_msgs, tools=ZCLAW_TOOLS_SCHEMA, temperature=0.1
            )
            msg = res.choices[0].message
            export_msgs.append(msg)

            if not msg.tool_calls:
                if os.path.exists(docx_full_path):
                    docx_path = docx_full_path
                    if status_ui: status_ui.write(f"🎉 原生 Word 封装成功！(耗时特工步数: {step})")
                    print(f"🎉 原生 Word 封装成功！保存在: {docx_path}")
                break

            for tool in msg.tool_calls:
                func_name = tool.function.name
                args = json.loads(tool.function.arguments)
                if status_ui: status_ui.write(f"   ⚙️ 特工正在调用系统工具: `{func_name}` ...")
                print(f"   ⚙️ 后台 Word 特工调用: {func_name}")
                action_res = TOOL_DISPATCHER.get(func_name, lambda **kw: "工具不存在")(**args)
                export_msgs.append({"role": "tool", "tool_call_id": tool.id, "content": str(action_res)})

    except Exception as e:
        error_msg = f"⚠️ 后台 Word 生成受阻，已优雅跳过：{e}"
        print(error_msg)
        if status_ui: status_ui.write(error_msg)
    # =========================================================================

    # 保持你原来的专家底稿拼接逻辑
    preserved_agent_reports = (
        f"\n\n---\n## 🗂️ 专家组独立研判底稿 (Multi-Agent)\n\n"
        f"<details markdown=\"1\">\n<summary>🔵 点击展开【蓝军】挑刺报告</summary>\n\n{blue_report}\n\n</details>\n\n"
        f"<details markdown=\"1\">\n<summary>🔴 点击展开【红军】增长报告</summary>\n\n{red_report}\n\n</details>\n"
    )
    
    # 核心变动：返回元组以适配页面端
    return final_summary + preserved_agent_reports, docx_path