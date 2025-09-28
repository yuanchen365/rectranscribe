# modules/adapter.py
from __future__ import annotations
from pathlib import Path
from typing import Tuple, Optional, Any

from modules.batch_job import run_batch_process  # ← 依你檔案路徑

def process_audio_job(
    file_path: str | Path,
    preview: bool = False,
) -> Tuple[
    str,  # summary
    str,  # outline
    str,  # todos
    Optional[str],  # revised_placeholder
    Optional[str],  # txt_path
    Optional[str],  # docx_path
    Optional[str],  # json_path
    str,  # progress_text
]:
    """
    包裝你的 run_batch_process，提供給 Flask 呼叫。
    現在版本不使用 start_segment 與 num_segments，僅保留 preview。
    """

    file_path = Path(file_path).resolve()

    # 呼叫你的核心邏輯（不含 start_segment / num_segments）
    try:
        results_dict, progress_log = run_batch_process(
            str(file_path),
            return_progress=True,
            preview=preview
        )
    except TypeError:
        # 若你的版本甚至沒有 preview，就退化呼叫
        results_dict, progress_log = run_batch_process(
            str(file_path),
            return_progress=True
        )

    summary = str(results_dict.get("summary", "") or "")
    outline = str(results_dict.get("outline", "") or "")
    todos = str(results_dict.get("todos", "") or "")

    txt_path = results_dict.get("txt_path")
    docx_path = results_dict.get("docx_path")
    json_path = results_dict.get("json_path")

    revised_placeholder: Optional[str] = None

    if isinstance(progress_log, list):
        progress_text = "\n".join(map(str, progress_log))
    else:
        progress_text = str(progress_log or "")

    return (
        summary,
        outline,
        todos,
        revised_placeholder,
        txt_path,
        docx_path,
        json_path,
        progress_text,
    )
