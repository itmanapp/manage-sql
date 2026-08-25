---
name: preflight-check
description: 在動手改程式碼前，先查官方文件與 changelog 確認套件/服務最新版本、breaking changes 與 deprecation。Use before any coding task that involves specific packages, SDKs, CLIs, cloud services or frameworks (e.g. upgrading Next.js, integrating Stripe API, Terraform config).
---

# Preflight Check

## 目的
在動手改程式碼或設定之前，先確認要用到的套件/服務目前「官方最新狀態」——版本號、breaking changes、deprecation——避免依賴過期知識給出建議，導致使用者事後要重工，或改出一個已經被官方棄用的寫法。

**觸發時機**：使用者訊息提到具體的套件名稱、SDK、雲端服務或框架時（例如「幫我升級 Next.js」「串接 Stripe API」「修這段 Terraform 設定」「用 LangChain 串起來」），即使沒有明確要求檢查版本，也應該主動觸發。同一次對話中已經查過的工具不用重複查。

## 這個技能做不到的事（先說清楚，避免誤用）
- **無法保證「每次新對話都自動執行」**。技能是依照使用者訊息內容、由模型自行判斷是否觸發，不是系統層級的強制 hook。如果你在 **Claude Code** 裡使用，想要更強的保證，可以搭配文末「選用：Claude Code SessionStart Hook」。
- **無法讀取需要登入的頁面**（私有文件、付費 changelog）。
- **搜尋結果只是摘要片段，不是完整頁面**——所以查完一定要接著讀完整頁面內容再下結論，不要只憑搜尋摘要判斷版本或變更細節。

## 步驟

### 1. 辨識目標服務／工具
從使用者最新訊息與任務內容中，列出會實際用到的：
- 套件/函式庫（如 pandas、langchain、stripe-node）
- CLI 工具（如 terraform、aws-cli、vercel）
- 雲端服務/API（如 AWS Lambda、Stripe API、OpenAI API）
- 框架（如 Next.js、Django、React）

排除以下，不用查：
- 通用語言本身、通用語言的核心指令（Python、Node.js、Git 的 add/commit/push 等）
- 已知極穩定、變更頻率極低的基礎工具（ls、cat、grep、curl）
- 這次對話裡稍早已經查過的工具，直接沿用先前的查詢結果

如果列出來的目標超過 4-5 個，優先查使用者明確要修改/新增/升級的那幾個，其餘可以先跳過或標成低優先。

### 2. 查詢官方資訊
對每個目標，用**簡短、分開**的查詢（web_search / web_extract / curl 皆可），不要把多個工具或多個條件塞進同一個搜尋字串：

1. `{工具名} latest version` 或 `{工具名} changelog`
2. 如果第一步發現版本落差大，再查：`{工具名} breaking changes {年份}`
3. 有需要時：`{工具名} migration guide`

拿到搜尋結果後，打開**官方來源**讀完整內容，不要只看搜尋摘要就下結論。信任順序：
1. 官方文件 / Release Notes / GitHub CHANGELOG
2. 官方部落格
3. 盡量避免只靠第三方教學文章判斷版本資訊

注意：本機 web_extract 僅支援搜尋、抓頁面常失敗；改用 `terminal curl + python 解析 HTML` 讀官方頁面。

摘要重點時用自己的話重寫（版本號、發布日期、breaking changes、deprecation、migration guide 連結），並附上來源連結，不要逐句照抄官方文件內容。

### 3. 比對本地版本
若專案中有 lockfile（package-lock.json / pnpm-lock.yaml / poetry.lock / requirements.txt / go.sum 等）或設定檔（package.json / pyproject.toml / Cargo.toml），讀取目前鎖定/宣告的版本，跟步驟 2 查到的最新穩定版比對，標記：
- `目前 < 最新`
- `目前 == 最新`
- `目前 > 最新`（可能在用 pre-release/nightly，特別留意）
- 找不到本地版本資訊 → 標記「無法比對」，不要用猜的

### 4. 輸出 Preflight Report
開始實際任務前，先用這個格式在回覆裡呈現（不用另外存檔）：

```markdown
## 🔎 Preflight Report

整體狀態：⚠️ 需注意 / ✅ 可直接開始 / ❓ 部分資訊未知

| 工具/服務 | 目前版本 | 最新穩定版 | 狀態 | Breaking Changes |
|---|---|---|---|---|
| 範例套件 | 2.3.0 | 2.6.1 | ⚠️ 落後 | 有，見下方 |

### 摘要（自己的話，附來源連結）
- **範例套件**：...

### 建議
- ...
```

- 有 breaking change 且會影響目前用法 → 建議先讀 migration guide 再動手
- 版本落後幅度大（差超過 2 個 minor，或差了一個 major）→ 建議考慮先升級再開發
- 查不到官方資訊 → 標 ❓，誠實告知「這部分沒查到」，**不要編造**
- 全部正常 → 一句話帶過「已核對，可直接開始」

### 5. 接著進行原本的任務
Preflight Report 是提醒，不是關卡。查完就直接接續原本要做的事——除非發現重大 breaking change 且原做法明顯會壞掉，才先跟使用者確認再動手。

## 效能考量
- 同一次對話裡，同一個工具只查一次
- 每個工具讀 2-3 個來源就夠
- 使用者明確說「不用查了直接改」時，跳過這個流程

## 可調整的預設值
這是文字型技能，不是腳本；門檻直接在對話裡調整：
- 版本落後幾個 minor 才建議升級：預設 2
- 每個工具查每個工具查幾個來源：預設 2-3
- 跳過：ls、cat、grep、curl、git core 指令、python/node/npm 本身

---

## 選用：Claude Code SessionStart Hook（更強的提醒，但不是強制執行）
在 `.claude/settings.json` 或 `~/.claude/settings.json` 加 `SessionStart` hook，每次新對話注入提醒文字（hook 無法保證真的執行成功）：

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "echo '提醒：這次工作階段若會用到特定套件、框架、雲端服務或 CLI 工具，請先使用 preflight-check 技能查詢官方最新版本與 breaking changes，再開始修改。'"
          }
        ]
      }
    ]
  }
}
```

SessionStart hook 每次 session 啟動都會跑，指令要盡量快。
