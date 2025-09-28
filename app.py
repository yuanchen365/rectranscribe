# app.py
import os
from flask import Flask, render_template, request, send_from_directory, flash, redirect
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from datetime import datetime

from modules.split_audio import split_audio
from modules.batch_job import run_batch_process

load_dotenv()
app = Flask(__name__)
app.secret_key = "supersecret"  # 用於 flash 訊息
app.config["UPLOAD_FOLDER"] = "uploads"
app.config["OUTPUT_FOLDER"] = "output/final"

# 確保必要目錄存在
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(app.config["OUTPUT_FOLDER"], exist_ok=True)

def read_file_text(filepath: str) -> str:
    """讀取指定路徑的文字檔案，若不存在則回傳提示文字"""
    return open(filepath, "r", encoding="utf-8").read() if os.path.exists(filepath) else "(檔案不存在)"

@app.route("/", methods=["GET", "POST"])
def index():
    report_filename = None
    transcript_text = ""
    review_text = ""
    revised_text = ""
    total_segments = 0  # 分段數

    if request.method == "POST":
        if "file" not in request.files:
            flash("請選擇檔案")
            return redirect(request.url)

        file = request.files["file"]
        if file.filename == "":
            flash("請選擇檔案")
            return redirect(request.url)

        # 🕒 建立唯一檔名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = secure_filename(file.filename or f"upload_{timestamp}.mp3")
        upload_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(upload_path)

        print(f"🎯 收到音檔：{filename}")

        try:
            # 🔪 Step 1: 切割音檔（5 分鐘為一段）
            split_audio(upload_path, output_dir="output/segments", chunk_length_sec=300)

            # 計算總分段數（以便頁面顯示）
            total_segments = len([
                f for f in os.listdir("output/segments")
                if f.lower().endswith(".wav")
            ])

            # 🔢 Step 2: 取得使用者輸入的分析段數（選填）
            max_segments_str = request.form.get("max_segments", "").strip()
            max_segments = int(max_segments_str) if max_segments_str.isdigit() else None

            # 🤖 Step 3: 執行整體分析流程（直接回傳 docx 檔案路徑）
            docx_path = run_batch_process(
                segments_dir="output/segments",
                max_segments=max_segments,
                preview=False,
                return_progress=False
            )

            # ✅ Step 4: 確認報告產出成功
            if docx_path and os.path.exists(docx_path):
                report_filename = os.path.basename(docx_path)
                flash(f"✅ 分析完成！下載報告：{report_filename}")

                transcript_text = read_file_text("output/final/transcript.txt")
                review_text = read_file_text("output/final/transcript_review.txt")
                revised_text = read_file_text("output/final/transcript_revised.txt")
            else:
                flash("⚠️ 分析失敗，請確認音檔格式或查看日誌")
                return redirect(request.url)

        except Exception as e:
            print(f"❌ 錯誤：{e}")
            flash("❌ 系統錯誤，請稍後再試")
            return redirect(request.url)

    return render_template(
        "index.html",
        report_link=report_filename,
        transcript_text=transcript_text,
        review_text=review_text,
        revised_text=revised_text,
        total_segments=total_segments
    )

@app.route("/download/<path:filename>")
def download(filename):
    return send_from_directory(app.config["OUTPUT_FOLDER"], filename, as_attachment=True)

if __name__ == "__main__":
    app.run(debug=True)
