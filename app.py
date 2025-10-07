import os
import io
import zipfile
import shutil
import time
import traceback
from functools import wraps
from datetime import datetime
from typing import Optional, cast, Any
import secrets

from authlib.integrations.flask_client import OAuth
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv
from flask import (
    Flask, render_template, request, send_from_directory,
    flash, redirect, url_for, jsonify, session, send_file
)
from flask_login import (
    LoginManager, login_user, logout_user, current_user, login_required
)
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from modules.split_audio import split_audio
from modules.batch_job import run_batch_process
from modules.db import Database, get_database_url
from modules.models import create_all, ensure_user_columns, User, Job, Usage
from sqlalchemy import func

load_dotenv()

APP_ROOT = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(APP_ROOT, "uploads")
FINAL_FOLDER = os.path.join(APP_ROOT, "output", "final")
SEGMENTS_ROOT = os.path.join(APP_ROOT, "output", "segments")

ALLOWED_EXTENSIONS = {"mp3", "wav", "m4a"}
MAX_UPLOAD_MB = 200
MAX_CONTENT_LENGTH = MAX_UPLOAD_MB * 1024 * 1024

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "supersecret")
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Plan & quota configuration (Route A)
DEFAULT_PLAN = os.getenv("DEFAULT_PLAN", "free")
FREE_MONTHLY_QUOTA_SECONDS = int(os.getenv("FREE_MONTHLY_QUOTA_SECONDS", "1800"))

# ==== Database & Auth initialization ====
db = Database(get_database_url(APP_ROOT))
create_all(db.engine)
ensure_user_columns(db.engine)

login_manager = LoginManager(app)
login_manager.login_view = "login"  # type: ignore[assignment]

oauth = OAuth(app)

from authlib.integrations.flask_client.apps import FlaskOAuth2App as RemoteApp
_google_client_id = os.getenv("GOOGLE_CLIENT_ID")
_google_client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
_google_oauth: Optional[RemoteApp] = None
if _google_client_id and _google_client_secret:
    _google_oauth = cast(RemoteApp, oauth.register(
        name="google",
        client_id=_google_client_id,
        client_secret=_google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        access_token_url="https://oauth2.googleapis.com/token",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        api_base_url="https://www.googleapis.com/oauth2/v3/",
        client_kwargs={"scope": "openid email profile"},
        prompt="consent",
    ))


def google_oauth_enabled() -> bool:
    return _google_oauth is not None


@login_manager.user_loader
def load_user(user_id: str):
    try:
        with db.session_scope() as s:
            return s.get(User, int(user_id))
    except Exception:
        return None


@app.teardown_appcontext
def remove_session(exception=None):
    try:
        db.remove()
    except Exception:
        pass


def admin_required(view_func):
    @wraps(view_func)
    @login_required
    def wrapper(*args, **kwargs):
        if getattr(current_user, "role", "user") != "admin":
            flash("需要管理員權限才能檢視此頁面。")
            return redirect(url_for("index"))
        return view_func(*args, **kwargs)

    return wrapper


os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(FINAL_FOLDER, exist_ok=True)
os.makedirs(SEGMENTS_ROOT, exist_ok=True)


def allowed_file(fname: str) -> bool:
    return "." in fname and fname.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def read_file_text(filepath: str) -> str:
    return open(filepath, "r", encoding="utf-8").read() if os.path.exists(filepath) else "(file not found)"


def log_exception(e: Exception) -> str:
    err_id = f"ERR-{int(time.time())}"
    log_path = os.path.join(APP_ROOT, "app.log")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[{err_id}] {repr(e)}\n{traceback.format_exc()}\n")
    return err_id


def to_rel_final_path(abs_path: str) -> str:
    rel = os.path.relpath(abs_path, FINAL_FOLDER)
    return rel.replace("\\", "/")


def month_start() -> datetime:
    now = datetime.utcnow()
    return datetime(now.year, now.month, 1)


def get_monthly_usage_seconds(user_id: int) -> float:
    with db.session_scope() as s:
        total = (
            s.query(func.coalesce(func.sum(Usage.quantity), 0.0))
            .filter(Usage.user_id == user_id, Usage.action == "transcribe", Usage.created_at >= month_start())
            .scalar()
        )
        return float(total or 0.0)


def plan_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("login"))
        user_plan = getattr(current_user, "plan", None) or DEFAULT_PLAN
        if user_plan == "free":
            try:
                usage = get_monthly_usage_seconds(int(current_user.get_id()))
            except Exception:
                usage = 0.0
            if usage >= FREE_MONTHLY_QUOTA_SECONDS:
                flash("Free plan monthly quota reached. Please upgrade.")
                return redirect(url_for("billing"))
        return view_func(*args, **kwargs)

    return wrapper

def get_user_dirs(user_id: int):
    user_upload = os.path.join(UPLOAD_FOLDER, f"user_{user_id}")
    user_segments = os.path.join(SEGMENTS_ROOT, f"user_{user_id}")
    user_final = os.path.join(FINAL_FOLDER, f"user_{user_id}")
    os.makedirs(user_upload, exist_ok=True)
    os.makedirs(user_segments, exist_ok=True)
    os.makedirs(user_final, exist_ok=True)
    return user_upload, user_segments, user_final


@app.get("/healthz")
def healthz():
    return jsonify(status="ok")


@app.route("/", methods=["GET"])
def index():
    step = session.get("step", 1)
    total_segments = session.get("total_segments", 0)

    if not current_user.is_authenticated:
        step = 1
        total_segments = 0
        for key in ("step", "job_dir", "total_segments", "upload_path", "src_filename", "report_relpath"):
            session.pop(key, None)

    report_relpath = request.args.get("report") or session.get("report_relpath")
    transcript_text = review_text = revised_text = ""

    if report_relpath:
        is_owner = False
        if current_user.is_authenticated:
            expected_prefix = f"user_{current_user.get_id()}/"
            if report_relpath.startswith(expected_prefix):
                is_owner = True

        if is_owner:
            final_dir = os.path.dirname(os.path.join(FINAL_FOLDER, report_relpath))
            transcript_text = read_file_text(os.path.join(final_dir, "transcript.txt"))
            review_text = read_file_text(os.path.join(final_dir, "transcript_review.txt"))
            revised_text = read_file_text(os.path.join(final_dir, "transcript_revised.txt"))
        else:
            report_relpath = None
            session.pop("report_relpath", None)
            transcript_text = review_text = revised_text = ""

    # Usage summary for UI display
    monthly_usage_seconds = None
    monthly_quota_seconds = None
    if current_user.is_authenticated:
        try:
            monthly_usage_seconds = get_monthly_usage_seconds(int(current_user.get_id()))
            monthly_quota_seconds = FREE_MONTHLY_QUOTA_SECONDS if getattr(current_user, "plan", DEFAULT_PLAN) == "free" else None
        except Exception:
            monthly_usage_seconds = None
            monthly_quota_seconds = None

    return render_template(
        "index.html",
        step=step,
        total_segments=total_segments,
        report_link=report_relpath,
        transcript_text=transcript_text,
        review_text=review_text,
        revised_text=revised_text,
        google_enabled=google_oauth_enabled(),
        monthly_usage_seconds=monthly_usage_seconds,
        monthly_quota_seconds=monthly_quota_seconds,
    )


@app.get("/reset")
@login_required
def reset():
    try:
        session.clear()
    except Exception:
        pass
    return redirect(url_for("index"))


@app.post("/upload")
@login_required
@plan_required
def upload():
    try:
        file = request.files.get("file")
        if not isinstance(file, FileStorage):
            flash("請先選擇音檔再送出。")
            return redirect(url_for("index"))

        raw_filename: str = file.filename or ""
        if raw_filename == "":
            flash("請先選擇音檔再送出。")
            return redirect(url_for("index"))

        if not allowed_file(raw_filename):
            flash("僅允許 mp3 / wav / m4a 檔案。")
            return redirect(url_for("index"))

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = secure_filename(raw_filename) or f"upload_{ts}.mp3"
        user_id = int(current_user.get_id())
        user_upload_dir, user_segments_root, _ = get_user_dirs(user_id)
        upload_path = os.path.join(user_upload_dir, f"{ts}_{safe_name}")
        file.save(upload_path)

        job_dir = os.path.join(user_segments_root, f"job_{ts}")
        os.makedirs(job_dir, exist_ok=True)

        split_audio(upload_path, output_dir=job_dir, chunk_length_sec=300)

        total_segments = len([f for f in os.listdir(job_dir) if f.lower().endswith(".wav")])

        session["step"] = 2
        session["job_dir"] = job_dir
        session["total_segments"] = total_segments
        session["upload_path"] = upload_path
        session["src_filename"] = raw_filename

        flash(f"已完成上傳，並切割為 {total_segments} 段。請輸入要處理的段數後繼續。")
        return redirect(url_for("index"))

    except Exception as e:
        err_id = log_exception(e)
        flash(f"上傳或切割時發生錯誤，代碼 {err_id}。")
        return redirect(url_for("index"))


@app.get("/upload")
@login_required
def upload_get_redirect():
    # 以 GET 直接開 /upload 時，導回首頁顯示上傳表單
    return redirect(url_for("index"))


@app.post("/run")
@login_required
@plan_required
def run():
    try:
        job_dir = session.get("job_dir")
        if not job_dir or not os.path.isdir(job_dir):
            flash("找不到工作資料夾，請重新上傳音檔。")
            session["step"] = 1
            return redirect(url_for("index"))

        max_segments_str = (request.form.get("max_segments") or "").strip()
        max_segments: Optional[int] = int(max_segments_str) if max_segments_str.isdigit() else None
        user_id = int(current_user.get_id())

        with db.session_scope() as s:
            job = Job(
                user_id=user_id,
                status="running",
                src_filename=session.get("src_filename"),
                segments=session.get("total_segments"),
                started_at=datetime.utcnow(),
            )
            s.add(job)
            s.flush()
            job_id_for_session = job.id

        docx_path = run_batch_process(
            segments_dir=job_dir,
            max_segments=max_segments,
            preview=False,
            return_progress=False,
        )

        if docx_path and os.path.exists(docx_path):
            final_dir = os.path.dirname(docx_path)
            _, _, user_final_root = get_user_dirs(user_id)
            target_dir = os.path.join(user_final_root, os.path.basename(final_dir))
            if os.path.abspath(os.path.dirname(final_dir)) != os.path.abspath(user_final_root):
                if os.path.exists(target_dir):
                    shutil.rmtree(target_dir)
                shutil.move(final_dir, target_dir)
            docx_path = os.path.join(target_dir, os.path.basename(docx_path))

        try:
            with db.session_scope() as s:
                job = s.get(Job, job_id_for_session)
                if job:
                    if docx_path and os.path.exists(docx_path):
                        job.status = "succeeded"
                        job.finished_at = datetime.utcnow()
                        job.output_dir_rel = os.path.dirname(to_rel_final_path(docx_path)).replace("\\", "/")
                    else:
                        job.status = "failed"
                        job.finished_at = datetime.utcnow()
        except Exception:
            pass

        # Record usage on success
        if docx_path and os.path.exists(docx_path):
            try:
                total_segments = int(session.get("total_segments") or 0)
                processed_segments = total_segments
                ms = request.form.get("max_segments")
                if ms and ms.isdigit():
                    processed_segments = min(int(ms), total_segments) if total_segments > 0 else int(ms)
                seconds = float(max(processed_segments, 0) * 300)
                with db.session_scope() as s:
                    s.add(Usage(user_id=user_id, action="transcribe", quantity=seconds, meta=f"job_id={job_id_for_session};segments={processed_segments}"))
            except Exception:
                pass

        session["step"] = 1
        session.pop("job_dir", None)
        session.pop("total_segments", None)
        session.pop("upload_path", None)
        session.pop("src_filename", None)

        if docx_path and os.path.exists(docx_path):
            report_relpath = to_rel_final_path(docx_path)
            session["report_relpath"] = report_relpath
            flash(f"處理完成！已可下載 {os.path.basename(docx_path)}。")
            return redirect(url_for("index", report=report_relpath))
        else:
            flash("處理失敗，請檢查 app.log。")
            return redirect(url_for("index"))

    except Exception as e:
        err_id = log_exception(e)
        flash(f"處理流程發生錯誤，代碼 {err_id}。")
        session["step"] = 1
        session.pop("job_dir", None)
        session.pop("total_segments", None)
        session.pop("upload_path", None)
        session.pop("src_filename", None)
        return redirect(url_for("index"))


@app.route("/download/<path:filename>")
@login_required
@plan_required
def download(filename: str):
    safe_rel = filename.replace("\\", "/")
    expected_prefix = f"user_{current_user.get_id()}/"
    if not safe_rel.startswith(expected_prefix):
        flash("您沒有權限下載此檔案。")
        return redirect(url_for("index"))
    return send_from_directory(FINAL_FOLDER, safe_rel, as_attachment=True)


@app.route("/download_zip/<path:report>")
@login_required
@plan_required
def download_zip(report: str):
    try:
        safe_rel = report.replace("\\", "/")
        expected_prefix = f"user_{current_user.get_id()}/"
        if not safe_rel.startswith(expected_prefix):
            flash("您沒有權限下載此資料夾。")
            return redirect(url_for("index"))

        final_dir = os.path.dirname(os.path.join(FINAL_FOLDER, safe_rel))
        if not os.path.isdir(final_dir):
            flash("找不到輸出的資料夾。")
            return redirect(url_for("index"))

        mem_file = io.BytesIO()
        with zipfile.ZipFile(mem_file, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(final_dir):
                for fname in files:
                    abs_path = os.path.join(root, fname)
                    rel_path = os.path.relpath(abs_path, final_dir)
                    zf.write(abs_path, arcname=rel_path)
        mem_file.seek(0)

        zip_name = f"{os.path.basename(final_dir)}.zip"
        return send_file(mem_file, mimetype="application/zip", as_attachment=True, download_name=zip_name)
    except Exception as e:
        err_id = log_exception(e)
        flash(f"打包 ZIP 失敗，代碼 {err_id}。")
        return redirect(url_for("index"))


@app.get("/try_demo")
@login_required
@plan_required
def try_demo():
    try:
        demo_path = os.path.join(APP_ROOT, "demo.mp3")
        if not os.path.exists(demo_path):
            flash("找不到範例檔 demo.mp3。")
            return redirect(url_for("index"))

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        upload_name = f"{ts}_demo.mp3"
        user_id = int(current_user.get_id())
        user_upload_dir, user_segments_root, _ = get_user_dirs(user_id)
        upload_path = os.path.join(user_upload_dir, upload_name)
        shutil.copyfile(demo_path, upload_path)

        job_dir = os.path.join(user_segments_root, f"job_{ts}")
        os.makedirs(job_dir, exist_ok=True)

        split_audio(upload_path, output_dir=job_dir, chunk_length_sec=300)

        total_segments = len([f for f in os.listdir(job_dir) if f.lower().endswith(".wav")])

        session["step"] = 2
        session["job_dir"] = job_dir
        session["total_segments"] = total_segments
        session["upload_path"] = upload_path
        session["src_filename"] = upload_name

        flash(f"已載入範例檔，並切割為 {total_segments} 段。")
        return redirect(url_for("index"))
    except Exception as e:
        err_id = log_exception(e)
        flash(f"範例檔處理失敗，代碼 {err_id}。")
        return redirect(url_for("index"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET" and current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        password2 = request.form.get("password2") or ""
        if not email or not password:
            flash("請輸入 Email 與密碼。")
            return redirect(url_for("register"))
        if password != password2:
            flash("兩次輸入的密碼不一致。")
            return redirect(url_for("register"))
        with db.session_scope() as s:
            exists = s.query(User).filter(User.email == email).first()
            if exists:
                flash("Email 已被註冊。")
                return redirect(url_for("register"))
            u = User(email=email, email_verified=False)
            u.set_password(password)
            s.add(u)
            s.flush()
            login_user(u)
        flash("註冊完成，已自動登入。")
        return redirect(url_for("index"))
    return render_template("register.html", google_enabled=google_oauth_enabled())


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET" and current_user.is_authenticated:
        next_url = request.args.get("next")
        return redirect(next_url or url_for("index"))
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        with db.session_scope() as s:
            user = s.query(User).filter(User.email == email).first()
            if not user or not user.check_password(password):
                flash("Email 或密碼不正確。")
                return redirect(url_for("login"))
            user.last_login_at = datetime.utcnow()
            login_user(user)
        flash("登入成功。")
        return redirect(url_for("index"))
    return render_template("login.html", google_enabled=google_oauth_enabled())


@app.get("/logout")
def logout():
    if current_user.is_authenticated:
        logout_user()
        flash("已登出。")
    for key in ("step", "job_dir", "total_segments", "upload_path", "src_filename", "report_relpath"):
        session.pop(key, None)
    return redirect(url_for("login"))


@app.get("/jobs")
@login_required
@plan_required
def jobs_page():
    with db.session_scope() as s:
        user_id = int(current_user.get_id())
        jobs = s.query(Job).filter(Job.user_id == user_id).order_by(Job.created_at.desc()).all()
    return render_template("jobs.html", jobs=jobs)


@app.get("/admin/users")
@admin_required
def admin_users():
    with db.session_scope() as s:
        records = []
        users = s.query(User).order_by(User.created_at.desc()).all()
        for user in users:
            job_count = s.query(Job).filter(Job.user_id == user.id).count()
            records.append({
                "id": user.id,
                "email": user.email,
                "display_name": user.display_name,
                "role": user.role,
                "created_at": user.created_at,
                "google_sub": user.google_sub,
                "job_count": job_count,
            })
    return render_template("admin_users.html", users=records)


@app.get("/auth/google")
def auth_google():
    if not google_oauth_enabled():
        flash("目前尚未啟用 Google 登入。")
        return redirect(url_for("login"))
    redirect_uri = url_for("auth_google_callback", _external=True)
    google = cast(RemoteApp, _google_oauth)
    nonce = secrets.token_urlsafe(16)
    session["oauth_nonce"] = nonce
    next_url = request.args.get("next")
    if isinstance(next_url, str) and next_url.startswith("/"):
        session["login_next"] = next_url
    else:
        # 嘗試從 Referer 的 query string 抓取 next
        ref = request.headers.get("Referer")
        if ref:
            try:
                qs = parse_qs(urlparse(ref).query)
                ref_next = qs.get("next", [None])[0]
                if isinstance(ref_next, str) and ref_next.startswith("/"):
                    session["login_next"] = ref_next
            except Exception:
                pass
    return google.authorize_redirect(redirect_uri, nonce=nonce)


@app.get("/auth/google/callback")
def auth_google_callback():
    if not google_oauth_enabled():
        flash("目前尚未啟用 Google 登入。")
        return redirect(url_for("login"))
    try:
        google = cast(RemoteApp, _google_oauth)
        token = google.authorize_access_token()
        nonce = cast(str, session.pop("oauth_nonce", ""))
        userinfo = google.parse_id_token(token, nonce=nonce)
    except Exception as e:
        err_id = log_exception(e)
        flash(f"Google 登入失敗，代碼 {err_id}。")
        return redirect(url_for("login"))

    if not userinfo or not userinfo.get("sub"):
        flash("未取得 Google 帳號資訊。")
        return redirect(url_for("login"))

    sub = userinfo.get("sub")
    email_val = userinfo.get("email")
    email = email_val.lower() if isinstance(email_val, str) else None
    name = userinfo.get("name")
    picture = userinfo.get("picture")

    with db.session_scope() as s:
        user = s.query(User).filter(User.google_sub == sub).first()
        if not user and email:
            user = s.query(User).filter(User.email == email).first()
        if not user:
            user = User(
                email=email or f"google_{sub}@example.com",
                google_sub=sub,
                display_name=name,
                avatar_url=picture,
                email_verified=True,
                role="user",
                password_hash="",
            )
            s.add(user)
        else:
            if not user.google_sub:
                user.google_sub = sub
            if email and not user.email:
                user.email = email
            if name and user.display_name != name:
                user.display_name = name
            if picture and user.avatar_url != picture:
                user.avatar_url = picture
            user.email_verified = True
        user.last_login_at = datetime.utcnow()
        s.flush()
        login_user(user)
        # 若有先前欲導向頁面，優先返回該頁
        next_url = session.pop("login_next", None)
        if isinstance(next_url, str) and next_url.startswith("/"):
            flash("�w�ϥ� Google �b���n�J�C")
            return redirect(next_url)
    flash("已使用 Google 帳號登入。")
    return redirect(url_for("index"))


@app.get("/billing")
@login_required
def billing():
    user_id = int(current_user.get_id())
    try:
        usage = get_monthly_usage_seconds(user_id)
    except Exception:
        usage = 0.0
    quota = FREE_MONTHLY_QUOTA_SECONDS if getattr(current_user, "plan", DEFAULT_PLAN) == "free" else None
    return render_template("billing.html", usage_seconds=usage, quota_seconds=quota)

if __name__ == "__main__":
    app.run(debug=True)





