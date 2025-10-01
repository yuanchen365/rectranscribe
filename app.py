# app.py
import os
import time
import traceback
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from flask import (
    Flask, render_template, request, send_from_directory,
    flash, redirect, url_for, jsonify, session
)
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from modules.split_audio import split_audio
from modules.batch_job import run_batch_process

# ========= 基本設定 =========
load_dotenv()

APP_ROOT = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(APP_ROOT, "uploads")
FINAL_FOLDER = os.path.join(APP_ROOT, "output", "final")
SEGMENTS_ROOT = os.path.join(APP_ROOT, "output", "segments")  # 每次上傳建立子資料夾

ALLOWED_EXTENSIONS = {"mp3", "wav", "m4a"}          # 上傳白名單
MAX_UPLOAD_MB = 200
MAX_CONTENT_LENGTH = MAX_UPLOAD_MB * 1024 * 1024    # 200MB

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "supersecret")
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# 確保必要目錄存在
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(FINAL_FOLDER, exist_ok=True)
os.makedirs(SEGMENTS_ROOT, exist_ok=True)

# ========= 小工具 =========
def allowed_file(fname: str) -> bool:
    """檔名副檔名是否在白名單"""
    return "." in fname and fname.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def read_file_text(filepath: str) -> str:
    """讀文字檔，不存在則回提示"""
    return open(filepath, "r", encoding="utf-8").read() if os.path.exists(filepath) else "(檔案不存在)"

def log_exception(e: Exception) -> str:
    """把例外寫到 app.log，回傳錯誤代碼"""
    err_id = f"ERR-{int(time.time())}"
    log_path = os.path.join(APP_ROOT, "app.log")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[{err_id}] {repr(e)}\n{traceback.format_exc()}\n")
    return err_id

# ========= 健康檢查 =========
@app.get("/healthz")
def healthz():
    return jsonify(status="ok")

# ========= 首頁（依狀態顯示） =========
@app.route("/", methods=["GET"])
def index():
    """
    - Step 1: 上傳音檔
    - Step 2: 顯示切割後的分段數，輸入要分析的段數並按「開始分析」
    - 完成後：透過 ?report=xxx 讀 output/final 下的結果顯示（不把大文字放進 session）
    """
    step = session.get("step", 1)
    total_segments = session.get("total_segments", 0)

    report_filename = request.args.get("report") or session.get("report_filename")
    transcript_text = ""
    review_text = ""
    revised_text = ""

    if report_filename:
        # 只在頁面上需要時，從檔案系統讀內容（若不存在，read_file_text 會回提示字串）
        transcript_text = read_file_text(os.path.join(FINAL_FOLDER, "transcript.txt"))
        review_text     = read_file_text(os.path.join(FINAL_FOLDER, "transcript_review.txt"))
        revised_text    = read_file_text(os.path.join(FINAL_FOLDER, "transcript_revised.txt"))

    return render_template(
        "index.html",
        step=step,
        total_segments=total_segments,
        report_link=report_filename,
        transcript_text=transcript_text,
        review_text=review_text,
        revised_text=revised_text,
    )

# 提供一鍵清除流程狀態，回到 Step 1
@app.get("/reset")
def reset():
    try:
        _ = session.get("job_id")  # 若未來要做檔案清理可用到
        session.clear()
    except Exception:
        pass
    return redirect(url_for("index"))

# ========= Step 1：上傳 + 切割（不啟動分析） =========
@app.post("/upload")
def upload():
    try:
        file = request.files.get("file")
        if not isinstance(file, FileStorage):
            flash("請選擇音檔後再送出")
            return redirect(url_for("index"))

        raw_filename: str = file.filename or ""
        if raw_filename == "":
            flash("請選擇音檔後再送出")
            return redirect(url_for("index"))

        if not allowed_file(raw_filename):
            flash("只允許上傳 mp3 / wav / m4a")
            return redirect(url_for("index"))

        # 儲存原始上傳檔
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = secure_filename(raw_filename) or f"upload_{ts}.mp3"
        upload_path = os.path.join(UPLOAD_FOLDER, f"{ts}_{safe_name}")
        file.save(upload_path)
        print(f"🎯 收到音檔：{upload_path}")

        # 為本次處理建立獨立分段資料夾
        job_dir = os.path.join(SEGMENTS_ROOT, f"job_{ts}")
        os.makedirs(job_dir, exist_ok=True)

        # 切割（預設 5 分鐘一段）
        split_audio(upload_path, output_dir=job_dir, chunk_length_sec=300)

        # 計算本次分段數
        total_segments = len([f for f in os.listdir(job_dir) if f.lower().endswith(".wav")])

        # 將狀態寫進 session（都很小）：進入 Step 2
        session["step"] = 2
        session["job_dir"] = job_dir
        session["total_segments"] = total_segments

        flash(f"✅ 上傳完成，已切割為 {total_segments} 段。請輸入要分析的段數後，按「開始分析」。")
        return redirect(url_for("index"))

    except Exception as e:
        err_id = log_exception(e)
        print(f"❌ 上傳/切割錯誤：{e} ({err_id})")
        flash(f"❌ 系統錯誤（上傳/切割），代碼 {err_id}")
        return redirect(url_for("index"))

# ========= Step 2：執行分析（run_batch_process） =========
@app.post("/run")
def run():
    try:
        job_dir = session.get("job_dir")
        if not job_dir or not os.path.isdir(job_dir):
            flash("找不到切割資料夾，請重新上傳音檔。")
            session["step"] = 1
            return redirect(url_for("index"))

        # 取得使用者指定的段數
        max_segments_str = (request.form.get("max_segments") or "").strip()
        max_segments: Optional[int] = int(max_segments_str) if max_segments_str.isdigit() else None

        # 執行整體分析流程（輸出到 output/final）
        docx_path = run_batch_process(
            segments_dir=job_dir,
            max_segments=max_segments,
            preview=False,
            return_progress=False
        )

        # 清理 session 的工作狀態（避免殘留）
        session["step"] = 1
        session.pop("job_dir", None)
        session.pop("total_segments", None)

        if docx_path and os.path.exists(docx_path):
            report_filename = os.path.basename(docx_path)
            session["report_filename"] = report_filename  # 只存小字串
            flash(f"✅ 分析完成！點擊即可下載報告：{report_filename}")
            # 透過 ?report= 帶回首頁，首頁自行從檔案系統讀取文字內容
            return redirect(url_for("index", report=report_filename))
        else:
            flash("⚠️ 分析失敗，請確認音檔格式或查看日誌（app.log）")
            return redirect(url_for("index"))

    except Exception as e:
        err_id = log_exception(e)
        print(f"❌ 分析錯誤：{e} ({err_id})")
        flash(f"❌ 系統錯誤（分析），代碼 {err_id}")
        session["step"] = 1
        session.pop("job_dir", None)
        session.pop("total_segments", None)
        return redirect(url_for("index"))

# ========= 下載路由（從 output/final 提供） =========
@app.route("/download/<path:filename>")
def download(filename: str):
    return send_from_directory(FINAL_FOLDER, filename, as_attachment=True)

# ========= 本地開發用（正式環境用 gunicorn 啟動） =========
if __name__ == "__main__":
    app.run(debug=True)
