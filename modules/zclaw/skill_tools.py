import os
import streamlit as st
import core.paths

def get_user_skills_dir():
    user = st.session_state.get("zclaw_user", "public")
    ws_path = os.path.join(str(core.paths.GLOBAL_DATA_DIR), f"zclaw_workspace_{user}")
    skills_path = os.path.join(ws_path, "skills")
    os.makedirs(skills_path, exist_ok=True)
    return skills_path

def list_skills() -> str:
    skills_dir = get_user_skills_dir()
    skills = [f"📦 `skills.{f[:-3]}`" for f in os.listdir(skills_dir) if f.endswith(".py") and not f.startswith("__")]
    if not skills: return "当前沙箱未沉淀任何技能。"
    return "已沉淀技能:\n" + "\n".join(skills)

def scan_skills() -> str:
    return list_skills()

SCHEMA = [
    {
        "name": "list_skills",
        "description": "列出沙箱内已经写好的 Python 技能脚本以供复用。",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    }
]