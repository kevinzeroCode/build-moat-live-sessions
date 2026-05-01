# QR Code Generator — 設計複習筆記

本文整理了實作過程中討論過的核心設計問題與解答，方便複習。

---

## Q1. 為什麼用 Dynamic QR（短網址）而非 Static QR（直接編原始網址）？

**答：** QR code 一旦印出就無法修改。

| 類型 | QR 編碼的內容 | 能否修改目的地 |
|------|--------------|--------------|
| Static | 原始長網址（直接） | ✗ 印出後無法改 |
| Dynamic | 短網址 token（你控制的） | ✓ 後端隨時可改對應關係 |

**應用：** 這就是為什麼 `PATCH /api/qr/{token}` 能更新目標網址，而 QR code 本體不變。

---

## Q2. 為什麼用 302（Temporary Redirect）而不用 301（Permanent Redirect）？

| Code | 瀏覽器行為 | 適合場景 |
|------|-----------|---------|
| **301** 永久 | 快取結果，下次直接跳過你的 server | 目的地永遠不變 |
| **302** 暫時 | 每次都回來問你的 server | 需要追蹤、可修改、可刪除 |

**答：** 選 302，因為 QR code 擁有者可以刪除或修改對應關係，必須確保每次掃描都取得最新狀態。若用 301，瀏覽器快取後就算你刪了 QR code，使用者還是會被導過去。

---

## Q3. Token 怎麼產生？碰撞了怎麼辦？

流程：
1. `SHA-256(url + nonce)` → 取得固定長度 digest
2. `Base62 encode` → 轉成可讀字串 `[0-9A-Za-z]`
3. 取前 N 個字元當 token（這個系統用 7 個字元）
4. 查 DB 是否已存在 → 碰撞就換 nonce 重試（最多 `MAX_RETRIES` 次）
5. DB 的 `token` 欄位加 `UNIQUE` 約束，雙重保護

**碰撞機率：** Base62 的 7 字元 key space = 62⁷ ≈ 35 億。隨著 token 數量增加，碰撞機率依生日悖論上升，但 retry 機制可以處理。

---

## Q4. redirect() 的 Cache-First 策略是什麼？

redirect 是系統最熱的路徑（每次掃 QR 都打），所以用 cache 減少 DB 壓力。

```
收到 token
    │
    ▼
┌─────────────────┐
│  redirect_cache │──── Hit ───→ _record_scan() → 302 RedirectResponse
│  (記憶體 dict)  │
└────────┬────────┘
         │ Miss
         ▼
    查 DB (UrlMapping)
         │
    ┌────┴──────────────┐
    │                   │
  找不到            找到了
    │            ┌──────┴──────┐
   404      is_deleted       正常
           或已過期            │
              │          暖 cache
             410         _record_scan()
                            302
```

---

## Q5. 404 vs 410 的語意差別

| Code | 意思 | QR code 場景 |
|------|------|-------------|
| **404** Not Found | 這個資源從來不存在（或不知道是否存在） | token 在 DB 完全找不到 |
| **410** Gone | 這個資源曾經存在，但已被永久移除 | `is_deleted=True` 或 `expires_at` 已過期 |

對使用者體驗很重要：
- `410` 告訴掃碼者「這個 QR code 曾經有效，但已失效」
- `404` 告訴掃碼者「這個 token 根本不認識」（可能是偽造或手誤）

---

## Q6. Cache Invalidation（快取失效）在哪裡發生？

| 操作 | 需要 invalidate 嗎？ | 原因 |
|------|---------------------|------|
| **Create** | 否（直接暖 cache） | 新建立後立刻塞入 cache |
| **Update URL** | ✓ `redirect_cache.pop(token, None)` | 目的地改了，舊 cache 值已過時 |
| **Update expires_at** | ✓ `redirect_cache.pop(token, None)` | 可能已過期，不能繼續 serve |
| **Delete** | ✓ `redirect_cache.pop(token, None)` | 已刪除不應繼續 redirect |

---

## Q7. redirect() 完整實作

```python
@router.get("/r/{token}")
def redirect(token: str, request: Request, db: Session = Depends(get_db)):
    # Step 1: cache hit
    if token in redirect_cache:
        _record_scan(token, request, db)
        return RedirectResponse(redirect_cache[token], status_code=302)

    # Step 2: cache miss → 查 DB
    mapping = db.query(UrlMapping).filter(UrlMapping.token == token).first()

    # Step 3: 不存在 → 404
    if mapping is None:
        raise HTTPException(status_code=404, detail="Not Found")

    # Step 4: 已刪除或過期 → 410
    if mapping.is_deleted:
        raise HTTPException(status_code=410, detail="Gone")

    if mapping.expires_at is not None and mapping.expires_at < datetime.utcnow():
        raise HTTPException(status_code=410, detail="Gone")

    # Step 5: 正常 → 暖 cache、記錄掃描、302
    redirect_cache[token] = mapping.original_url
    _record_scan(token, request, db)
    return RedirectResponse(mapping.original_url, status_code=302)
```

### 為什麼不用 `_get_mapping_or_404()` 這個 helper？

因為那個 helper 對 `is_deleted=True` 也回 404，無法區分「從未存在」vs「已刪除」，無法回 410。redirect() 需要自己查 raw DB。

---

## 驗證測試（curl）

```bash
cd scaffold
uvicorn app.main:app --reload

# 建立
TOKEN=$(curl -s -X POST http://localhost:8000/api/qr/create \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}' | python -c "import sys,json; print(json.load(sys.stdin)['token'])")

curl -o /dev/null -w "%{http_code}" http://localhost:8000/r/$TOKEN          # → 302
curl -X PATCH http://localhost:8000/api/qr/$TOKEN -H "Content-Type: application/json" -d '{"url":"https://new-url.com"}'
curl -o /dev/null -w "%{redirect_url}" http://localhost:8000/r/$TOKEN       # → https://new-url.com
curl -X DELETE http://localhost:8000/api/qr/$TOKEN
curl -o /dev/null -w "%{http_code}" http://localhost:8000/r/$TOKEN          # → 410
curl -o /dev/null -w "%{http_code}" http://localhost:8000/r/INVALID         # → 404
```
