# modules/split_audio.py
import os
from pydub import AudioSegment
from typing import Optional

def split_audio(input_file: str, output_dir: str = "output/segments", chunk_length_sec: int = 300) -> int:
    """
    將音檔依固定秒數切割，輸出為多個 .wav 檔，並回傳總段數。

    Args:
        input_file (str): 原始音檔路徑（.mp3 / .wav / .m4a）
        output_dir (str): 輸出目錄（預設 output/segments）
        chunk_length_sec (int): 每段秒數（預設 300 秒 = 5 分鐘）

    Returns:
        int: 總共切出幾段
    """
    print(f"📂 載入音檔：{input_file}")

    # 🧹 清除舊的分段音檔
    if os.path.exists(output_dir):
        for fname in os.listdir(output_dir):
            if fname.lower().endswith((".wav", ".mp3", ".m4a")):
                os.remove(os.path.join(output_dir, fname))
        print(f"🧹 已清空舊分段音檔：{output_dir}")
    else:
        os.makedirs(output_dir)

    audio = AudioSegment.from_file(input_file)
    chunk_length_ms = chunk_length_sec * 1000
    total_parts = 0

    for i, start_ms in enumerate(range(0, len(audio), chunk_length_ms)):
        end_ms = min(start_ms + chunk_length_ms, len(audio))
        chunk = audio[start_ms:end_ms]
        out_path = os.path.join(output_dir, f"part_{i+1:02d}.wav")
        chunk.export(out_path, format="wav")
        print(f"✅ 已輸出分段：{out_path}")
        total_parts += 1

    print(f"📊 共切割出 {total_parts} 段")
    return total_parts
