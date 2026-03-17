import os
from concurrent.futures import ThreadPoolExecutor

# 【绝对导入】不再依赖原来的相对路径
from modules.multi_compare.api_client import call_api
from modules.multi_compare.main import get_safe_text_for_model
from core.prompts import COMPARE_EXTRACT, COMPARE_EDITOR_SYSTEM, COMPARE_EDITOR_USER

# 【直接读环境变量】彻底抛弃 config.py
MODEL_EDITOR = os.getenv("MODEL_EDITOR", "deepseek-v3-0324")
MODEL_TEXT = os.getenv("MODEL_TEXT", "deepseek-v3-0324")

def _extract_single_company(company_name, text):
    """Map阶段：独立提取单家公司的数据，防止幻觉混淆"""
    print(f"[{company_name}] 专属分析师正在提纯数据...")
    safe_text = get_safe_text_for_model(text, MODEL_TEXT)
    
    prompt = COMPARE_EXTRACT.format(company_name=company_name, safe_text=safe_text)

    messages = [{"role": "user", "content": prompt}]
    return call_api(messages, model_name=MODEL_TEXT, stream=False)


def generate_compare_summary(company_data_dict):
    """Reduce阶段：多公司拉通对比"""
    print("\n🤖 [多模态竞品大脑] 启动！正在并行提取各家数据...")
    
    extracted_results = {}
    with ThreadPoolExecutor(max_workers=len(company_data_dict)) as executor:
        future_to_company = {
            executor.submit(_extract_single_company, name, text): name 
            for name, text in company_data_dict.items()
        }
        for future in future_to_company:
            company_name = future_to_company[future]
            extracted_results[company_name] = future.result()

    print("✅ 各家数据提纯完毕！首席竞品分析师正在输出深度横评...")

    combined_context = ""
    for name, data in extracted_results.items():
        combined_context += f"\n\n{'='*20}\n【{name} 的核心数据提取】：\n{data}\n{'='*20}"

    # 👇 极简的数组构建
    editor_messages = [
        {
            "role": "system", 
            "content": COMPARE_EDITOR_SYSTEM
        },
        {
            "role": "user", 
            "content": COMPARE_EDITOR_USER.format(combined_context=combined_context)
        }
    ]
    
    final_summary = call_api(editor_messages, model_name=MODEL_EDITOR, stream=True)
    return final_summary