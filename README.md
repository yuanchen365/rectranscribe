太好了！以下是一份為「新手友善」量身打造的、可直接貼到你 repo 根目錄的 README.md。
（內含：完整安裝、.env 設定、FFmpeg 安裝、操作教學、架構圖、資料夾說明、部署與常見錯誤排除等）

貼進 README.md 後：
git add README.md && git commit -m "docs: add beginner-friendly README" && git push origin main

# rectranscribe 🎙️
**會議錄音 ➜ 語音轉文字 ➜ AI 修訂 ➜ 摘要/大綱/待辦** 的自動化系統（V5.0）

- 支援長音檔自動切割（每段約 5 分鐘）
- Whisper / OpenAI 模型轉錄
- AI 預檢與修正版逐字稿
- 合併輸出 **TXT / DOCX / JSON**
- 介面：Flask（模板在 `templates/`）＊若改用 Gradio，也可另啟 `app_gradio.py`（可選）

---

## 目錄
- [快速開始（5 分鐘）](#快速開始5-分鐘)
- [環境需求](#環境需求)
- [.env（環境變數）設定](#env環境變數設定)
- [FFmpeg 安裝（必要）](#ffmpeg-安裝必要)
- [如何使用](#如何使用)
- [系統架構圖](#系統架構圖)
- [資料夾結構](#資料夾結構)
- [輸出與檔案說明](#輸出與檔案說明)
- [部署（MVP）](#部署mvp)
- [常見問題（Troubleshooting）](#常見問題troubleshooting)
- [版本控管建議（給新手）](#版本控管建議給新手)
- [安全與隱私](#安全與隱私)
- [授權](#授權)
- [Roadmap](#roadmap)

---

## 快速開始（5 分鐘）

```bash
# 1) 下載專案
git clone https://github.com/yuanchen365/rectranscribe.git
cd rectranscribe

# 2) 建立虛擬環境並啟用（Windows）
python -m venv .venv
.venv\Scripts\activate

# macOS / Linux
# python3 -m venv .venv
# source .venv/bin/activate

# 3) 安裝套件
pip install -r requirements_flask.txt

# 4) 建立 .env（放在專案根目錄）
#    內容見下方「.env（環境變數）設定」章節

# 5) 安裝 FFmpeg（必要，見下方章節）

# 6) 啟動服務（Flask 介面）
python app.py
# 預設：http://127.0.0.1:5000


若你使用 Gradio 版本，則改執行：python app_gradio.py（若 repo 有此檔）

環境需求

Python 3.10+（建議 3.11）

pip / venv

FFmpeg（音訊切割與格式轉換必備）

OpenAI API Key（用於轉錄與文字分析）

.env（環境變數）設定

在專案根目錄新增 .env 檔：

OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
# 其他可選參數（有需要再加）
# TEST_MODE=true
# TEST_DURATION=120


🔒 .env 不可上傳到 GitHub。此 repo 的 .gitignore 已包含 .env，請妥善保存你的金鑰。

FFmpeg 安裝（必要）
Windows

前往 FFmpeg 官方或第三方鏡像下載 zip（任意 stable 版皆可）。

解壓縮到 C:\ffmpeg（例如）。

將 C:\ffmpeg\bin 加到「系統環境變數 PATH」。

開新終端機執行：

ffmpeg -version


若能顯示版本資訊代表安裝成功。

macOS
brew install ffmpeg
ffmpeg -version

Linux（Debian/Ubuntu）
sudo apt-get update
sudo apt-get install -y ffmpeg
ffmpeg -version

如何使用
A) Flask 介面（本專案預設）
python app.py
# 打開瀏覽器 http://127.0.0.1:5000


操作步驟：

上傳會議音檔（mp3/wav/m4a）

選擇「起始段」、「要處理幾段（0=到結尾）」與「預覽模式（僅前2分鐘/約500字）」

點「開始處理」

完成後可於頁面下載 TXT / DOCX / JSON 成果

B) Gradio 介面（可選）

若你的 repo 也有 app_gradio.py：

python app_gradio.py
# 預設 http://127.0.0.1:7860

系統架構圖

以下使用 Mermaid 描述主要流程（GitHub 會自動渲染）：

flowchart LR
    A[使用者上傳音檔] --> B[split_audio.py<br/>切割為 part_01.wav...]
    B --> C[batch_job.py<br/>批次處理主流程]
    C --> C1[transcribe.py<br/>語音轉文字]
    C --> C2[ai_precheck.py<br/>AI 審閱/修訂]
    C --> C3[合併修正版全文<br/>transcript_revised.txt]
    C3 --> C4[analyze.py<br/>摘要/大綱/待辦]
    C4 --> D[doc_generator.py<br/>產出 TXT/DOCX/JSON]
    D --> E[前端呈現/下載]

資料夾結構
rectranscribe/
├─ modules/                 # 功能模組（transcribe, analyze, ai_precheck, split_audio, batch_job, doc_generator...）
├─ output/                  # 產出資料夾（程式會自動生成）
│  ├─ segments/             # 本次切割出的分段音檔（part_XX.wav）
│  ├─ segments_text/        # 各段轉錄/審閱/修正版與 meta
│  ├─ final/                # 合併後的 transcript 與 meeting_summary（txt/docx/json）
│  └─ logs/                 # 進度與 manifest 日誌
├─ static/                  # （Flask）CSS/圖片等靜態資源
├─ templates/               # （Flask）頁面模板
├─ uploads/                 # 上傳的音檔暫存
├─ app.py                   # Flask 入口（或視你的版本為主）
├─ requirements_flask.txt   # 套件需求（pip install -r）
├─ .env                     # 本地環境變數（請勿上傳）
└─ .gitignore

輸出與檔案說明

output/segments_text/seg_XX_transcript.txt：第 XX 段的原始逐字稿

output/segments_text/seg_XX_review.txt：AI 審閱說明

output/segments_text/seg_XX_revised.txt：AI 修正版逐字稿

output/final/transcript.txt：合併原始逐字稿（含段界標頭）

output/final/transcript_review.txt：合併審閱稿

output/final/transcript_revised.txt：合併修正版逐字稿（總分析依此進行）

output/final/meeting_summary.txt：最終摘要/大綱/待辦（純文字）

output/final/meeting_summary.docx：最終報告（Word）

output/final/meeting_summary.json：最終報告（JSON 結構化）

部署（MVP）

適合先上線 Demo 或內部測試

Railway / Render / Hugging Face Spaces（三選一）

上傳程式碼、於平台後台設定環境變數 OPENAI_API_KEY

指定啟動命令（例如：python app.py）

綁定自訂網域（可選）

VPS（正式）：Nginx + Gunicorn + Flask

將 .env 轉為伺服器的 環境變數

設定 systemd service 自動重啟

限制 uploads/ 與 output/ 的容量與清理排程

常見問題（Troubleshooting）
1) GitHub 拒絕推送：偵測到 Secrets（OpenAI Key）

現象：Push Protection 擋下推送
解法：

確保 .env 已在 .gitignore 中

移除歷史中的 .env：

安裝 git-filter-repo 後：git filter-repo --path .env --invert-paths

或用孤立分支重建：

git checkout --orphan clean-main
git rm --cached .env
echo ".env" >> .gitignore
git add .
git commit -m "feat: clean initial commit without secrets"
git branch -M main
git push -f origin main

2) pydub 或 ffmpeg 錯誤

現象：切割音檔/讀取檔案時錯誤
解法：確保安裝 FFmpeg，且 ffmpeg -version 可執行。Windows 記得把 ffmpeg\bin 加到 PATH。

3) OpenAI 金鑰錯誤或無效

現象：401/403/429 等錯誤
解法：

檢查 .env 的 OPENAI_API_KEY 是否正確

確認專案使用的 API 模型/權限可用

減少同時請求（429：rate limit）

4) 上傳大檔失敗 / 記憶體不足

建議：先在本地切割、或啟用預覽模式（僅前 2 分鐘/500 字）測試流程；伺服器佈署時限制檔案大小。

版本控管建議（給新手）

分支策略

main：穩定可部署

feat/xxx：新功能

fix/xxx：修 bug

範例：feat/gradio-scrollbar、fix/batch-timeout

Commit 訊息格式

<type>(scope): <subject>
# type: feat / fix / docs / refactor / test / chore
# 例：feat(batch_job): support start_index & max_segments

安全與隱私

.env 只放在本地；雲端部署改用平台的「環境變數」設定

uploads/ 與 output/ 可能含敏感內容，請定期清理或加權限

若要商用，請在隱私權政策中告知「音檔/逐字稿」的處理方式與保存天數

授權

MIT License