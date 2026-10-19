# 聲音位準計 Sound Lab

這是一個以 Python、PyQt5、pyqtgraph 與 sounddevice 建立的即時聲音位準計。它可在筆電使用一般 USB/內建麥克風開發，也可在 Raspberry Pi 5 桌面環境執行。介面以 800 x 480 螢幕為目標，包含 SPL、Leq、Max、時域波形、FFT 與 1/3 倍頻程檢視。

## 專案檔案

```text
raspmicrophone/
├── audio_input.py   # 麥克風裝置搜尋、音訊串流啟停
├── .gitignore       # 排除虛擬環境與 Python 快取
├── config.json      # 取樣率與聲壓計算設定
├── dashboard.py     # 800 x 480 PyQt5 使用者介面
├── dsp.py           # 加權濾波、SPL、FFT、1/3 倍頻程
├── interface_preview/ # 無麥克風、無測量數值的版面預覽工具
├── readmecode.md    # 各程式檔案的職責與執行時機
├── recording.py     # WAV 錄音、存檔與讀取
├── requirements.txt # Python 套件清單
└── run.py           # 唯一建議使用的程式入口
```

只想檢查介面排版、不使用麥克風或顯示測量數值時，可執行：

```powershell
python .\interface_preview\preview.py
```

預覽視窗會顯示 `INTERFACE PREVIEW | NO AUDIO INPUT`，SPL/Leq/Max 和圖表維持空白。正式量測請執行 `python run.py`。

## 筆電安裝與測試

在專案資料夾開啟 PowerShell。建議使用 Python 3.11 或 3.12；建立虛擬環境並安裝套件：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

列出 sounddevice 能辨識的錄音裝置：

```powershell
python run.py --list-devices
```

啟動完整介面：

```powershell
python run.py
```

如果 PowerShell 不允許啟用虛擬環境，也可直接執行：

```powershell
.\.venv\Scripts\python.exe .\run.py
```

Windows 請到「設定 > 隱私權與安全性 > 麥克風」允許桌面應用程式存取麥克風。程式會先嘗試系統預設輸入裝置，再依序嘗試其他可用輸入裝置。

## Raspberry Pi 5 安裝

### 開機後操作流程

如果 Raspberry Pi 尚未安裝作業系統，請先用 Raspberry Pi Imager 將 Raspberry Pi OS Desktop 寫入系統 SD 卡，再插入 Pi 開機並完成初始設定。這張是系統卡，不要為了傳送專案重新格式化。

專案不必壓縮。Pi 開機進入桌面後，最簡單的傳檔方式是將專案資料夾放到 USB 隨身碟，再插入 Pi，使用檔案管理員把整個 `raspmicrophone` 資料夾複製到家目錄。也可以使用 Git 複製專案。完成後，路徑應為 `~/raspmicrophone`，且資料夾內要有 `run.py`、`audio_input.py`、`dashboard.py`、`dsp.py`、`config.json` 和 `requirements.txt`。不需要複製筆電上的 `.venv` 或 `__pycache__`。

第一次使用這台 Pi 時，開啟桌面終端，安裝系統需求和 Python 套件。詳細安裝指令見下方「1. 準備系統與螢幕」；安裝完成後不必每次開機重裝套件。

之後每次開機要使用聲音位準計時：

1. 進入 Raspberry Pi OS 桌面，接好 USB 麥克風；若使用 INMP441，先確認 I2S/ALSA 錄音裝置已設定完成。
2. 開啟桌面終端並執行：

	```bash
	cd ~/raspmicrophone
	source .venv/bin/activate
	python run.py --list-devices
	```

3. 確認清單列出麥克風輸入裝置，再啟動介面：

	```bash
	python run.py
	```

4. 確認畫面顯示麥克風名稱或 `LIVE`。關閉視窗即可結束程式。

請從 Raspberry Pi 的圖形桌面終端啟動，PyQt5 介面需要桌面工作階段；不要從純 SSH 終端啟動並期待視窗顯示。若只有另一張資料 SD 卡可用，Pi 開機後需透過 USB 讀卡機讀取；一般情況使用 USB 隨身碟傳檔較簡單。

### 安全關機注意事項

1. 先關閉聲音位準計視窗，讓程式停止音訊串流並釋放麥克風。若終端仍在虛擬環境中，可輸入 `deactivate` 離開；這不是必要步驟，但可讓終端回到一般狀態。
2. 使用 Raspberry Pi 桌面選單的「Shutdown / 關機」，或在終端執行：

	```bash
	sudo shutdown -h now
	```

3. 等待桌面畫面熄滅、系統停止活動並完成關機後，才拔除電源。不要在程式執行或系統仍在寫入資料時直接拔電，也不要用拔電方式代替正常關機，以免 SD 卡檔案系統損壞。
4. 若要重新接線、拆裝 INMP441 或移動 GPIO 杜邦線，務必先正常關機並拔除電源，再進行操作；勿在通電時插拔 GPIO 線。

### 1. 準備系統與螢幕

建議使用 64 位元 Raspberry Pi OS Desktop。PyQt5 需要圖形桌面工作階段；不要從沒有圖形工作階段的純 SSH 終端直接啟動 GUI。將 DSI 螢幕依照螢幕廠商提供的排線方向和接口說明連到 Pi 5 的 DSI 接口，並依螢幕規格供電。不同 4.3 吋螢幕的排線、供電和觸控方式可能不同，請以該型號手冊為準。進入桌面後確認顯示解析度為 800 x 480。

先更新系統並安裝音訊建置所需的系統函式庫：

```bash
sudo apt update
sudo apt full-upgrade -y
sudo apt install -y python3 python3-venv python3-pip libportaudio2 portaudio19-dev
```

把專案資料夾放到 Pi（例如從 USB 隨身碟複製或使用 `git clone`），在 Pi 的終端進入該資料夾：

```bash
cd ~/raspmicrophone
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

若套件安裝失敗，先確認正在使用 64 位元 Raspberry Pi OS、網路可用且 `python3 --version` 顯示受支援的 Python 版本。不要在系統 Python 上使用 `sudo pip install`。

### 2. 先用 USB 麥克風驗證

USB 麥克風通常會由 Raspberry Pi OS 自動建立錄音裝置，是第一次測試最簡單的方式。插入 USB 麥克風後執行：

```bash
source .venv/bin/activate
python run.py --list-devices
python run.py
```

畫面左下方顯示麥克風名稱或 `LIVE` 即代表程式已開啟輸入串流。若清單沒有輸入裝置，請先檢查 USB 麥克風、桌面音訊設定與系統權限。

## INMP441 接線

接線前關閉 Raspberry Pi 電源。以下使用 Raspberry Pi 40-pin 排針的**實體腳位編號**；請用排針上的 Pin 1 標記確認方向，不要把實體腳位編號和 GPIO 編號混為一談。

| INMP441 腳位 | Raspberry Pi 5 接點 | 說明 |
| --- | --- | --- |
| VDD | 實體 Pin 1（3V3） | 只接 3.3 V，絕對不要接 5 V |
| GND | 實體 Pin 6（GND） | 麥克風與 Pi 共地 |
| SCK | 實體 Pin 12（GPIO18 / PCM_CLK） | I2S 位元時鐘 BCLK |
| WS | 實體 Pin 35（GPIO19 / PCM_FS） | I2S 左右聲道時鐘 LRCLK/WS |
| SD | 實體 Pin 38（GPIO20 / PCM_DIN） | 麥克風資料輸出，接 Pi 的 I2S 資料輸入 |
| L/R | 實體 Pin 6（GND） | 拉低選左聲道；不要讓此腳位懸空 |

若想選右聲道，將 L/R 接到實體 Pin 1（3V3），同一個麥克風只需選一個聲道。Pi 的 GPIO 是 3.3 V 邏輯。建議先使用杜邦線逐條核對標籤，並確認模組的 VDD/GND 不會接反。

### 重要：I2S 接線不等於作業系統已支援麥克風

INMP441 是 I2S 數位麥克風，不是 USB 麥克風。單純接好上表的線，並不保證 Raspberry Pi OS 會自動出現可錄音的 ALSA 裝置。核心必須有與目前 Raspberry Pi OS、核心版本及 INMP441 相容的 Device Tree overlay/音訊卡驅動，並把 I2S 輸入註冊成 ALSA capture device。`dtparam=i2s=on` 只開啟 I2S 控制器，未必會建立完整的錄音裝置；請勿直接套用為其他聲卡設計的 overlay。

完成該硬體驅動設定並重新開機後，先檢查 ALSA 是否列出錄音卡，再檢查本程式是否能看到輸入裝置：

```bash
arecord -l
python run.py --list-devices
```

若 `arecord -l` 沒有 capture card，請先處理作業系統的 I2S/overlay/驅動設定，程式端無法替代這一層。若老師要求 INMP441，請使用與你的 Pi 5 OS/核心版本相符且已測試的 INMP441 overlay；若目前沒有可用的 overlay，先以 USB 麥克風完成 GUI 與 DSP 測試，再和老師確認指定的 I2S 驅動設定。不要將 INMP441 的 SCK/WS/SD 接到任意 GPIO，因為本程式不會以一般 GPIO bit-banging 讀取 I2S。

## 設定與執行

`config.json` 目前設定為 48 kHz、每次 4800 個取樣點、參考聲壓 20 µPa、預設 A 加權。啟動程式：

```bash
source .venv/bin/activate
python run.py
```

若有多個麥克風，程式預設採用作業系統的預設輸入；預設輸入無效時，會嘗試其他可用輸入。也可在 `config.json` 的 JSON 物件內增加選填欄位來指定裝置索引或裝置名稱的一部分，例如在 `weighting` 後加逗號，再加上：

```json
"input_device": "USB Microphone"
```

`--list-devices` 會顯示裝置索引與名稱，將 `input_device` 設為其中一個索引（整數）或名稱片段（字串）。

## 使用介面功能

主視窗以四個頁籤分開功能，保留原本測量頁的波形和 FFT/1/3 OCT 圖表：

- **測量**：顯示即時 SPL、Leq、Max、波形及頻譜。預設 A 加權（dBA）；C、Z 可用於比較。FAST、SLOW、IMPULSE 是獨立的聲級時間響應選擇，分別使用 125 ms、1 s，以及 35 ms 上升 / 1.5 s 下降時間常數。它們不是音訊圖表更新速率。
- **錄音**：錄音、暫停/繼續、停止、存成 16-bit PCM WAV，並可選取已儲存的 WAV 播放。錄音存於專案的 `recordings/` 資料夾；關閉程式會停止錄音，不會自動存檔。
- **頻譜分析**：顯示主峰頻率與 dB/Hz，並限制峰值搜尋頻帶。FAN（60–500 Hz）、MUSIC（80–12000 Hz）、ALL（20 Hz–Nyquist）只是方便操作的頻帶預設，可自行改上下限，不是 IEC 定義的固定分類。
- **校正**：輸入已知參考聲級，以穩定 1 kHz 音調收集 3 秒資料，檢查主頻與聲級穩定度後計算 `cal_factor`，並寫回 `config.json`。可按「重置校正」恢復未校正係數。

校正不能只靠「手機播放 1 kHz」完成：手機提供頻率，不保證麥克風位置的聲壓。建議使用聲校正器（例如 1 kHz、94 dB SPL），或把已校正聲級計放在麥克風位置作參考。若沒有已知聲壓來源，請保留「未校正」狀態；輸入一個猜測的參考值不會讓量測變準。

## 聲壓校正與測量限制

`cal_factor` 初始值 `1.0` 只是讓程式可以執行，不是麥克風的校正值。不同麥克風、前級增益、I2S 驅動與 USB 音效卡都會有不同靈敏度；沒有校正時，畫面上的 dB SPL 只能視為未校正讀值，不能當作合格聲級計或法規測量結果。

要得到有意義的 SPL，需用已知聲壓的聲校正器/參考聲源，按麥克風及驅動的數位輸出尺度求出並填入 `cal_factor`。例如參考聲源為 94 dB SPL、1 kHz 時，其聲壓約為 1 Pa RMS；須根據實際讀到的數位 RMS 求出「Pa/數位振幅」係數。正式使用前也要確認麥克風頻率響應、I2S 位元格式、系統增益和左右聲道設定。

目前的 IEC 風格 A/C 權重是供專題展示與一般分析使用的數位濾波近似。整套硬體未經聲學校正、頻率響應與法規流程驗證前，不應宣稱為 IEC 61672 認證聲級計。

## 常見問題

- `MICROPHONE UNAVAILABLE`：先執行 `python run.py --list-devices`。USB 麥克風需在系統出現輸入裝置；INMP441 需先確認 I2S 音效卡已由核心註冊。
- `PortAudioError` 或取樣率錯誤：確認輸入裝置支援 `config.json` 的 48000 Hz；必要時選擇支援的取樣率並同步修改設定。
- 沒有圖形畫面：請從 Raspberry Pi 桌面終端啟動，並確認螢幕已被系統辨識。
- SPL 數值不準：確認 `cal_factor` 和輸入增益已校正。單純改變 `p_ref` 不會校正麥克風。
