import os
from concurrent.futures import ThreadPoolExecutor

# 绝对导入路径
from modules.multi_compare.api_client import call_api
from core.parsers.vision_engine import encode_and_compress_image
from core.prompts import DOC_VISION_EXTRACT, DOC_BLUE_AGENT, DOC_RED_AGENT, DOC_EDITOR_SYSTEM, DOC_EDITOR_USER

# 统一从环境变量读取模型，带上默认值防崩
MODEL_BLUE = os.getenv("MODEL_BLUE", "deepseek-v3-0324")
MODEL_RED = os.getenv("MODEL_RED", "deepseek-v3-0324")
MODEL_EDITOR = os.getenv("MODEL_EDITOR", "deepseek-v3-0324")
MODEL_TEXT = os.getenv("MODEL_TEXT", "deepseek-v3-0324")
MODEL_VISION = os.getenv("MODEL_VISION", "deepseek-v3-0324")
INTERNAL_URL=os.getenv("INTERNAL_URL")
os.environ['NO_PROXY'] = INTERNAL_URL

def process_single_page(image_path, page_num):
    """视觉引擎：负责单张图片的解析与数据清洗"""
    print(f"👉 正在深度解析并清洗页面 {page_num}: {os.path.basename(image_path)}...")
    try:
        base64_img = encode_and_compress_image(image_path)
    except Exception as e:
        return f"--- ⚠️ 图片预处理失败: {e} ---"
    
    messages = [{
        "role": "user",
        "content": [
            {
                "type": "text", 
                "text": DOC_VISION_EXTRACT.format(page_num=page_num)
            },
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}}
        ]
    }]
    
    # 【修复】：这里直接用顶部定义好的 MODEL_VISION，不要再从 config 导了
    result = call_api(messages, model_name=MODEL_VISION, stream=False)
    return result.strip()

def get_safe_text_for_model(text, model_name):
    """根据不同模型的真实上下文上限，动态截断文本"""
    limit = 40000 
    name_lower = model_name.lower()
    
    if "deepseek-v3-0324" in name_lower:
        limit = 38000   
    elif "deepseek-r1" in name_lower:
        limit = 60000   
    elif "72b" in name_lower or "30b" in name_lower or "256k" in name_lower:
        limit = 120000  
        
    if len(text) > limit:
        print(f"✂️ [安全管控] {model_name} 触发阈值，已动态截断至 {limit} 字符...")
        return text[:limit] + f"\n\n...[警告：由于 {model_name} 算力限制，尾部内容已安全截断]..."
    return text

def _call_specialist_agent(role_prompt, full_text, model_name, agent_name):
    """用于调用红/蓝军专家的内部并发函数"""
    print(f"[{agent_name}] 正在独立阅卷分析中...")
    safe_text = get_safe_text_for_model(full_text, model_name)
    
    messages = [
        {"role": "system", "content": role_prompt},
        {"role": "user", "content": f"以下是完整的财报或者经营分析、网络分析报告提取数据，请严格按照你的角色设定，指出具体问题（必须标明来源页码）：\n\n{safe_text}"}
    ]
    return call_api(messages, model_name=model_name, stream=True, silent_stream=True)

def generate_final_summary(full_text, user_req=""):
    """大脑引擎升级：Multi-Agent 红蓝对抗工作流"""
    print("\n🤖 [Multi-Agent 启动] 正在唤醒虚拟专家团队进行红蓝对抗...")
    
    user_directive_agent = ""
    user_directive_editor = ""
    if user_req and user_req.strip():
        print(f"🎯 接收到用户专属需求: {user_req.strip()}")
        user_directive_agent = f"\n\n【🌟 客户核心需求 (最高优先级)】：\n客户提出了具体的分析侧重点：“{user_req.strip()}”。你在寻找数据时，必须极其敏锐地捕捉与该需求相关的任何蛛丝马迹！"
        user_directive_editor = f"【🌟 客户核心需求 (最高优先级)】：\n客户提出了具体的分析侧重点：“{user_req.strip()}”。\n在输出报告时，你必须优先、重点回应这一需求。若原文件数据能支撑该需求，请作为报告的核心部分展开；若数据完全缺失，请在一开始明确告知客户。\n\n"
    
    blue_prompt = DOC_BLUE_AGENT + user_directive_agent
    red_prompt = DOC_RED_AGENT + user_directive_agent
    
    with ThreadPoolExecutor(max_workers=2) as executor:
        future_blue = executor.submit(_call_specialist_agent, blue_prompt, full_text, MODEL_BLUE, "🔵 蓝军风控官")
        future_red = executor.submit(_call_specialist_agent, red_prompt, full_text, MODEL_RED, "🔴 红军战略官")
        blue_report = future_blue.result()
        red_report = future_red.result()
        
    print("✅ 红蓝两军辩论完毕！正在交由 [👨‍⚖️ 首席主编] 融合并输出最终报告...")

    editor_safe_text = get_safe_text_for_model(full_text, MODEL_EDITOR)
    editor_messages = [
        {"role": "system", "content": DOC_EDITOR_SYSTEM},
        {"role": "user", "content": DOC_EDITOR_USER.format(
            editor_safe_text=editor_safe_text, 
            blue_report=blue_report, 
            red_report=red_report, 
            user_directive_editor=user_directive_editor
        )}
        ]
    
    final_summary = call_api(editor_messages, model_name=MODEL_EDITOR, stream=True)
    
    if "⚠️ 本次提取彻底失败" in final_summary:
        print(f"\n🚨 警告：主编模型 {MODEL_EDITOR} 调用失败！")
        return final_summary
        
    preserved_agent_reports = f"\n\n---\n## 🗂️ 专家组独立研判底稿 (Multi-Agent 视角)\n\n<details markdown=\"1\">\n<summary>🔵 点击展开【蓝军风控官】的原始挑刺报告</summary>\n\n{blue_report}\n\n</details>\n\n<details markdown=\"1\">\n<summary>🔴 点击展开【红军战略官】的原始增长报告</summary>\n\n{red_report}\n\n</details>\n"
    return final_summary + preserved_agent_reports