# modules/summary.py
"""
功能：
- 對單一段文字（逐字稿）執行 GPT 摘要
- 可被其他模組呼叫 summary_text(text)
- CLI 模式下可自動讀取指定目錄並批次摘要
"""

import os
import sys
import json
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# 預設資料夾
SEGMENT_DIR = "output/segments_text"
SUMMARY_DIR = "output/segments_summary"
os.makedirs(SUMMARY_DIR, exist_ok=True)

def summary_text(text: str, max_sentences: int = 3) -> str:
    """
    呼叫 GPT 對單段落文字摘要，限制句數。
    """
    if not text:
        return ""

    prompt = f"""
你是一個會議記錄摘要助手。請將以下逐字稿文字，摘要為不超過 {max_sentences} 句話：

{text}
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        content = response.choices[0].message.content or ""
        return content.strip()
    except Exception as e:
        print(f"❌ GPT 摘要錯誤：{e}")
        return ""

# ✅ CLI 批次摘要功能
def summarize_all_segments():
    files = [f for f in os.listdir(SEGMENT_DIR) if f.endswith("_revised.txt")]
    files.sort()

    for fname in files:
        seg_path = os.path.join(SEGMENT_DIR, fname)
        summary_path = os.path.join(SUMMARY_DIR, fname.replace("_revised.txt", "_summary.txt"))

        with open(seg_path, "r", encoding="utf-8") as f:
            text = f.read()

        print(f"🧠 處理 {fname} ...")
        result = summary_text(text)

        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(result)
        print(f"✅ 已儲存：{summary_path}")

def main():
    preview = "--preview" in sys.argv
    if preview:
        print("🧪 測試模式")
        test_text = "這是測試的逐字稿段落內容，請嘗試產出 2 句摘要。"
        print(summary_text(test_text, max_sentences=2))
    else:
        summarize_all_segments()

if __name__ == "__main__":
    main()
