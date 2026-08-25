---
name: model-retry-handler
description: 自動處理模型提供商層級的暫時性失敗並重試。Use when a task hits "model provider failed" or "Empty response from model" errors — wait 6 minutes per retry, up to 6 short retries, then loop into a 66-minute long wait until success or manual stop.
metadata:
  version: "1.0.0"
  author: Hermes Agent
  license: MIT
  trigger: 任務中出現 model provider failed、Empty response from model 等錯誤
  tags: reliability,provider,retry,error-handling
---

# Model Retry Handler Skill

## When to Use
Use this skill when a model provider returns transient failures like `model provider failed` or `Empty response from model`. It implements automatic retry with a 6-minute delay, up to 3 attempts, preserving conversation context.

## 觸發條件
- 模型回應出現 `model provider failed`
- 模型回應出現 `Empty response from model`
- 類似的提供商層級錯誤（非提示詞/內容錯誤）

## 處理流程

1. **偵測錯誤** — 在工具結果或模型回應中發現上述關鍵字
2. **記錄錯誤** — 記錄時間、錯誤類型、當前任務上下文
3. **等待 6 分鐘** — 使用非阻塞等待（背景計時）
4. **自動重試** — 以相同提示詞/上下文重新呼叫模型
5. **最多重試 6 次** — 連續失敗 6 次後進入長等待
6. **長等待 66 分鐘** — 6 次失敗後等待 66 分鐘，然後重新開始策略（回到步驟 3）
7. **持續循環** — 直到成功或用戶介入

## 實作細節

### 等待機制
- 不要使用 `sleep` 阻塞主執行緒
- 使用 `cronjob` 排程或背景任務實現延遲重試
- 或在代碼中使用 `asyncio.sleep(360)` / `asyncio.sleep(3960)` 配合非阻塞架構

### 重試策略
```python
SHORT_RETRY_DELAY = 360      # 6 分鐘
LONG_RETRY_DELAY = 3960      # 66 分鐘
MAX_SHORT_RETRIES = 6

async def call_with_retry(prompt, context):
    short_retry_count = 0
    
    while True:  # 無限循環，直到成功或用戶介入
        try:
            result = await call_model(prompt, context)
            if is_provider_error(result):
                raise ProviderError(result)
            return result  # 成功
        except ProviderError as e:
            short_retry_count += 1
            
            if short_retry_count <= MAX_SHORT_RETRIES:
                # 短重試：等待 6 分鐘
                await asyncio.sleep(SHORT_RETRY_DELAY)
                continue
            else:
                # 已達 6 次短重試，進入長等待
                short_retry_count = 0  # 重置計數器
                await asyncio.sleep(LONG_RETRY_DELAY)  # 等待 66 分鐘
                # 長等待後自動回到開頭繼續短重試循環
                continue
```

## 整合點
- Hermes Agent 的模型呼叫鏈路（provider 抽象層）
- 適用於所有 provider（OpenRouter、Anthropic、OpenAI 等）
- 不處理：rate limit（需指數退避）、context length exceeded、內容政策違規

## 驗證方式
1. 模擬 provider 失敗 → 確認 6 分鐘後自動重試
2. 連續 3 次失敗 → 確認停止並通知用戶
3. 成功重試 → 確認任務正常繼續

## 注意事項
- 重試時保持相同的 conversation context
- 避免重複產生副作用（如發送郵件、寫入檔案）——冪等操作才適合重試
- 用戶可透過設定調整 `SHORT_RETRY_DELAY`、`LONG_RETRY_DELAY` 與 `MAX_SHORT_RETRIES`
- 此策略為無限循環，直到成功或用戶手動介入停止
- 長等待（66 分鐘）後會自動重置短重試計數器，重新開始 6 次短重試循環