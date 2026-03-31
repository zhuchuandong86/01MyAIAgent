import os
import time

from modules.multi_compare.api_client import call_api
from modules.multi_compare.main import get_safe_text_for_model
from core.prompts import COMPARE_EXTRACT, COMPARE_EDITOR_SYSTEM, COMPARE_EDITOR_USER

MODEL_EDITOR = os.getenv("MODEL_EDITOR", "deepseek-v3-0324")
MODEL_TEXT = os.getenv("MODEL_TEXT", "qwen2.5-72b-instruct") # 建议用极速72B做提取

def _extract_single_company(company_name, text, user_req=""):
    """Map阶段：带上用户的‘有色眼镜’去提纯数据（🌟支持无限长文本的分块安全读取）"""
    # 1. 设定安全切块大小（10000字符，保证绝对不会触发内网 504 熔断）
    chunk_size = 10000 
    chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
    
    print(f"📦 【{company_name}】长文本共 {len(text)} 字符，已切割为 {len(chunks)} 个数据块进行安全穿透读取...")
    
    all_extracted_parts = []
    
    # 2. 循环阅读每一个数据块
    for idx, chunk in enumerate(chunks):
        print(f"   -> 🔍 正在扫描提纯第 {idx+1}/{len(chunks)} 块 (流式保活中)...")
        
        prompt = COMPARE_EXTRACT.format(company_name=company_name, safe_text=chunk)
        if user_req:
            prompt = f"【🌟 客户专属分析侧重点】：\n{user_req}\n\n请极度优先提取与上述侧重点相关的所有真实数据！\n\n" + prompt

        messages = [{"role": "user", "content": prompt}]
        # 发送小块请求，网关毫无压力，顺利秒回
        part_res = call_api(messages, model_name=MODEL_TEXT, stream=True, silent_stream=True)
        all_extracted_parts.append(part_res)
        time.sleep(1) # 给服务器1秒的喘息时间
        
    # 3. 把所有分块中提取到的精华数据拼装在一起，做到 100% 无遗漏！
    return "\n\n".join(all_extracted_parts)

def generate_compare_summary(company_data_dict, status_ui=None):
    """Reduce阶段：多公司升维对抗"""
    msg = "\n🤖 [多模态竞品大脑] 启动！正在串行穿透各家数据..."
    print(msg)
    if status_ui: status_ui.write(msg)
    
    extracted_results = {}
    
    # 🌟 核心修复：pop 出指令，不参与循环解析，保护上下文空间
    user_req = company_data_dict.pop("_USER_REQ_", "")
    style_instruction = company_data_dict.pop("_STYLE_INSTRUCTION_", "")
    
    # 串行提取，防 504 崩溃
    for name, text in company_data_dict.items():
        step_msg = f"⏳ 正在为【{name}】进行专属数据降噪提纯..."
        if status_ui: status_ui.write(step_msg)
        
        extracted_results[name] = _extract_single_company(name, text, user_req)
        
        if status_ui: status_ui.write(f"✅ 【{name}】数据就绪。")

    final_msg = "✍️ 正在进行‘非对称’对抗分析，首席主编出稿中..."
    if status_ui: status_ui.write(final_msg)

    combined_context = ""
    for name, data in extracted_results.items():
        combined_context += f"\n\n{'='*20}\n【{name} 核心提纯内容】：\n{data}\n{'='*20}"

    editor_messages = [
        {"role": "system", "content": COMPARE_EDITOR_SYSTEM},
        # 🌟 核心修复：把系统强制 XML 拼在总编指令最前方
        {"role": "user", "content": style_instruction + "\n\n" + COMPARE_EDITOR_USER.format(combined_context=combined_context)}
    ]
    
    return call_api(editor_messages, model_name=MODEL_EDITOR, stream=True)