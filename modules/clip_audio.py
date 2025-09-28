# modules/clip_audio.py
from pydub import AudioSegment
import os

def clip_audio(input_path: str, out_path: str = "output/trimmed/temp_trimmed.wav", max_seconds: int = 120) -> str:
    """
    將音檔裁剪至指定秒數後輸出為 .wav 格式

    Args:
        input_path (str): 原始音檔路徑（支援 .mp3 / .m4a / .wav）
        out_path (str): 輸出音檔路徑（預設 output/trimmed/temp_trimmed.wav）
        max_seconds (int): 最大裁剪長度（秒），預設 120 秒

    Returns:
        str: 輸出音檔完整路徑
    """
    print(f"🎧 載入音檔：{input_path}")
    audio = AudioSegment.from_file(input_path)

    trimmed = audio[:max_seconds * 1000]  # pydub 以毫秒為單位

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    trimmed.export(out_path, format="wav")
    print(f"✂️ 已裁剪前 {max_seconds} 秒並儲存至：{out_path}")

    return out_path

# ✅ 測試用 CLI 執行點
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="✂️ 將音檔裁剪成前 n 秒")
    parser.add_argument("--input", type=str, required=True, help="輸入音檔路徑")
    parser.add_argument("--out", type=str, default="output/trimmed/temp_trimmed.wav", help="輸出音檔路徑")
    parser.add_argument("--max", type=int, default=120, help="最大裁剪秒數")
    args = parser.parse_args()

    clip_audio(args.input, args.out, args.max)
