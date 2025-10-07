# modules/adapter.py
from __future__ import annotations

from pathlib import Path
from typing import Tuple, Optional

from modules.batch_job import run_batch_process


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
    呼叫 run_batch_process 處理音檔；目前僅回傳最終輸出路徑與空白摘要欄位。
    如需實際摘要內容，應讀取 output/final/*/meeting_summary.txt 或 JSON。
    """

    file_path = Path(file_path).resolve()

    # 目前 run_batch_process 回傳最終 DOCX 檔案路徑（字串）
    try:
        docx_path = run_batch_process(
            segments_dir=str(file_path),
            preview=preview,
            return_progress=False,
        )
    except TypeError:
        # 向後相容：若參數位置不同，嘗試以位置引數呼叫
        docx_path = run_batch_process(str(file_path))

    final_dir = Path(docx_path).parent if docx_path else None
    txt_path = str(final_dir / "meeting_summary.txt") if final_dir and (final_dir / "meeting_summary.txt").exists() else None
    json_path = str(final_dir / "meeting_summary.json") if final_dir and (final_dir / "meeting_summary.json").exists() else None

    # 先回傳空字串；使用端可自行解析 txt/json 填入
    summary = ""
    outline = ""
    todos = ""
    revised_placeholder: Optional[str] = None
    progress_text = ""

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

