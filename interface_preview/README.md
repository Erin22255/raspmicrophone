# SPL Meter 介面預覽

這個資料夾只用來檢查正式儀表板的版面，不會開啟麥克風，也不會送入或顯示模擬測量數值。SPL、Leq、Max 會維持 `--.-`，圖表會保持空白；狀態列會顯示 `INTERFACE PREVIEW | NO AUDIO INPUT`。

在專案根目錄的終端執行：

```powershell
.\.venv\Scripts\python.exe .\interface_preview\preview.py
```

如果已啟用虛擬環境，也可執行：

```powershell
python .\interface_preview\preview.py
```

Linux / Raspberry Pi 的桌面終端執行：

```bash
source .venv/bin/activate
python interface_preview/preview.py
```

這只會檢查目前 `dashboard.py` 的介面排版；正式量測仍請從專案根目錄執行 `python run.py`。
