# MSSQL 資料查詢系統（manage-sql）

[![CI](https://github.com/itmanapp/manage-sql/actions/workflows/ci.yml/badge.svg)](https://github.com/itmanapp/manage-sql/actions/workflows/ci.yml)

離線環境專用的會員資料查詢網頁。讀取 Microsoft SQL Server 資料庫（`.mdf` 檔附加後的資料表），支援「姓名、身份證、地址、電話」四條件搜尋，並以**帳號密碼 + TOTP 動態驗證碼**進行完全離線的兩階段登入認證。

CI 已使用 **Microsoft 官方 AdventureWorksLT2012 範例 MDF** 在真實 SQL Server 2022 容器上驗證完整流程（附加 MDF → 登入 → TOTP → 四欄位搜尋）。

## 功能特色

| 需求 | 實作 |
|---|---|
| 讀取 MSSQL 資料庫（MDF 檔） | 透過 `pymssql` 連線 SQL Server；MDF 以 `FOR ATTACH` 方式載入（見下方） |
| 多格式資料庫檔案 + 自動判別 | `backend: auto` 自動辨識 SQLite／Access(MDB/ACCDB)／dBASE(DBF)／SQL Server MDF |
| 條件搜尋：姓名／身份證／地址／電話 | 參數化 LIKE 查詢，多條件 AND 結合，支援部分比對、分頁 |
| 資料寫入 | 可讀寫格式提供網頁「新增一筆」與逐列「刪除」（含確認），唯讀格式自動隱藏 |
| 離線登入認證 + TOTP | 本地 SQLite 帳號庫（PBKDF2-HMAC-SHA256），TOTP 依 RFC 6238 自行實作，零外部服務 |

其他安全設計：

- 兩步式登入：密碼正確後才進入 TOTP 頁
- TOTP 重放防護：同一時間切片（30 秒）的代碼只能使用一次
- 密碼連續錯誤 5 次 → 鎖定 5 分鐘
- 所有表單附 CSRF token；Session Cookie 設 `HttpOnly` / `SameSite=Lax`
- SQL 一律參數化，識別碼加引號處理，輸入長度限制
- 未偵測使用者時也執行雜湊運算，避免帳號枚舉時序攻擊

## 目錄結構

```
├── run.py                  啟動伺服器
├── manage.py               管理工具（建帳號、重設 TOTP、示範資料）
├── config.yaml             主要設定（自 config.yaml.example 複製）
├── app/
│   ├── auth.py             登入／TOTP／登出流程
│   ├── search.py           搜尋頁邏輯
│   ├── db.py               SQL Server / SQLite 後端、欄位自動對應
│   ├── totp.py             RFC 6238 TOTP 實作
│   ├── users.py            帳號儲存（SQLite + PBKDF2）
│   └── templates/, static/
├── scripts/
│   ├── attach_mdf.sh       將 MDF/LDF 附加進 Docker 版 SQL Server
│   └── smoke_test.sh       端對端煙霧測試
├── docker-compose.yml      離線可用的 SQL Server 2022 容器
├── .github/workflows/ci.yml  CI：真實 SQL Server 附加 MDF 的整合測試
└── tests/                  單元測試、E2E、多格式讀寫、MSSQL 整合測試
```

## 安裝

### 取得專案

```bash
git clone https://github.com/itmanapp/manage-sql.git
cd manage-sql
```

### 安裝相依套件

需求：Python 3.10+（開發環境以 3.11 驗證）

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

相依套件共 5 個：`Flask`（網頁框架）、`PyYAML`（設定檔）、`pymssql`（SQL Server 驅動）、`access-parser`（Access 唯讀解析）、`dbf`（dBASE 讀寫），皆為純 Python 或含預編譯 wheel。

### 快速開始（示範模式，SQLite）

```bash
cp config.yaml.example config.yaml        # 預設 backend: sqlite
.venv/bin/python manage.py seed-demo      # 建立 12 筆虛構示範資料
.venv/bin/python manage.py adduser admin  # 依提示設定密碼，記下畫面上的 TOTP 密鑰

.venv/bin/python run.py                   # http://127.0.0.1:8000
```

登入流程：輸入帳密 → 在驗證器 App（Google Authenticator、Aegis 等）以手動輸入方式新增剛才的 Base32 密鑰 → 輸入 6 位動態碼完成登入。

## 支援格式與自動判別

設定 `backend: auto` 並指定檔案路徑，系統會先以**魔術位元組＋標頭結構**判別檔案類型再載入：

| 格式 | 常見副檔名 | 判別依據 | 讀取 | 寫入 |
|---|---|---|---|---|
| SQLite | `.db` `.sqlite` `.sqlite3` | 開頭魔術字串 `SQLite format 3` | ✅ | ✅ 新增／刪除 |
| dBASE / FoxPro | `.dbf` | 版本旗標＋日期＋標頭長度結構 | ✅ | ✅ 新增／刪除 |
| Microsoft Access (Jet) | `.mdb` | 偏移 4 的 `Standard Jet DB` | ✅ | ❌ 唯讀 |
| Microsoft Access (ACE) | `.accdb` | 偏移 4 的 `Standard ACE DB` | ✅ | ❌ 唯讀 |
| SQL Server 資料檔 | `.mdf` | 8KB 分頁對齊＋內容特徵 | 需先附加引擎 | 經 SQL Server 讀寫 |

```yaml
database:
  backend: auto
  file: data/sample.dbf     # 要載入的資料庫檔案
  table: Members            # SQLite / Access 需指定資料表（DBF 為單表格式免設定）
  encoding: utf-8           # DBF 編碼：utf-8 或 big5 (cp950)、gbk
```

- 登入後頁面頂部會顯示「已載入：〈格式〉（可讀寫／僅可讀）」橫幅
- 不確定檔案內容時，可用管理工具判別：
  ```bash
  .venv/bin/python manage.py detect data/sample.dbf
  # 會印出類型、可否寫入、可用資料表清單與建議設定方式
  ```
- DBF 中文亂碼時調整 `encoding`（台灣常用 `big5`）；DBF 為固定長度欄位，寫入超出欄位寬度會被拒絕並提示
- Access 格式基於第三方解析器（access-parser）為唯讀；需要寫入時請先轉換為 SQLite
- 選到 `.mdf` 時會引導改用 `backend: sqlserver`（需先附加至引擎）

## 正式環境：載入 MDF 檔

MDF 是 SQL Server 的資料檔，需先由 SQL Server 引擎附加（ATTACH）。三種常見做法：

### A. Docker 版 SQL Server（Linux 離線主機建議）

1. **在還有網路時**預先拉取映像並匯出備用：
   ```bash
   docker pull mcr.microsoft.com/mssql/server:2022-latest
   docker save mcr.microsoft.com/mssql/server:2022-latest -o mssql2022.tar
   # 離線主機上：docker load -i mssql2022.tar
   ```
2. 將 `.mdf` / `.ldf` 放入 `./data/`，啟動容器：
   ```bash
   docker compose up -d
   ```
3. 附加資料庫：
   ```bash
   ./scripts/attach_mdf.sh MemberData YourData.mdf YourData.ldf
   ```
4. 修改 `config.yaml`：
   ```yaml
   database:
     backend: sqlserver
     sqlserver:
       host: 127.0.0.1
       port: 11433          # docker-compose 映射埠
       user: sa
       password: "YourStrong!Passw0rd"
       database: MemberData
       table: dbo.Members   # 實際資料表名稱
   ```

> 若只有 `.mdf` 沒有 `.ldf`，SQL Server 仍可附加但需額外重建記錄檔；建議向原始端取得完整一組檔案。

### B. Windows 主機（LocalDB / SQL Server Express）

```bat
sqlcmd -S "(localdb)\MSSQLLocalDB" -Q "CREATE DATABASE [MemberData] ON (FILENAME = N'C:\data\YourData.mdf') FOR ATTACH"
```

`config.yaml` 的 `host` / `port` 對應該執行個體即可。

### C. 既有的內部 SQL Server

直接把 `config.yaml` 指向該伺服器並填入 `database` 與 `table`。

## 搜尋欄位對應

系統會自動在目標資料表偵測欄位（比對 `姓名/name`、`身份證/idcard/pid`、`地址/address`、`電話/tel/mobile` 等常見命名，中英文皆可）。若自動判斷不正確，於 `config.yaml` 明確指定：

```yaml
search:
  columns:
    name: 客戶姓名
    idcard: 身分證統一編號
    address: 戶籍地址
    phone: 行動電話
```

## 使用者加入與 TOTP 設定流程（詳細說明）

整個流程分「管理員」與「使用者」兩端，全程**不需要網路**。

### 第 1 步：管理員建立帳號並產生 TOTP 密鑰

在伺服器上執行：

```bash
.venv/bin/python manage.py adduser alice
```

依提示輸入兩次密碼（至少 8 碼）後，畫面會輸出：

```
使用者 alice 已建立。
請將下列密鑰加入離線驗證器 App（Google Authenticator、Aegis、Authy 等）：

  密鑰（Base32）：KRSXG5CTMVRXEZLUON2GC5DFN5ZGSZB5

  otpauth URI（可手動貼上或轉 QR Code）：
  otpauth://totp/MdfQuery:alice?secret=KRSXG5...&issuer=MdfQuery&algorithm=SHA1&digits=6&period=30
```

- **Base32 密鑰**：手動輸入用的字串
- **otpauth URI**：掃描／匯入用，內容與密鑰相同

> 安全提醒：這組密鑰等同使用者的第二組密碼，能產生合法動態碼。請勿透過 Email、群組聊天軟體傳遞；建議當面交付、內線電話口述，或列印後當面轉交並回收銷毀。

### 第 2 步（選配）：離線產生 QR Code

沒有網路也能產生 QR Code。在伺服器或任何離線電腦安裝 `qrencode` 後：

```bash
qrencode -t ANSIUTF8 "otpauth://totp/MdfQuery:alice?secret=..."   # 直接印在終端機
qrencode -o alice-totp.png "otpauth://totp/MdfQuery:alice?secret=..."   # 存成圖檔
```

- 終端機版：請 alice 到伺服器螢幕前直接掃描，不必留存檔案
- 圖檔版：掃描完成後立即刪除

### 第 3 步：使用者將密鑰加入驗證器 App

以 **Google Authenticator** 為例：

| 方式 | 操作 |
|---|---|
| 掃描 QR Code | 開啟 App → 右下「+」→「掃描 QR Code」→ 對準管理員提供的 QR Code → 出現名為 `MdfQuery: alice` 的條目與 6 位數字 |
| 手動輸入 | 開啟 App → 右下「+」→「輸入設定金鑰」→「帳戶」填 `alice`、「金鑰」貼上 Base32 密鑰 → 類型選「時間型（Time-based）」→ 完成 |

其他常見 App（步驟大同小異）：

- **Microsoft Authenticator**：「+」→「其他帳戶」→「或手動輸入代碼」
- **Aegis / Authy**：支援直接匯入 `otpauth://` URI 或手動輸入

新增成功後，App 會顯示一個**每 30 秒更新一次的 6 位數代碼**，旁邊通常有倒數圓圈。

### 第 4 步：首次登入驗證綁定是否成功

1. 開啟查詢系統網頁 → 輸入帳號密碼 → 下一步
2. 打開驗證器 App，讀取目前顯示的 6 位數代碼
3. 在倒數結束前輸入並送出（若剛好跳到下一組，改輸最新一組即可）
4. 成功進入查詢頁 = TOTP 綁定完成；之後每次登入都需要當下最新的動態碼

### 常見問題與維運

| 情境 | 處理方式 |
|---|---|
| 「動態驗證碼錯誤」，確定輸入正確 | 手機時鐘不準。開啟自動日期時間；Google Authenticator：設定 →「時間校正」（同步時間） |
| 提示「已被使用」 | 同一組代碼只能用一次，等 App 跳出下一組再輸入 |
| 換手機 / App 刪除 / 遺失 | 管理員執行 `.venv/bin/python manage.py reset-totp alice`，取得**新密鑰**重新走一次第 2～4 步；舊密鑰立即失效 |
| 忘記密碼 | 管理員先 `reset-totp`（順便解鎖），再刪除重建該帳號（目前版本未提供改密指令，可於 `adduser` 同名覆蓋前先確認設計） |
| 帳號被鎖定 | 連續錯 5 次密碼會鎖 5 分鐘後自動解鎖；急件可由管理員 `reset-totp` 重置失敗計數 |
| 密鑰外流疑慮 | 一律視同洩漏，立即 `reset-totp` |

### 管理工具總覽

```bash
.venv/bin/python manage.py init-db          # 只建立帳號庫
.venv/bin/python manage.py adduser <帳號>    # 新增使用者＋產生 TOTP 密鑰
.venv/bin/python manage.py reset-totp <帳號> # 重設密鑰（舊碼全部失效）
.venv/bin/python manage.py list-users        # 列出所有帳號
.venv/bin/python manage.py seed-demo         # 寫入 SQLite 示範資料
```

## 離線運作說明

- **TOTP 不需要網路**：驗證器 App 與伺服器各自以「共用密鑰 + 目前時間」計算同樣的 6 位數代碼（RFC 6238，每 30 秒更新）。
- 伺服器與手機的**時鐘必須準確**（容許 ±30 秒）；離線主機請確保 RTC 正常或以 NTP 於內網校時。
- 整個系統（登入、驗證、查詢）皆為本機服務，無任何外部 API 呼叫。

## 測試

### 本機測試

```bash
.venv/bin/python -m unittest discover -s tests -p "test_*.py"   # 單元 + E2E + 多格式測試（37 例）
./scripts/smoke_test.sh                                          # 本機 HTTP 全流程煙霧測試（SQLite 示範模式）
.venv/bin/python manage.py detect <檔案>                          # 判別任意資料庫檔案類型
```

### CI：真實 SQL Server + 官方 MDF 整合測試

GitHub Actions 工作流程（`.github/workflows/ci.yml`）每次推送自動執行：

1. 於 runner 啟動真實 **SQL Server 2022** 容器（health check 就緒後才繼續）
2. 下載 Microsoft 官方 [AdventureWorksLT2012 MDF/LDF](https://github.com/Microsoft/sql-server-samples/releases/tag/adventureworks2012) 範例資料檔
3. 將檔案複製進容器並以 `CREATE DATABASE ... FOR ATTACH` 附加 MDF
4. 由附加後的真實資料建立可搜尋的 `dbo.Members` 資料表
5. 執行 `tests/ci_integration.py`：驗證未登入防護、錯誤密碼拒絕、TOTP 正反流程、姓名／身份證／電話搜尋、複合條件 AND 查詢等 11 項情境

## 上線前建議

- 以反向代理（nginx/Caddy）加上 HTTPS，並將 `SESSION_COOKIE_SECURE = True` 加入 `app/__init__.py`
- 更換 Docker `SA_PASSWORD`，勿使用範例值
- 定期備份 `instance/users.db`（遺失等同重建所有帳號）
