import os
import time
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
    # 防网关超时截断极限
    limit = 10000 
    name_lower = model_name.lower()
    if "deepseek-v3" in name_lower: limit = 10000   
    elif "deepseek-r1" in name_lower: limit = 12000   
    elif "72b" in name_lower or "30b" in name_lower or "256k" in name_lower: limit = 20000  
        
    if len(text) > limit:
        print(f"✂️ [防 504 截断] {model_name} 触发阈值，动态截断至 {limit} 字符...")
        return text[:limit] + f"\n\n...[警告：为防网关超时，尾部已安全截断]..."
    return text

def _call_specialist_agent(role_prompt, full_text, model_name, agent_name):
    print(f"[{agent_name}] 正在独立阅卷分析中...")
    safe_text = get_safe_text_for_model(full_text, model_name)
    messages = [
        {"role": "system", "content": role_prompt},
        {"role": "user", "content": f"以下是完整的报告提取数据，请严格按照你的角色设定指出具体问题（标明页码）：\n\n{safe_text}"}
    ]
    return call_api(messages, model_name=model_name, stream=True, silent_stream=True)

# 🌟 核心修复：接收拆分后的 user_req 和 style_instruction
def generate_final_summary(full_text, user_req="", style_instruction=""):
    print("\n🤖 [Multi-Agent 启动] 正在唤醒虚拟专家团队进行红蓝对抗...")
    
    user_directive_agent = ""
    user_directive_editor = ""
    if user_req and user_req.strip():
        user_directive_agent = f"\n\n【🌟 客户核心需求】：“{user_req.strip()}”。你在寻找数据时必须敏锐捕捉！"
        user_directive_editor = f"【🌟 客户核心需求】：“{user_req.strip()}”。请在报告中优先、重点回应。\n\n"
    
    blue_prompt = DOC_BLUE_AGENT + user_directive_agent
    red_prompt = DOC_RED_AGENT + user_directive_agent
    
    blue_report = _call_specialist_agent(blue_prompt, full_text, MODEL_BLUE, "🔵 蓝军风控官")
    print("⏳ 缓冲避震中 (强制等待 3 秒释放 API 显存)...")
    time.sleep(3)
    red_report = _call_specialist_agent(red_prompt, full_text, MODEL_RED, "🔴 红军战略官")
        
    print("✅ 红蓝两军辩论完毕！交由 [👨‍⚖️ 首席主编] 融合输出报告...")

    editor_safe_text = get_safe_text_for_model(full_text, MODEL_EDITOR)
    editor_messages = [
        {"role": "system", "content": DOC_EDITOR_SYSTEM},
        # 🌟 核心修复：将 XML 指令置顶！保障系统防幻觉法则不被稀释
        {"role": "user", "content": style_instruction + "\n\n" + DOC_EDITOR_USER.format(
            editor_safe_text=editor_safe_text, blue_report=blue_report, red_report=red_report, user_directive_editor=user_directive_editor)}
    ]
    final_summary = call_api(editor_messages, model_name=MODEL_EDITOR, stream=True)
    
    if "⚠️ 本次提取彻底失败" in final_summary: return final_summary
        
    preserved_agent_reports = f"\n\n---\n## 🗂️ 专家组独立研判底稿 (Multi-Agent)\n\n<details markdown=\"1\">\n<summary>🔵 点击展开【蓝军】挑刺报告</summary>\n\n{blue_report}\n\n</details>\n\n<details markdown=\"1\">\n<summary>🔴 点击展开【红军】增长报告</summary>\n\n{red_report}\n\n</details>\n"
    return final_summary + preserved_agent_reports