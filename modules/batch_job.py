# -*- coding: utf-8 -*-
"""
批次處理（逐段驗證 → 合併 → 產出最終檔）
"""
import os, re, json, time, hashlib
from typing import List, Tuple, Dict, Any, Optional, Callable

# ✅ 修正 import 為 modules.xx
from modules.transcribe import transcribe
from modules.analyze import run_analysis
from modules.ai_precheck import ai_precheck  # ✅ 確保這個模組放在 modules/
from docx import Document
from modules.doc_generator import generate_docx

# 預設資料夾
SEG_AUDIO_DIR_DEFAULT = os.path.join("output", "segments")
SEG_TEXT_DIR          = os.path.join("output", "segments_text")
FINAL_DIR             = os.path.join("output", "final")
LOGS_DIR              = os.path.join("output", "logs")

os.makedirs(SEG_TEXT_DIR, exist_ok=True)
os.makedirs(FINAL_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

def _nkey(s: str):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]

def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def _save_text(path: str, text: str):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text or "")

def _save_json(path: str, data: Dict[str, Any]):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _save_docx(path: str, summary: str, outline: List[str], todos: List[str]):
    doc = Document()
    doc.add_heading("會議摘要報告", level=0)
    doc.add_heading("摘要", level=1)
    doc.add_paragraph(summary if summary else "（無內容）")
    doc.add_heading("大綱", level=1)
    if outline:
        for item in outline:
            doc.add_paragraph(item, style="List Bullet")
    else:
        doc.add_paragraph("（無內容）")
    doc.add_heading("待辦事項", level=1)
    if todos:
        for t in todos:
            doc.add_paragraph(t, style="List Number")
    else:
        doc.add_paragraph("（無內容）")
    doc.save(path)

def _list_segments(seg_dir: str) -> List[str]:
    files = [os.path.join(seg_dir, f) for f in os.listdir(seg_dir)
             if os.path.splitext(f.lower())[1] in {".wav", ".mp3", ".m4a"}]
    files.sort(key=lambda p: _nkey(os.path.basename(p)))
    return files

def _stitch(paths: List[str], header_prefix: str) -> str:
    chunks = []
    for i, p in enumerate(paths, 1):
        name = os.path.basename(p)
        with open(p, "r", encoding="utf-8") as f:
            txt = f.read()
        chunks.append(f"=== {header_prefix} {i:02d} | {name} ===\n{txt}\n")
    return "\n".join(chunks)

def run_batch_process(
    segments_dir: str = SEG_AUDIO_DIR_DEFAULT,
    preview: bool = False,
    force: bool = False,
    return_progress: bool = False,
    *,
    start_index: int = 1,
    max_segments: Optional[int] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> str:
    t0 = time.time()
    progress: List[str] = []

    def log(msg: str):
        s = time.strftime("%H:%M:%S") + " " + msg
        print(s)
        progress.append(s)

    all_seg_files = _list_segments(segments_dir)
    if not all_seg_files:
        raise FileNotFoundError(f"在 {segments_dir} 沒找到任何音檔。")

    start = max(0, start_index - 1)
    end = None if not max_segments or max_segments <= 0 else start + max_segments
    seg_files = all_seg_files[start:end]
    total = len(seg_files)

    log(f"🔧 將處理段落：從第 {start_index} 段開始；最多處理 {max_segments if max_segments else '全部'} 段。")
    log(f"📊 實際段數：{total}（全部共有 {len(all_seg_files)} 段）")

    manifest = {
        "segments_dir": segments_dir,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "preview": preview,
        "items": [],
        "start_index": start_index,
        "count": total
    }

    if on_progress:
        try: on_progress(0, total, "開始處理")
        except: pass

    for idx, audio_path in enumerate(seg_files, 1):
        abs_index = start_index + idx - 1
        seg_id = f"{abs_index:02d}"
        base = f"seg_{seg_id}"
        paths = {
            "transcript": os.path.join(SEG_TEXT_DIR, f"{base}_transcript.txt"),
            "review":     os.path.join(SEG_TEXT_DIR, f"{base}_review.txt"),
            "revised":    os.path.join(SEG_TEXT_DIR, f"{base}_revised.txt"),
            "meta":       os.path.join(SEG_TEXT_DIR, f"{base}_meta.json"),
        }

        if not force and all(os.path.exists(p) for p in paths.values()):
            log(f"🟡 跳過 {base}（已有輸出）")
            with open(paths["meta"], "r", encoding="utf-8") as f:
                meta = json.load(f)
            manifest["items"].append(meta)
            if on_progress:
                try: on_progress(idx, total, f"跳過第 {abs_index} 段")
                except: pass
            continue

        log(f"🎧 [{seg_id}] 處理：{os.path.basename(audio_path)}")
        try:
            transcript = transcribe(audio_path)
            review_text, revised_text = ai_precheck(transcript, preview=preview)

            _save_text(paths["transcript"], transcript)
            _save_text(paths["review"], review_text)
            _save_text(paths["revised"], revised_text)

            meta = {
                "seg_id": seg_id,
                "audio": os.path.basename(audio_path),
                "audio_sha256": _sha256(audio_path),
                "paths": paths,
                "lens": {
                    "transcript": len(transcript or ""),
                    "review": len(review_text or ""),
                    "revised": len(revised_text or "")
                },
                "ok": True,
            }
            _save_json(paths["meta"], meta)
            manifest["items"].append(meta)
            log(f"✅ [{seg_id}] 完成（T{meta['lens']['transcript']}/R{meta['lens']['revised']}）")
        except Exception as e:
            meta = {
                "seg_id": seg_id,
                "audio": os.path.basename(audio_path),
                "paths": paths,
                "ok": False,
                "error": repr(e)
            }
            _save_json(paths["meta"], meta)
            manifest["items"].append(meta)
            log(f"❌ [{seg_id}] 失敗：{e!r}")

        if on_progress:
            try: on_progress(idx, total, f"完成第 {abs_index} 段")
            except: pass

    manifest_path = os.path.join(LOGS_DIR, "batch_manifest.json")
    _save_json(manifest_path, manifest)

    ok_items = [it for it in manifest["items"] if it.get("ok")]
    tr_paths = [it["paths"]["transcript"] for it in ok_items]
    rvw_paths = [it["paths"]["review"]     for it in ok_items]
    rvd_paths = [it["paths"]["revised"]    for it in ok_items]

    merged_transcript = _stitch(tr_paths, "TRANSCRIPT SEG") if tr_paths else ""
    merged_review     = _stitch(rvw_paths, "REVIEW SEG")     if rvw_paths else ""
    merged_revised    = _stitch(rvd_paths, "REVISED SEG")    if rvd_paths else ""

    final_paths = {
        "transcript_txt": os.path.join(FINAL_DIR, "transcript.txt"),
        "transcript_review_txt": os.path.join(FINAL_DIR, "transcript_review.txt"),
        "transcript_revised_txt": os.path.join(FINAL_DIR, "transcript_revised.txt"),
    }
    _save_text(final_paths["transcript_txt"], merged_transcript)
    _save_text(final_paths["transcript_review_txt"], merged_review)
    _save_text(final_paths["transcript_revised_txt"], merged_revised)

    summary, outline, todos = run_analysis(merged_revised, preview=False)

    meeting_paths = {
        "txt":  os.path.join(FINAL_DIR, "meeting_summary.txt"),
        "docx": os.path.join(FINAL_DIR, "meeting_summary.docx"),
        "json": os.path.join(FINAL_DIR, "meeting_summary.json"),
    }
    _save_text(meeting_paths["txt"],
               "【摘要】\n" + (summary or "") +
               "\n\n【大綱】\n" + "\n".join(outline or []) +
               "\n\n【待辦事項】\n" + "\n".join(todos or []))
    _save_docx(meeting_paths["docx"], summary, outline, todos)
    _save_json(meeting_paths["json"], {
        "summary": summary,
        "outline": outline,
        "todos": todos
    })

    log(f"📦 已產出報告：{meeting_paths['docx']}")
    log(f"⏱️ 總耗時：{time.time() - t0:.1f} 秒")

    # ✅ 為 Flask app.py 回傳報告檔案路徑即可
    return meeting_paths["docx"]
    generate_docx("output/final/meeting_summary.docx", summary, outline, todos)