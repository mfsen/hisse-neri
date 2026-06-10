# BIST Sinyal Motoru — Ajan Entegrasyon Kılavuzu

## Başlatma

### Docker ile (önerilen)
```bash
docker compose up --build
# → http://localhost:5000  (web dashboard)
# → http://localhost:5000/api/...  (REST API)
```

### Direkt Python ile
```bash
pip install -r requirements.txt
python app.py
# → http://localhost:5000
```

---

## Ajan için sistem promptu — REST API versiyonu (kopyala-yapıştır)

Ajan HTTP araçları kullanıyorsa (Claude API tool_use, n8n, LangChain vb.) bu promptu ver:

```
Sen bir BIST teknik analiz asistanısın.
Sinyal motoruna http://localhost:5000 adresinden erişiyorsun.

Araçlar (HTTP GET):
- GET /api/scan?index=30        → Günlük tarama (~30sn, kapanış sonrası çalıştır)
- GET /api/monitor?force=true   → Anlık AL/SAT sinyalleri
- GET /api/watchlist            → Son scan'in aday listesi
- GET /api/positions            → Açık pozisyonlar
- GET /health                   → Servis ayakta mı?

Çalışma kuralları:
1. Kullanıcı "sinyal ver", "ne alayım", "durum ne" dediğinde ÖNCE
   GET /api/monitor?force=true çağır, dönen JSON'u yorumla.
2. JSON'daki "actionable" listesini ön plana çıkar (AL / SAT sinyalleri).
3. "signals" listesindeki BEKLE/TUT/İPTAL'leri de özetle.
4. Her sinyalin yanına stop ve hedef fiyatını yaz.
5. Asla "kesin kazanır" deme — risk uyarısını her cevaba ekle.
6. Kullanıcı "tara" veya "yenile" derse GET /api/scan?index=30 çağır,
   sonra GET /api/monitor?force=true çağır.

Çıktı formatı:
## 🔴 SAT / ✅ AL (varsa)
- SEMBOL — fiyat ₺ | Stop: X₺ | Hedef: Y₺ | R/R: Z | Neden: ...

## 🟡 İzlemede (BEKLE/TUT)
- SEMBOL — fiyat ₺ → giriş: X₺ bekle

## ℹ️ Durum
- Açık pozisyon: N | Tarih: ...
- ⚠️ Yatırım tavsiyesi değildir.
```

---

## Ajan için sistem promptu — terminal versiyonu (kopyala-yapıştır)

Ajan doğrudan komut çalıştırabiliyorsa (Claude Code gibi) bu promptu ver:

```
Sen bir BIST teknik analiz asistanısın.

Araçlar:
- `python signal_engine.py scan --index 30`   → Günlük tarama (seans kapanışı sonrası çalıştır)
- `python signal_engine.py monitor --force`   → Anlık sinyal sorgulama (seans içi her ~10dk)

Çalışma kuralları:
1. Kullanıcı "sinyal ver", "ne alayım", "durum ne" dediğinde ÖNCE monitor komutunu çalıştır,
   sonra gelen JSON'u yorumla.
2. JSON'daki "actionable" listesindeki AL/SAT sinyallerini ön plana çıkar.
3. "signals" listesindeki BEKLE/TUT/İPTAL'leri de özetle.
4. Her sinyalin yanına stop ve hedef fiyatını yaz.
5. Asla "kesin kazanır" deme — risk uyarısını her cevaba ekle.
6. Kullanıcı "tara" veya "yenile" derse scan komutunu çalıştır, sonra monitor çalıştır.

Çıktı formatı:
## 🔴 SAT / ✅ AL (varsa)
- SEMBOL — fiyat ₺ | Stop: X₺ | Hedef: Y₺ | R/R: Z | Neden: ...

## 🟡 İzlemede (BEKLE/TUT)
- SEMBOL — fiyat ₺ → giriş: X₺ bekle

## ℹ️ Durum
- Açık pozisyon: N | Tarih: ...
- ⚠️ Yatırım tavsiyesi değildir.
```

---

## REST API endpoint'leri — özet

| Endpoint | Ne zaman | Açıklama |
|---|---|---|
| `GET /api/scan?index=30` | Günde **1 kez** — saat ~18:20 (kapanış sonrası) | Günlük göstergelerle adayları seçer, `watchlist.json` yazar |
| `GET /api/monitor` | Seans içi **her ~10 dk** (10:00–18:10) | Canlı fiyatı seviyelere karşı izler, AL/SAT/BEKLE verir |
| `GET /api/monitor?force=true` | Her zaman (test / seans dışı sorgu) | Piyasa kapalı uyarısını atlar |
| `GET /api/watchlist` | İstediğinde | Son scan'in ham aday listesi |
| `GET /api/positions` | İstediğinde | Açık pozisyonların tüm detayı |
| `POST /api/positions/<SEMBOL>/close` | Manuel çıkış | Pozisyonu elle kapat |
| `GET /health` | Her zaman | Servis ayakta mı kontrolü |
| `GET /api/scan?index=50` | Daha geniş evren | Katılım 50 hisse tarar |

## Terminal komutları — özet

| Komut | Ne zaman | Açıklama |
|---|---|---|
| `python signal_engine.py scan --index 30` | Günde **1 kez** — saat ~18:20 (kapanış sonrası) | Günlük göstergelerle adayları seçer, `watchlist.json` yazar |
| `python signal_engine.py monitor` | Seans içi **her ~10 dk** (10:00–18:10) | Canlı fiyatı seviyelere karşı izler, AL/SAT/BEKLE verir |
| `python signal_engine.py monitor --force` | Her zaman (test / seans dışı sorgu) | Piyasa kapalı uyarısını atlar |
| `python signal_engine.py scan --index 50` | Daha geniş evren için | Katılım 50 hisse tarar |

---

## JSON çıktısı — anahtar alanlar

### monitor çıktısı
```json
{
  "actionable": [          // ← AJAN BURAYI OKUR (AL / SAT)
    {
      "symbol": "KORDS",
      "action": "AL",      // AL | SAT | TUT | BEKLE | İPTAL | VERİ_YOK
      "price": 75.50,      // anlık fiyat
      "stop": 64.00,       // zararı kes seviyesi
      "target": 94.55,     // kâr al seviyesi
      "rr": 1.73,          // risk/ödül oranı (dinamik)
      "reason": "...",
      "state": "OPEN"
    }
  ],
  "signals": [...],        // tüm izleme listesi (BEKLE/TUT dahil)
  "open_positions": 1      // kaç açık pozisyon var
}
```

### scan çıktısı
```json
{
  "watchlist": [           // bugünün adayları
    {
      "symbol": "KORDS",
      "score": 30,
      "strategy": "Trend Takibi",
      "entry": 75.80,
      "stop": 64.00,
      "target": 94.55,
      "rr": 1.59,
      "reasons": [...],
      "risks": [...]
    }
  ]
}
```

---

## Durum makinesi (bir hissenin hayat döngüsü)

```
WATCH → (fiyat giriş bölgesine gelir) → OPEN (AL sinyali)
OPEN  → (fiyat stop'a gelir)          → CLOSED-stop (SAT sinyali)
OPEN  → (fiyat hedefe gelir)          → CLOSED-target (SAT sinyali)
WATCH → (fiyat stop altına düşer)     → İPTAL (kurulum geçersiz)
WATCH → (fiyat girişi >%3 aşar)       → İPTAL (kaçırıldı, kovalaşma)
```

---

## Önemli uyarılar

- **Sinyaller emir değildir.** Giriş bölgesi, stop ve hedef ÖNERIDIR.
- Yahoo Finance BIST verisi ~15dk gecikmeli olabilir; bedelli/bedelsiz sermaye artırımı düzeltmeleri kusurlu olabilir.
- Portföyün max **%5'ini** tek hisseye koy.
- **Scan'den sonra mutlaka monitor'ü çalıştır** — sadece scan yeterli değil.
- Skor **30-35 altı** adaylar filtrelenir; bu günkü piyasa koşulunda kurulum gücü düşük demektir.
- **Bu araç yatırım tavsiyesi değildir.**
