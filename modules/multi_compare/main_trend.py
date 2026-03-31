import os
import time

from modules.multi_compare.api_client import call_api
from modules.multi_compare.main import get_safe_text_for_model
from core.prompts import TREND_EXTRACT, TREND_EDITOR_SYSTEM, TREND_EDITOR_USER

MODEL_EDITOR = os.getenv("MODEL_EDITOR", "deepseek-v3-0324")
MODEL_TEXT = os.getenv("MODEL_TEXT", "deepseek-v3-0324")

def _extract_single_year(year_label, text, user_req=""):
    """Map阶段：独立提取单年的核心数据（🌟支持无限长文本的分块安全读取）"""
    chunk_size = 10000 
    chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
    
    print(f"📦 【{year_label}】年长文本共 {len(text)} 字符，已切割为 {len(chunks)} 个数据块进行安全穿透读取...")
    
    all_extracted_parts = []
    
    for idx, chunk in enumerate(chunks):
        print(f"   -> 🔍 正在扫描提纯第 {idx+1}/{len(chunks)} 块 (流式保活中)...")
        
        prompt = TREND_EXTRACT.format(year_label=year_label, safe_text=chunk)
        if user_req:
            prompt = f"【🌟 客户专属推演侧重点】：\n{user_req}\n\n请极度优先提取与上述侧重点相关的所有真实数据！\n\n" + prompt

        messages = [{"role": "user", "content": prompt}]
        part_res = call_api(messages, model_name=MODEL_TEXT, stream=True, silent_stream=True)
        all_extracted_parts.append(part_res)
        time.sleep(1) 
        
    return "\n\n".join(all_extracted_parts)

def generate_trend_summary(yearly_data_dict, status_ui=None):
    """Reduce阶段：按时间轴进行历史连贯性推演"""
    msg = "\n🤖 [历史趋势大脑] 启动！正在串行梳理历年数据(防 504 熔断)..."
    print(msg)
    if status_ui: status_ui.write(msg)
    
    extracted_results = {}
    
    user_req = yearly_data_dict.pop("_USER_REQ_", "")
    style_instruction = yearly_data_dict.pop("_STYLE_INSTRUCTION_", "")
    
    for year, text in yearly_data_dict.items():
        step_msg = f"⏳ 正在独立清洗【{year}】年的历史数据 (流式保活中)..."
        print(step_msg)
        if status_ui: status_ui.write(step_msg)
        
        extracted_results[year] = _extract_single_year(year, text, user_req)
        
        done_msg = f"✅ 【{year}】年数据清洗完毕！"
        print(done_msg)
        if status_ui: status_ui.write(done_msg)
        time.sleep(2)

    final_msg = "✍️ 历年时间轴梳理完毕，资深分析师开始推演..."
    print(final_msg)
    if status_ui: status_ui.write(final_msg)

    sorted_years = sorted(extracted_results.keys())
    combined_context = ""
    for year in sorted_years:
        combined_context += f"\n\n{'='*20}\n【{year} 年度提取数据】：\n{extracted_results[year]}\n{'='*20}"

    editor_messages = [
        {"role": "system", "content": TREND_EDITOR_SYSTEM},
        {"role": "user", "content": style_instruction + "\n\n" + TREND_EDITOR_USER.format(combined_context=combined_context)}
    ]
    
    return call_api(editor_messages, model_name=MODEL_EDITOR, stream=True)