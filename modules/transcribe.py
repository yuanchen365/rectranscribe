# modules/transcribe.py
import os
from openai import OpenAI
from dotenv import load_dotenv
from modules.clip_audio import clip_audio

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def transcribe(audio_path: str, preview: bool = False, test_duration: int = 120) -> str:
    """
    語音轉文字主函式

    Args:
        audio_path (str): 音檔路徑（.mp3 / .m4a / .wav）
        preview (bool): 是否啟用測試模式（裁剪前幾秒）
        test_duration (int): 預覽模式下裁剪秒數，預設 120 秒

    Returns:
        str: 轉錄後的純文字內容
    """
    print(f"🔊 開始轉錄音檔：{audio_path} (preview={preview})")

    # 暫存裁剪檔放在 output/temp/
    temp_dir = "output/temp"
    os.makedirs(temp_dir, exist_ok=True)
    trimmed_path = os.path.join(temp_dir, "temp_trimmed.wav")

    # 若啟用 preview 模式先裁剪
    file_path = clip_audio(audio_path, trimmed_path, test_duration) if preview else audio_path

    try:
        with open(file_path, "rb") as audio_file:
            response = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="text"
            )
        result_text = response if isinstance(response, str) else getattr(response, "text", str(response))
    except Exception as e:
        print(f"❌ Whisper API 錯誤：{e}")
        result_text = ""

    # 清理暫存檔案
    if preview and os.path.exists(trimmed_path):
        os.remove(trimmed_path)
        print(f"🧹 已清除暫存音檔 {trimmed_path}")

    return result_text.strip()

# ✅ CLI 測試模式
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="🎧 Whisper 語音轉文字工具")
    parser.add_argument("--input", type=str, required=True, help="輸入音檔路徑")
    parser.add_argument("--preview", action="store_true", help="是否僅轉錄前 120 秒")
    args = parser.parse_args()

    text = transcribe(args.input, preview=args.preview)

    with open("output/transcript.txt", "w", encoding="utf-8") as f:
        f.write(text)

    print("✅ 轉錄完成，已輸出 output/transcript.txt")
