"""
Flask REST API + web dashboard.

Endpoint'ler (ajan bu URL'leri çağırır):
  GET  /api/scan?index=30        → günlük tarama (watchlist günceller)
  GET  /api/monitor              → anlık AL/SAT sinyalleri
  GET  /api/watchlist            → son scan sonucu
  GET  /api/positions            → açık pozisyonlar
  POST /api/positions/<sym>/close → pozisyonu manuel kapat
  GET  /health                   → servis sağlık kontrolü
  GET  /                         → web dashboard
"""

import sys, os, json, threading
from datetime import datetime
from flask import Flask, jsonify, request, render_template_string

sys.path.insert(0, os.path.dirname(__file__))
from signal_engine import (
    run_scan, run_monitor,
    load_json, WATCHLIST_FILE, POSITIONS_FILE,
    now_iso, INDEX_MAP
)

app = Flask(__name__)
_scan_lock = threading.Lock()   # aynı anda iki scan önlenir

# ------------------------------------------------------------------ #
#  Yardımcı
# ------------------------------------------------------------------ #
class FakeArgs:
    """run_scan / run_monitor argparse namespace yerine."""
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _capture_emit(fn, args):
    """run_scan/run_monitor'ün emit() çağrısını yakalar (stdout yerine)."""
    captured = {}
    original_print = __builtins__.__dict__["print"] if isinstance(__builtins__, dict) else print

    import builtins
    results = []

    orig = builtins.print
    def fake_print(*a, **kw):
        # sadece stdout'a giden çağrıyı yakala (stderr=sys.stderr olanları değil)
        if kw.get("file") is sys.stderr:
            orig(*a, **kw)
        else:
            results.append(a[0] if a else "")
    builtins.print = fake_print
    try:
        fn(args)
    finally:
        builtins.print = orig

    for r in results:
        try:
            return json.loads(r)
        except Exception:
            pass
    return {}


# ------------------------------------------------------------------ #
#  API endpoint'leri
# ------------------------------------------------------------------ #
@app.route("/health")
def health():
    return jsonify({"status": "ok", "time": now_iso()})


@app.route("/api/scan")
def api_scan():
    index = request.args.get("index", "30")
    if index not in INDEX_MAP:
        return jsonify({"error": "index must be 30, 50 or 100"}), 400
    args = FakeArgs(
        index=index, period=365,
        min_score=30, min_rr=1.0, max_positions=8
    )
    with _scan_lock:
        result = _capture_emit(run_scan, args)
    return jsonify(result)


@app.route("/api/monitor")
def api_monitor():
    force = request.args.get("force", "false").lower() == "true"
    args = FakeArgs(index="30", buy_tol=0.5, missed_tol=3.0, force=force)
    result = _capture_emit(run_monitor, args)
    return jsonify(result)


@app.route("/api/watchlist")
def api_watchlist():
    wl = load_json(WATCHLIST_FILE, {"watchlist": [], "note": "Henüz scan yapılmadı."})
    return jsonify(wl)


@app.route("/api/positions")
def api_positions():
    pos = load_json(POSITIONS_FILE, {})
    return jsonify(pos)


@app.route("/api/positions/<sym>/close", methods=["POST"])
def api_close_position(sym):
    yf_sym = sym.upper() + ".IS"
    pos = load_json(POSITIONS_FILE, {})
    if yf_sym not in pos:
        return jsonify({"error": f"{sym} pozisyonu bulunamadı"}), 404
    pos[yf_sym]["state"] = "CLOSED"
    pos[yf_sym]["closed_at"] = now_iso()
    pos[yf_sym]["exit_reason"] = "manual"
    from signal_engine import save_json
    save_json(POSITIONS_FILE, pos)
    return jsonify({"ok": True, "symbol": sym, "closed_at": pos[yf_sym]["closed_at"]})


# ------------------------------------------------------------------ #
#  Web dashboard (tek HTML sayfası, harici bağımlılık yok)
# ------------------------------------------------------------------ #
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>BIST Katılım — Sinyal Motoru</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Segoe UI',sans-serif;background:#0f1117;color:#e0e0e0;min-height:100vh}
  header{background:#1a1d2e;border-bottom:1px solid #2a2d3e;padding:16px 24px;display:flex;align-items:center;gap:16px}
  header h1{font-size:1.1rem;color:#60c8ff}
  header .badge{background:#2a2d3e;border-radius:6px;padding:4px 10px;font-size:.75rem;color:#aaa}
  .status-dot{width:10px;height:10px;border-radius:50%;background:#555;display:inline-block;margin-right:6px}
  .status-dot.green{background:#22c55e;box-shadow:0 0 6px #22c55e}
  .status-dot.red{background:#ef4444}
  main{padding:24px;max-width:1100px;margin:0 auto}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin-bottom:24px}
  .card{background:#1a1d2e;border:1px solid #2a2d3e;border-radius:10px;padding:16px}
  .card h3{font-size:.7rem;color:#888;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px}
  .card .val{font-size:1.6rem;font-weight:700}
  .green{color:#22c55e}.red{color:#ef4444}.yellow{color:#f59e0b}.cyan{color:#22d3ee}
  .btn{display:inline-flex;align-items:center;gap:6px;padding:8px 16px;border-radius:7px;border:none;cursor:pointer;font-size:.85rem;font-weight:600;transition:.2s}
  .btn-blue{background:#2563eb;color:#fff}.btn-blue:hover{background:#1d4ed8}
  .btn-green{background:#16a34a;color:#fff}.btn-green:hover{background:#15803d}
  .btn-red{background:#dc2626;color:#fff}.btn-red:hover{background:#b91c1c}
  .btn:disabled{opacity:.4;cursor:not-allowed}
  .actions{display:flex;gap:10px;margin-bottom:24px;flex-wrap:wrap}
  table{width:100%;border-collapse:collapse;font-size:.85rem}
  th{background:#12151f;color:#888;font-weight:600;padding:10px 12px;text-align:left;font-size:.72rem;text-transform:uppercase;letter-spacing:.04em}
  td{padding:10px 12px;border-bottom:1px solid #1e2130}
  tr:hover td{background:#1e2130}
  .pill{display:inline-block;padding:2px 8px;border-radius:20px;font-size:.72rem;font-weight:700}
  .pill-al{background:#15803d22;color:#22c55e;border:1px solid #22c55e55}
  .pill-sat{background:#dc262622;color:#ef4444;border:1px solid #ef444455}
  .pill-bekle{background:#f59e0b22;color:#f59e0b;border:1px solid #f59e0b55}
  .pill-tut{background:#2563eb22;color:#60a5fa;border:1px solid #60a5fa55}
  .pill-iptal{background:#6b728022;color:#9ca3af;border:1px solid #9ca3af55}
  .section{background:#1a1d2e;border:1px solid #2a2d3e;border-radius:10px;padding:20px;margin-bottom:20px}
  .section h2{font-size:.85rem;color:#60c8ff;margin-bottom:16px;font-weight:600;text-transform:uppercase;letter-spacing:.06em}
  .spinner{display:none;width:16px;height:16px;border:2px solid #ffffff44;border-top-color:#fff;border-radius:50%;animation:spin .6s linear infinite}
  @keyframes spin{to{transform:rotate(360deg)}}
  .loading .spinner{display:inline-block}
  .timestamp{color:#555;font-size:.75rem}
  .disclaimer{color:#555;font-size:.72rem;margin-top:24px;text-align:center}
  .empty{color:#555;font-size:.85rem;padding:16px 0}
  #toast{position:fixed;bottom:24px;right:24px;background:#1e2130;border:1px solid #2a2d3e;border-radius:10px;padding:12px 20px;font-size:.85rem;opacity:0;transition:.3s;pointer-events:none}
  #toast.show{opacity:1}
</style>
</head>
<body>
<header>
  <span class="status-dot" id="mktDot"></span>
  <h1>BIST Katılım — Sinyal Motoru</h1>
  <span class="badge" id="lastUpdate">—</span>
  <span class="badge" id="mktStatus">Kontrol ediliyor...</span>
</header>
<main>
  <div class="grid">
    <div class="card"><h3>Açık Pozisyon</h3><div class="val cyan" id="cntOpen">—</div></div>
    <div class="card"><h3>Bugünkü Aday</h3><div class="val yellow" id="cntWatch">—</div></div>
    <div class="card"><h3>AL Sinyali</h3><div class="val green" id="cntBuy">—</div></div>
    <div class="card"><h3>SAT Sinyali</h3><div class="val red" id="cntSell">—</div></div>
  </div>

  <div class="actions">
    <button class="btn btn-green" id="btnScan" onclick="doScan()">
      <span class="spinner" id="spScan"></span> Tara (scan)
    </button>
    <button class="btn btn-blue" id="btnMon" onclick="doMonitor()">
      <span class="spinner" id="spMon"></span> Sinyalleri Getir
    </button>
  </div>

  <div class="section">
    <h2>Anlık Sinyaller</h2>
    <div id="sigTable"><div class="empty">Henüz sorgulanmadı — "Sinyalleri Getir" butonuna tıkla.</div></div>
  </div>

  <div class="section">
    <h2>İzleme Listesi (son scan)</h2>
    <div id="wlTable"><div class="empty">Henüz scan yapılmadı.</div></div>
  </div>

  <p class="disclaimer">⚠️ Yatırım tavsiyesi değildir. Yahoo Finance verisi ~15dk gecikmeli olabilir. Risk yönetiminizi kendiniz yapın.</p>
</main>
<div id="toast"></div>

<script>
const actionColor = {AL:"al",SAT:"sat",BEKLE:"bekle",TUT:"tut","İPTAL":"iptal","VERİ_YOK":"iptal"};
const actionTR = {AL:"✅ AL",SAT:"🔴 SAT",BEKLE:"🟡 BEKLE",TUT:"🔵 TUT","İPTAL":"⛔ İPTAL","VERİ_YOK":"❓ VERİ YOK"};

function toast(msg,ms=2500){
  const t=document.getElementById("toast");
  t.textContent=msg; t.classList.add("show");
  setTimeout(()=>t.classList.remove("show"),ms);
}

function setLoading(id,on){
  const btn=document.getElementById("btn"+id);
  const sp=document.getElementById("sp"+id);
  if(btn)btn.disabled=on;
  if(sp)sp.style.display=on?"inline-block":"none";
}

async function doScan(){
  setLoading("Scan",true);
  toast("Tarama başladı, ~30 sn sürebilir…",8000);
  try{
    const r=await fetch("/api/scan?index=30");
    const d=await r.json();
    document.getElementById("cntWatch").textContent=d.candidate_count??0;
    toast(`Tarama tamamlandı — ${d.candidate_count??0} aday bulundu.`);
    loadWatchlist();
    doMonitor();
  }catch(e){toast("Scan hatası: "+e);}
  finally{setLoading("Scan",false);}
}

async function doMonitor(){
  setLoading("Mon",true);
  try{
    const r=await fetch("/api/monitor?force=true");
    const d=await r.json();
    const sigs=d.signals??[];
    document.getElementById("cntOpen").textContent=d.open_positions??0;
    document.getElementById("cntBuy").textContent=(d.actionable??[]).filter(s=>s.action==="AL").length;
    document.getElementById("cntSell").textContent=(d.actionable??[]).filter(s=>s.action==="SAT").length;
    document.getElementById("lastUpdate").textContent=d.generated_at?d.generated_at.slice(11,19)+" güncel":"—";
    const dot=document.getElementById("mktDot");
    const ms=document.getElementById("mktStatus");
    dot.className="status-dot "+(d.market_open?"green":"red");
    ms.textContent=d.market_open?"Piyasa Açık":"Piyasa Kapalı";

    if(!sigs.length){
      document.getElementById("sigTable").innerHTML='<div class="empty">İzleme listesi boş — önce scan yap.</div>';
      return;
    }
    let html='<table><thead><tr><th>Hisse</th><th>Aksiyon</th><th>Fiyat</th><th>Giriş</th><th>Stop</th><th>Hedef</th><th>R/R</th><th>Durum</th><th>Neden</th></tr></thead><tbody>';
    for(const s of sigs){
      const cls=actionColor[s.action]||"iptal";
      const act=actionTR[s.action]||s.action;
      const pnl=s.unrealized_pct!=null?`<span class="${s.unrealized_pct>=0?"green":"red"}">${s.unrealized_pct>=0?"+":""}${s.unrealized_pct.toFixed(1)}%</span>`:"—";
      html+=`<tr>
        <td><b>${s.symbol}</b></td>
        <td><span class="pill pill-${cls}">${act}</span></td>
        <td>${s.price??""}</td>
        <td>${s.entry?s.entry.toFixed(2):s.fill?s.fill.toFixed(2):"—"}</td>
        <td class="red">${s.stop?s.stop.toFixed(2):"—"}</td>
        <td class="green">${s.target?s.target.toFixed(2):"—"}</td>
        <td>${s.rr?s.rr.toFixed(2):"—"}</td>
        <td>${pnl}</td>
        <td style="color:#888;font-size:.78rem">${s.reason??""}</td>
      </tr>`;
    }
    html+="</tbody></table>";
    document.getElementById("sigTable").innerHTML=html;
  }catch(e){toast("Monitor hatası: "+e);}
  finally{setLoading("Mon",false);}
}

async function loadWatchlist(){
  try{
    const r=await fetch("/api/watchlist");
    const d=await r.json();
    const wl=d.watchlist??[];
    if(!wl.length){document.getElementById("wlTable").innerHTML='<div class="empty">'+( d.note||"Henüz scan yapılmadı.")+'</div>';return;}
    let html='<table><thead><tr><th>Hisse</th><th>Strateji</th><th>Skor</th><th>Giriş</th><th>Stop</th><th>Hedef</th><th>R/R</th><th>RSI</th><th>Nedenler</th></tr></thead><tbody>';
    for(const w of wl){
      html+=`<tr>
        <td><b>${w.symbol}</b><br><span style="color:#666;font-size:.75rem">${w.name}</span></td>
        <td>${w.strategy}</td>
        <td class="${w.score>=50?"green":w.score>=35?"yellow":"red"}">${w.score}</td>
        <td>${w.entry.toFixed(2)}</td>
        <td class="red">${w.stop.toFixed(2)}</td>
        <td class="green">${w.target.toFixed(2)}</td>
        <td>${w.rr.toFixed(2)}</td>
        <td>${w.rsi}</td>
        <td style="color:#888;font-size:.78rem">${(w.reasons||[]).join(" · ")}</td>
      </tr>`;
    }
    html+="</tbody></table>";
    document.getElementById("wlTable").innerHTML=html;
  }catch(e){}
}

// Sayfa açıldığında watchlist'i yükle ve monitor çalıştır
window.onload=()=>{loadWatchlist();doMonitor();};
// Her 10 dakikada otomatik yenile
setInterval(doMonitor, 10*60*1000);
</script>
</body>
</html>"""


@app.route("/")
def dashboard():
    return render_template_string(DASHBOARD_HTML)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
