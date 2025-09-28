# modules/analyze.py
"""
功能：
1. 使用 GPT 對轉錄文字進行摘要 / 大綱 / 待辦事項分析
2. 提供 run_analysis(text, preview) 給 batch_job.py 呼叫
3. 支援 preview 模式（只分析前 500 字）
4. 可直接執行：python -m modules.analyze --preview
"""

import os
import sys
import json
from dotenv import load_dotenv
from openai import OpenAI
from docx import Document

# 載入 OpenAI 金鑰
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def ai_analyze(text: str) -> str:
    """呼叫 GPT 進行分析，回傳 JSON 字串"""
    prompt = f"""
你是一個會議紀錄分析助手。請依據以下逐字稿，輸出 JSON 格式，包含：
- "summary": 會議摘要（3~5 句話）
- "outline": 主要議題清單（list，每個元素是一個議題）
- "todos": 待辦事項清單（list，每個元素是一個待辦事項）

逐字稿如下：
{text}
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content or ""
    except Exception as e:
        print(f"❌ OpenAI 分析錯誤：{e}")
        return "{}"  # 回傳空 JSON 字串防止中斷

def parse_sections(ai_output: str):
    """解析 JSON，抽出摘要、大綱、待辦"""
    try:
        data = json.loads(ai_output)
    except json.JSONDecodeError:
        data = {}
    summary = data.get("summary", "")
    outline = data.get("outline", [])
    todos = data.get("todos", [])
    return summary, outline, todos

# ✅ 提供主流程 batch_job.py 呼叫
def run_analysis(text: str, preview: bool = False):
    """主函式，輸入文字後回傳：摘要、大綱、待辦清單"""
    if not text:
        raise ValueError("無效文字內容")

    clipped = text[:500] if preview else text
    ai_output = ai_analyze(clipped)

    if not ai_output:
        ai_output = "{}"

    return parse_sections(ai_output)

# 🔧 CLI 模式用的函式（非必要）
def save_docx(path: str, summary: str, outline: list, todos: list):
    doc = Document()
    doc.add_heading("會議摘要報告", level=0)

    doc.add_heading("摘要", level=1)
    doc.add_paragraph(summary if summary else "（無內容）")

    doc.add_heading("大綱", level=1)
    for item in outline or ["（無內容）"]:
        doc.add_paragraph(item, style="List Bullet")

    doc.add_heading("待辦事項", level=1)
    for item in todos or ["（無內容）"]:
        doc.add_paragraph(item, style="List Number")

    doc.save(path)

def main():
    # CLI 模式測試用
    input_path = "output/final/transcript_revised.txt"
    preview_mode = "--preview" in sys.argv

    if not os.path.exists(input_path):
        print(f"❌ 找不到輸入檔：{input_path}")
        return

    with open(input_path, "r", encoding="utf-8") as f:
        text = f.read()

    print(f"🤖 開始分析（preview={preview_mode}）")
    summary, outline, todos = run_analysis(text, preview=preview_mode)

    # 輸出結果
    result_txt = "【摘要】\n" + summary + "\n\n【大綱】\n" + "\n".join(outline) + "\n\n【待辦事項】\n" + "\n".join(todos)
    os.makedirs("output/final", exist_ok=True)

    with open("output/final/meeting_summary.txt", "w", encoding="utf-8") as f:
        f.write(result_txt)

    with open("output/final/meeting_summary.json", "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outline": outline, "todos": todos}, f, ensure_ascii=False, indent=2)

    save_docx("output/final/meeting_summary.docx", summary, outline, todos)

    print("✅ 已輸出分析結果至 output/final/")

if __name__ == "__main__":
    main()
