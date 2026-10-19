# 程式檔案說明

一般使用者只需執行 `run.py`。其餘模組由主程式載入，不需要分別啟動。

| 檔案 | 負責工作 | 何時執行/使用 |
| --- | --- | --- |
| `run.py` | 讀取並檢查 `config.json`、建立 Qt 應用程式、連接音訊輸入與儀表板；提供 `--list-devices` 裝置診斷選項。 | 每次要執行整個專題時執行：`python run.py`。檢查麥克風時執行：`python run.py --list-devices`。 |
| `audio_input.py` | 使用 sounddevice 搜尋可用輸入裝置、嘗試開啟單聲道音訊串流，並將每個音訊區塊交給儀表板。程式關閉時停止並釋放串流。 | 由 `run.py` 啟動時載入；不需要手動執行。若要改成指定裝置或其他音訊來源，從這個模組調整裝置管理。 |
| `dashboard.py` | 建立 800 x 480 PyQt5 介面；顯示 dB SPL、Leq、Max、時域波形，並切換 FFT/1/3 OCT；每 100 ms 更新一次畫面。 | 由 `run.py` 建立視窗並呼叫；不需要手動執行。 |
| `dsp.py` | `AudioDSP` 訊號處理核心：A/C/Z 加權、RMS、SPL、FFT PSD 與標準三分之一倍頻程頻帶能量。 | 由 `dashboard.py` 在收到音訊後呼叫；修改聲學計算或權重濾波器時才需編輯。 |
| `config.json` | 保存取樣率、區塊大小、參考聲壓、麥克風校正係數與初始加權。 | 每次 `run.py` 啟動時讀取。調整硬體取樣率或完成麥克風校正後修改。 |
| `requirements.txt` | 列出 NumPy、SciPy、sounddevice、PyQt5、pyqtgraph 等 Python 相依套件。 | 新電腦或 Raspberry Pi 第一次安裝專案時執行 `pip install -r requirements.txt`。 |
| `.gitignore` | 避免把虛擬環境與 Python 快取檔加入版本控制。 | 不需執行；使用 Git 管理專案時自動生效。 |
| `README.md` | 安裝、執行、Raspberry Pi 5/DSI 使用、INMP441 接線與硬體驅動注意事項。 | 第一次部署、接線或排查問題時閱讀。 |

## 建議操作順序

1. 第一次使用新電腦/Pi：依 `README.md` 建立 Python 虛擬環境並安裝 `requirements.txt`。
2. 開始量測前：接好 USB 麥克風，或確認 INMP441 的 I2S ALSA capture 裝置已建立；執行 `python run.py --list-devices` 檢查。
3. 啟動專題：執行 `python run.py`。主程式會讀取設定、開啟音訊輸入、顯示介面。
4. 修改測量設定：編輯 `config.json`；校正麥克風後更新 `cal_factor`，不要把未校正的預設值當成真實 SPL。
5. 修改演算法或介面：演算法改 `dsp.py`，麥克風裝置改 `audio_input.py`，按鈕/圖表/顯示改 `dashboard.py`，啟動與設定流程改 `run.py`。
