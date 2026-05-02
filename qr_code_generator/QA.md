# System Design Interview — QR Code Generator

模擬系統設計面試，從高層需求到實作細節的完整問答流程。

---

## 第一階段：需求確認

**Q：請你設計一個動態 QR Code 產生器。在開始之前，你會先問哪些問題來確認需求？**

A：我會先確認功能性需求和非功能性需求。

**功能性：**
- 使用者輸入一個長網址，系統產生短網址和 QR code
- 掃描 QR code 後要能跳轉到原始網址
- QR code 要是「動態的」— 也就是說可以在不換 QR code 的情況下修改目標網址
- 需要軟刪除（token 還在，但跳轉回傳 410）
- 需要過期時間設定
- 需要 scan analytics

**非功能性：**
- Redirect 延遲要極低，使用者掃完不能等
- 系統要能承受大量讀（redirect）、少量寫（create/update）的流量
- Token 要保證唯一性

---

**Q：好。那你估一下規模。假設每天產生 100 萬個新 QR code，redirect 的 read/write 比例大概是多少？**

A：QR code 通常印在實體媒體上，一張貼紙可能被掃幾百次。保守估計 read:write = 100:1。

每天 100 萬次 write，就是 1 億次 redirect read。
換算成 QPS：1 億 / 86400 ≈ **1,150 QPS 讀，12 QPS 寫**。
尖峰時間可能 10x，所以讀要能承受約 **10,000 QPS**。

這個規模下，單靠 DB 扛不住 redirect，一定要加 cache。

---

## 第二階段：高層架構

**Q：畫出你的高層架構，說明主要元件。**

```
Client
  │
  ├─ POST /api/qr/create ──→ App Server ──→ DB (寫)
  │
  └─ GET /r/{token} ────────→ App Server
                                  │
                              Cache (Redis)
                                  │ miss
                                 DB (讀)
```

A：核心元件：
- **App Server**：處理 create、redirect、update、delete
- **Redis**：cache token → original_url 的 mapping，redirect 走 cache-first
- **DB（PostgreSQL）**：持久化所有 mapping、scan events
- **QR Code Image**：可以即時產生（on-the-fly），或 pre-generate 存進 object storage（S3）

---

## 第三階段：資料模型

**Q：DB schema 怎麼設計？**

```sql
url_mappings
  id          BIGINT PK
  token       VARCHAR(8)  UNIQUE  INDEX
  original_url TEXT        NOT NULL
  created_at  TIMESTAMP
  updated_at  TIMESTAMP
  expires_at  TIMESTAMP   NULLABLE
  is_deleted  BOOLEAN     DEFAULT false

scan_events
  id          BIGINT PK
  token       VARCHAR(8)  INDEX(token, scanned_at)
  scanned_at  TIMESTAMP
  ip_address  VARCHAR(45)
  user_agent  VARCHAR(500)
```

A：`token` 加 unique index 是為了 redirect 查詢效率。`scan_events` 的 composite index `(token, scanned_at)` 是為了讓 analytics 按日期 group by 時不做 full scan。

---

## 第四階段：核心流程

**Q：Redirect 的完整流程說一下，要包含 cache miss 的情況。**

```
GET /r/{token}
  │
  ├─ Redis GET token
  │     │
  │   HIT └─ record scan → 302 redirect          ← 快，不碰 DB
  │
  └─ MISS
        ├─ DB query WHERE token = ?
        │
        ├─ Not found ──────────────→ 404
        │
        ├─ is_deleted OR expired ──→ 410 Gone
        │
        └─ Found
              ├─ Redis SET token = original_url
              ├─ record scan
              └─ 302 redirect
```

---

**Q：為什麼用 302 不用 301？**

A：301 是 Permanent redirect，瀏覽器會把結果 cache 在本地，之後直接跳過你的伺服器。這樣你就：
- **收不到 analytics**（scan 沒經過你）
- **改不了目標網址**（cache 在 client 端，你改 DB 沒用）

302 是 Temporary redirect，每次都會回來問你，才能支援動態更新和掃描統計。

---

## 第五階段：Token 設計

**Q：Token 怎麼產生？怎麼避免碰撞？**

A：用 `SHA-256(url + nonce)`，取前幾個 bytes，Base62 encode 成 7 個字元。

Base62 keyspace = 62^7 ≈ **35 億**個 token，碰撞機率低。

但還是要處理碰撞：

```python
for nonce in range(10):
    token = base62(sha256(url + nonce))[:7]
    if not exists_in_db(token):
        return token
raise RuntimeError("max retries exceeded")
```

如果規模更大，可以改成預先產生一批 token 放進 queue（Twitter Snowflake 的概念），完全避免寫入時的碰撞檢查。

---

## 第六階段：Cache 策略

**Q：更新目標網址的時候，cache 怎麼處理？**

A：用的是 **Cache Invalidation**：PATCH 的時候先更新 DB，然後把 Redis 裡的 key 刪掉。下一次 redirect 進來 cache miss，自然會從 DB 拿新的值並重新暖 cache。

另一個選項是 **Write-through**：PATCH 同時寫 DB 和 Redis。但這樣有個問題——如果 DB 寫成功、Redis 寫失敗，兩邊就不一致了。

Invalidation 比較保守，不一致視窗很短，而且邏輯更簡單。

---

**Q：Cache 的 TTL 怎麼設？**

A：要考慮兩種情況：
- **正常 token**：TTL 設長一點，比如 24 小時。因為 redirect 是高頻讀，希望盡量 cache hit。
- **有 expires_at 的 token**：TTL 要設成 `min(24h, expires_at - now)`，過期後 cache 自動消失，不然 cache hit 會繞過過期檢查直接 302。

> ⚠️ 目前這個實作沒有設 TTL，所以過期 token 只有在 cache miss 之後查 DB 才能被攔截。這是一個已知缺陷——應該在 cache set 的時候帶 TTL。

---

## 第七階段：進階問題

**Q：如果 Redis 掛了，系統怎麼辦？**

A：Redis 掛掉 → 所有 redirect 都 cache miss → 打到 DB。

短期可以撐，但如果是 10,000 QPS 全部打到 DB，DB 可能過載。

幾個方向：
1. **Circuit breaker**：偵測到 Redis 不可用，自動降級直接查 DB，同時觸發告警
2. **Redis Sentinel / Cluster**：做 HA，避免單點故障
3. **DB read replica**：DB 本身也要能扛讀流量的增加

---

**Q：404 和 410 的語意差異是什麼？為什麼要區分？**

A：
- **404 Not Found**：這個 token 從來就不存在
- **410 Gone**：這個 token 存在過，但已被刪除或過期

對 SEO 和 crawler 有意義：410 告訴 Google「這頁永久消失了，請從索引中移除」，404 只是「找不到」。

對使用者體驗也有意義：掃到 410 的 QR code，可以顯示「此連結已失效」而不是通用的「找不到頁面」。

---

## 延伸：本實作的已知限制

| 限制 | 原因 | Production 解法 |
|------|------|----------------|
| in-memory dict 無法跨 process 共享 | 每個 process 有自己的 `redirect_cache` | 換成 Redis |
| 過期 token 在 cache hit 時不會被攔截 | Cache 沒有設 TTL | Cache set 時帶 `expires_at - now` 作為 TTL |
| SQLite 不支援高並發寫入 | SQLite 有 write lock | 換成 PostgreSQL |
| 沒有 rate limiting | Create endpoint 可被濫用 | 加 IP-based rate limit |
