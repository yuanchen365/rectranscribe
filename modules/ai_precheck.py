# modules/ai_precheck.py
"""
功能：
1. 檢查逐字稿 → 找出問題清單 / 初步修正建議 / 修正版全文
2. 回傳 review_text + revised_text 給 batch_job.py 使用
3. CLI 模式可直接測試預覽版分析
"""

import os
import sys
import json
from dotenv import load_dotenv
from openai import OpenAI
from typing import Tuple

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# 輸出資料夾
OUTPUT_DIR = "output/segments_text"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def ai_precheck(text: str, preview: bool = False) -> Tuple[str, str]:
    """
    呼叫 GPT 分析語意錯誤，回傳：
    - review_text: 問題清單 + 修正建議
    - revised_text: 修正版逐字稿
    """
    if not text:
        return "", ""

    clipped = text[:300] if preview else text

    prompt = f"""
我有一段會議錄音已經轉錄成文字，但因為包含許多產業和公司特有的專有名詞，
轉錄過程中出現了許多不精準或難以理解的地方。請依照以下方式協助我：

1. 檢查整段文字：找出可能語意不通、專有名詞錯誤或上下文不一致的地方。
2. 集中問答：將可疑或不合理的句子整理成「需要釐清的問題」，用簡單明確的問句提出。
3. 修正建議：提出更精準的修正文字建議。
4. 保留專業性與精準度。

請先輸出 JSON 格式，包含三個欄位：
- "problems": 問題清單（list，每個元素為一個問句）
- "suggestions": 初步修正建議（list，每個元素為一句建議）
- "revised_text": 修正版全文（string）

逐字稿如下：
{clipped}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        ai_output = response.choices[0].message.content or "{}"
        data = json.loads(ai_output)
    except Exception as e:
        print(f"❌ GPT 回傳錯誤：{e}")
        data = {"problems": [], "suggestions": [], "revised_text": ""}

    # 整理輸出
    review_text = (
        "⚠️ 問題清單\n" + "\n".join(data.get("problems", [])) +
        "\n\n✍️ 初步修正建議\n" + "\n".join(data.get("suggestions", []))
    )
    revised_text = data.get("revised_text", "")

    # 寫入檔案（供手動測試用，可被 batch_job 忽略）
    _save_text(os.path.join(OUTPUT_DIR, "transcript_review.txt"), review_text)
    _save_text(os.path.join(OUTPUT_DIR, "transcript_revised.txt"), revised_text)
    _save_json(os.path.join(OUTPUT_DIR, "transcript_ai_output.json"), data)

    return review_text, revised_text

def _save_text(path: str, content: str):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content or "")

def _save_json(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ✅ CLI 測試模式
def main():
    input_path = "output/final/transcript.txt"
    preview = "--preview" in sys.argv

    if not os.path.exists(input_path):
        print(f"❌ 找不到輸入檔：{input_path}")
        return

    with open(input_path, "r", encoding="utf-8") as f:
        text = f.read()

    print(f"🔍 開始 AI 預審處理（preview={preview}）")
    review_text, revised_text = ai_precheck(text, preview=preview)

    print("✅ 已產生下列檔案：")
    print("  - transcript_review.txt")
    print("  - transcript_revised.txt")
    print("  - transcript_ai_output.json")

if __name__ == "__main__":
    main()
