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
    return "." in fname and fname.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def read_file_text(filepath: str) -> str:
    return open(filepath, "r", encoding="utf-8").read() if os.path.exists(filepath) else "(檔案不存在)"

def log_exception(e: Exception) -> str:
    err_id = f"ERR-{int(time.time())}"
    log_path = os.path.join(APP_ROOT, "app.log")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[{err_id}] {repr(e)}\n{traceback.format_exc()}\n")
    return err_id

def to_rel_final_path(abs_path: str) -> str:
    """把 FINAL_FOLDER 底下的絕對路徑轉成相對路徑，並統一使用 / 分隔"""
    rel = os.path.relpath(abs_path, FINAL_FOLDER)
    return rel.replace("\\", "/")

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
    - 完成後：透過 ?report=<相對路徑> 顯示結果與下載
    """
    step = session.get("step", 1)
    total_segments = session.get("total_segments", 0)

    # report 是相對於 FINAL_FOLDER 的路徑，例如：job_20251001_153743/meeting_summary.docx
    report_relpath = request.args.get("report") or session.get("report_relpath")
    transcript_text = review_text = revised_text = ""

    if report_relpath:
        final_dir = os.path.dirname(os.path.join(FINAL_FOLDER, report_relpath))
        transcript_text = read_file_text(os.path.join(final_dir, "transcript.txt"))
        review_text     = read_file_text(os.path.join(final_dir, "transcript_review.txt"))
        revised_text    = read_file_text(os.path.join(final_dir, "transcript_revised.txt"))

    return render_template(
        "index.html",
        step=step,
        total_segments=total_segments,
        report_link=report_relpath,   # 直接帶相對路徑給下載用
        transcript_text=transcript_text,
        review_text=review_text,
        revised_text=revised_text,
    )

# 提供一鍵清除流程狀態，回到 Step 1
@app.get("/reset")
def reset():
    try:
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

        # 將狀態寫進 session：進入 Step 2
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

        # 執行整體分析流程：預期會產生 output/final/job_xxx/meeting_summary.docx
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
            report_relpath = to_rel_final_path(docx_path)  # e.g., job_.../meeting_summary.docx
            session["report_relpath"] = report_relpath
            flash(f"✅ 分析完成！點擊即可下載報告：{os.path.basename(docx_path)}")
            return redirect(url_for("index", report=report_relpath))
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

# ========= 下載路由（從 output/final 提供，相對路徑允許子資料夾） =========
@app.route("/download/<path:filename>")
def download(filename: str):
    # filename 是相對於 FINAL_FOLDER 的路徑
    safe_rel = filename.replace("\\", "/")
    return send_from_directory(FINAL_FOLDER, safe_rel, as_attachment=True)

# ========= 本地開發用（正式環境用 gunicorn 啟動） =========
if __name__ == "__main__":
    app.run(debug=True)
