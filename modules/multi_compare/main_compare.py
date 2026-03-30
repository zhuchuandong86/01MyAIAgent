import os

# 【绝对导入】不再依赖原来的相对路径
from modules.multi_compare.api_client import call_api
from modules.multi_compare.main import get_safe_text_for_model
from core.prompts import COMPARE_EXTRACT, COMPARE_EDITOR_SYSTEM, COMPARE_EDITOR_USER

# 【直接读环境变量】彻底抛弃 config.py
MODEL_EDITOR = os.getenv("MODEL_EDITOR", "deepseek-v3-0324")
MODEL_TEXT = os.getenv("MODEL_TEXT", "deepseek-v3-0324")

def _extract_single_company(company_name, text):
    """Map阶段：独立提取单家公司的数据，防止幻觉混淆"""
    safe_text = get_safe_text_for_model(text, MODEL_TEXT)
    
    prompt = COMPARE_EXTRACT.format(company_name=company_name, safe_text=safe_text)

    messages = [{"role": "user", "content": prompt}]
    return call_api(messages, model_name=MODEL_TEXT, stream=False)


def generate_compare_summary(company_data_dict, status_ui=None):
    """Reduce阶段：多公司拉通对比"""
    msg = "\n🤖 [多模态竞品大脑] 启动！正在串行提取各家数据(防并发限流)..."
    print(msg)
    if status_ui: status_ui.write(msg)
    
    extracted_results = {}
    
    # 🌟【修复】：取消并发，改为串行排队 + UI 实时打印防焦虑
    for name, text in company_data_dict.items():
        # 保护我们注入的特洛伊木马指令不被当成公司去解析
        if name == "_STYLE_INSTRUCTION_":
            extracted_results[name] = text
            continue
            
        step_msg = f"⏳ 正在独立提纯【{name}】的底层财报数据..."
        print(step_msg)
        if status_ui: status_ui.write(step_msg)
        
        extracted_results[name] = _extract_single_company(name, text)
        
        done_msg = f"✅ 【{name}】数据提纯完毕！"
        print(done_msg)
        if status_ui: status_ui.write(done_msg)

    final_msg = "✍️ 各家数据就绪，首席竞品分析师正在输出深度横评..."
    print(final_msg)
    if status_ui: status_ui.write(final_msg)

    combined_context = ""
    for name, data in extracted_results.items():
        if name == "_STYLE_INSTRUCTION_":
            combined_context += f"\n\n{data}\n"
        else:
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