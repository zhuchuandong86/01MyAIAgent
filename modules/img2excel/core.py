# modules/img2excel/core.py
import base64
import pandas as pd
from openai import OpenAI
import concurrent.futures
import time
from PIL import Image
import io
from core.token_tracker import log_usage

# from dotenv import load_dotenv
# load_dotenv()
# INTERNAL_URL=os.getenv("INTERNAL_URL")
# os.environ['NO_PROXY'] = INTERNAL_URL


PROMPT_TEXT = """
# 角色定义
你是一个高精度的文档数字处理专家，擅长从复杂的拍照图像中提取结构化表格数据。

# 核心任务
将提供的图片中的核心数据表格提取出来，并转换为标准的 Markdown 表格。

# 约束与具体指令
1. ### 忽略背景与干扰 ###
   - 忽略纸张以外的桌面、纹理或背景。
2. ### 适度读取行标和列标 ###
   - 如图片中有 Excel 界面自带的最顶端列标(A, B...)和最左侧行号(1, 2...)，请将其分别作为 Markdown 表格的“表头”和“第一列”。如果没有，则只提取内部实际数据。
3. ### 应对畸变与模糊 ###
   - 图片存在拍照畸变，请按行列逻辑对齐数据。对于模糊不清的单元格，填入 `[模糊]`。
4. ### 完整性要求（绝对禁止省略） ###
   - 你必须从图片表格的第一行数据开始，逐行提取直到最后一行！
   - 绝对不允许“偷懒”，绝对不允许使用“...”、省略号或“等”字样来跳过中间或尾部的数据。
   - **必须原原本本地输出每一个单元格，不要因为重复空值就停止！**
5. ### 严格输出格式 ###
   - 必须且仅输出标准的 Markdown 表格文本，不要有任何多余的解释文字或代码块符号。
"""

REVIEWER_PROMPT = """
# 角色定义
你是一个高精度的数据核对专家与文档处理大师。

# 背景
我们使用了多个AI视觉模型对同一张图片进行了表格数据提取，以下是它们各自的提取结果：
{extracted_results}

# 核心任务
请你结合原图，仔细对比上述不同模型的提取结果，找出并修正其中的错漏、对齐问题或省略的部分，整合出一份最准确、最完整的最终数据表格。

# 严格约束
1. 必须原原本本地输出每一个单元格，应对畸变与模糊。绝对不允许省略数据。
2. 必须且仅输出标准的 Markdown 表格文本，不要有任何多余的解释文字或代码块符号。
"""

def _call_vision_model(client: OpenAI, image_base64: str, model_name: str, prompt_text: str, max_retries: int = 3) -> str:
    """底层的单次模型调用函数（包含失败自动重试机制）"""
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt_text},
                        # 👇 确保 image_url 后面只跟了一个包含 url 和 detail 的单层字典
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                    ]
                }],
                temperature=0.1, 
                max_tokens=4096
            )

            content = response.choices[0].message.content
            
            # 👇【新增计费拦截】：从 response 中抓取官方返回的 token 消耗
            # 如果接口没返回 usage，采用强行估算 (按返回文字长度预估)
            if hasattr(response, 'usage') and response.usage:
                tokens = response.usage.total_tokens
            else:
                tokens = int(len(content) * 1.2 + 1000) # 预估输入图片的token+输出文字
                
            log_usage("图片转Excel", model_name, tokens)
            # 👆【新增结束】
            
            return content
        except Exception as e:
            last_exception = e
            print(f"[警告] 模型 {model_name} 第 {attempt + 1} 次调用失败: {e}")
            if attempt < max_retries - 1:
                time.sleep(2)  # 失败后等待2秒再进行下一次重试
                
    # 重试耗尽，抛出异常
    raise Exception(f"模型 {model_name} 连续 {max_retries} 次请求失败: {last_exception}")

def parse_markdown_to_df(md_text: str) -> pd.DataFrame:
    """将 Markdown 解析为 DataFrame (带过程打印与严格过滤)"""
    print("\n" + "="*50)
    print("🔍 [DEBUG] 开始解析大模型返回的 Markdown")
    print("="*50)
    
    if not md_text:
        raise Exception("模型返回结果为空")
        
    # 打印原始文本的总长度
    print(f"📄 [原始文本总长度]: {len(md_text)} 字符")
        
    # 1. 严格提取只包含 '|' 的行
    lines = [line.strip() for line in md_text.strip().split('\n')]
    table_lines = [line for line in lines if '|' in line]
    
    print(f"✂️  [初步过滤]: 找到 {len(table_lines)} 行包含 '|' 的文本。")
    
    # 2. 深度过滤：干掉分割线和模型脑补的“假空行”
    data_lines = []
    for line in table_lines:
        # 去掉 |、-、: 和所有空格后，如果啥也不剩，说明它是纯分割线或全空的无效行！
        cleaned = line.replace('|', '').replace('-', '').replace(':', '').strip()
        if cleaned: 
            data_lines.append(line)
            
    print(f"🧹 [深度清洗]: 剔除表头分割线和全空行后，剩余 {len(data_lines)} 行有效数据。")
    
    if not data_lines:
        raise Exception("提取到了表格边框，但没有实质内容数据。")
        
    # 3. 分割单元格并清理首尾的 '|'
    table_data = []
    for line in data_lines:
        if line.startswith('|'): line = line[1:]
        if line.endswith('|'): line = line[:-1]
        row = [cell.strip() for cell in line.split('|')]
        table_data.append(row)
        
    if len(table_data) <= 1:
        print("⚠️ [警告]: 只提取到了 1 行数据，可能是纯表头。")
        return pd.DataFrame([table_data[0]] if table_data else [])
        
    # 4. 强制对齐列数
    max_cols = max(len(row) for row in table_data) 
    print(f"📏 [列数对齐]: 检测到最大列数为 {max_cols} 列。")
    
    header = table_data[0]
    
    if len(header) < max_cols:
        header.extend([f"未命名列_{i}" for i in range(len(header), max_cols)])
    elif len(header) > max_cols:
        header = header[:max_cols]
        
    normalized_data = []
    # 打印部分数据行，看看最后莫名其妙的到底是什么内容
    print("📊 [数据行抽样预览]:")
    total_data_rows = len(table_data[1:])
    
    for i, row in enumerate(table_data[1:]):
        # 打印前2行和最后3行，中间折叠，方便排查末尾垃圾数据
        if i < 2 or i >= total_data_rows - 3:
            print(f"   -> 第 {i+1} 行: {row}")
        elif i == 2:
            print("   -> ...... (中间数据省略) ......")

        if len(row) < max_cols:
            row.extend([''] * (max_cols - len(row)))
        elif len(row) > max_cols:
            row = row[:max_cols]
        normalized_data.append(row)
        
    print("✅ [解析成功]: DataFrame 构建完成！")
    print("="*50 + "\n")
    
    return pd.DataFrame(normalized_data, columns=header)

def process_image_to_df(image_bytes: bytes, api_key: str, api_base: str, extract_models: list, reviewer_model: str = None) -> tuple:
    # --- 新增图片压缩逻辑 ---
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode != 'RGB':
        img = img.convert('RGB')
    img.thumbnail((1024, 1024)) # 限制最大分辨率为 1024x1024
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=80) # 压缩质量
    compressed_bytes = buffer.getvalue()
    
    # 用压缩后的 bytes 转 Base64
    base64_img = base64.b64encode(compressed_bytes).decode('utf-8')
    client = OpenAI(api_key=api_key, base_url=api_base)
    
    # 1. 配置中只有一个提取模型时（最省流模式）
    if len(extract_models) == 1 and not reviewer_model:
        md_text = _call_vision_model(client, base64_img, extract_models[0], PROMPT_TEXT)
    
    # 2. 多模型并发提取 + 智能校验/降级机制
    else:
        results = []
        successful_models = []
        last_success_res = ""
        
        # 并发请求所有的提取模型
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future_to_model = {
                executor.submit(_call_vision_model, client, base64_img, model, PROMPT_TEXT): model 
                for model in extract_models
            }
            for future in concurrent.futures.as_completed(future_to_model):
                model_name = future_to_model[future]
                try:
                    res = future.result()
                    results.append(f"### 提取结果 (来自模型 {model_name}) ###\n{res}\n")
                    successful_models.append(model_name)
                    last_success_res = res  # 暂存最后一个成功的纯净结果
                except Exception as e:
                    print(f"[错误] 模型 {model_name} 彻底提取失败已被跳过: {e}")
        
        # 结果判定与流转
        if len(successful_models) == 0:
            raise Exception("所有前置提取模型均由于网络或服务原因调用失败。")
            
        elif len(successful_models) == 1:
            # 只有1个模型成功，无需启动审阅模型，直接输出，并附加提示
            warning_msg = f"\n\n> ⚠️ **系统提示**：原定多模型并发校验，但目前仅有 `{successful_models[0]}` 模型成功返回数据（其他模型可能因网络或限流失败）。已自动为您降级输出该单模型结果。"
            md_text = last_success_res + warning_msg
            
        else:
            # 有多个模型成功，提交给审阅模型进行合并与纠错
            combined_text = "\n".join(results)
            final_prompt = REVIEWER_PROMPT.format(extracted_results=combined_text)
            final_model = reviewer_model if reviewer_model else successful_models[0]
            md_text = _call_vision_model(client, base64_img, final_model, final_prompt)

    # 3. 将最终的 Markdown 解析为 DataFrame
    df = parse_markdown_to_df(md_text)
        
    return df, md_text