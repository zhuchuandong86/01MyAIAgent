import os
from pathlib import Path
import core.paths

# 🌟 精准锚定静态插件库 (只读区)
ANTHROPIC_SKILLS_DIR = Path(core.paths.ROOT_DIR) / "modules" / "skills"

def invoke_anthropic_skill(skill_name: str, task_requirement: str) -> str:
    """调用 Anthropic 特定领域的专家技能"""
    skill_path = ANTHROPIC_SKILLS_DIR / skill_name
    if not skill_path.exists():
        return f"❌ 找不到技能目录 [{skill_name}]"

    result_text = f"✅ 已成功激活 Anthropic 领域专家：{skill_name}\n"

    readme_path = skill_path / "SKILL.md"
    if not readme_path.exists():
        readme_path = skill_path / "README.md"

    if readme_path.exists():
        with open(readme_path, "r", encoding="utf-8") as f:
            result_text += f"\n--- 💡 专家指导手册 (Prompt) ---\n{f.read()[:4000]}\n"

    scripts_dir = skill_path / "scripts"
    if scripts_dir.exists():
        script_files = []
        for root, _, files in os.walk(scripts_dir):
            for file in files:
                if not file.startswith(".") and not file.endswith(".pyc"):
                    rel_path = os.path.relpath(os.path.join(root, file), scripts_dir)
                    script_files.append(rel_path)

        if script_files:
            result_text += f"\n--- 🛠️ 专家提供的可执行脚本 (位于 {scripts_dir}) ---\n"
            for sf in script_files:
                script_full_path = (scripts_dir / sf).as_posix()
                result_text += f"✔️ 可用脚本: `{script_full_path}`。\n(请使用 execute_bash 工具运行它！)\n"

    return result_text


# =========================================================
# 🚀 导出专用的 Schema 和 Dispatcher 供 __init__.py 组装
# =========================================================
ANTHROPIC_SCHEMA = []
ANTHROPIC_DISPATCHER = {}

if ANTHROPIC_SKILLS_DIR.exists():
    # 扫描 modules/skills 下的 20 个物理文件夹
    available_skills = [d.name for d in ANTHROPIC_SKILLS_DIR.iterdir() if d.is_dir() and not d.name.startswith(".")]

    if available_skills:
        ANTHROPIC_SCHEMA.append(
            {
                "type": "function",
                "function": {
                    "name": "invoke_anthropic_skill",
                    "description": "极其重要：调用 Anthropic 特定领域的专家技能库。获取核心提示词指导和可执行的脚本路径。拿到路径后，必须结合 execute_bash 去运行。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill_name": {
                                "type": "string",
                                "enum": available_skills, # 🔒 锁定20个选项，杜绝大模型偷懒
                                "description": "必须严格从选项中选择最对口的技能名称。"
                            },
                            "task_requirement": {
                                "type": "string",
                                "description": "详细描述你当前遇到的问题或需求。"
                            }
                        },
                        "required": ["skill_name", "task_requirement"]
                    }
                }
            }
        )
        ANTHROPIC_DISPATCHER["invoke_anthropic_skill"] = invoke_anthropic_skill