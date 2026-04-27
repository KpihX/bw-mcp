import http.server
import socketserver
import threading
import json
import uuid
import webbrowser
import html
import time
import ssl
import os
import subprocess
import tempfile
import ipaddress
from typing import Optional, Dict, Any
from .config import HITL_HOST, HITL_PORT, HITL_AUTO_OPEN

# Global state for the temporary HITL server
_hitl_request_data = None
_hitl_response = None
_hitl_token = None
_hitl_server = None
_custom_get_handler = None
_custom_post_handler = None

def _build_subject_alt_names(host: str) -> list[str]:
    entries = ["DNS:localhost", "IP:127.0.0.1"]
    candidate = (host or "").strip()
    if candidate and candidate not in {"localhost", "127.0.0.1", "0.0.0.0"}:
        try:
            ipaddress.ip_address(candidate)
            entries.append(f"IP:{candidate}")
        except ValueError:
            entries.append(f"DNS:{candidate}")
    return entries


def _build_openssl_config(host: str) -> str:
    san_entries = ", ".join(_build_subject_alt_names(host))
    return f"""
[req]
default_bits = 2048
prompt = no
default_md = sha256
distinguished_name = dn
x509_extensions = v3_req

[dn]
CN = localhost

[v3_req]
subjectAltName = {san_entries}
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
basicConstraints = CA:FALSE
"""


def _generate_self_signed_cert(host: str = HITL_HOST):
    """Generates a temporary self-signed certificate bundle in RAM-only storage."""
    cert_dir = "/dev/shm" if os.path.exists("/dev/shm") else tempfile.gettempdir()
    temp_dir = tempfile.mkdtemp(prefix="bw_proxy_tls_", dir=cert_dir)
    cert_path = os.path.join(temp_dir, "cert.pem")
    key_path = os.path.join(temp_dir, "key.pem")
    bundle_path = os.path.join(temp_dir, "bundle.pem")
    config_path = os.path.join(temp_dir, "openssl.cnf")

    with open(config_path, "w", encoding="utf-8") as f:
        f.write(_build_openssl_config(host))

    cmd = [
        "openssl", "req", "-x509", "-nodes", "-newkey", "rsa:2048",
        "-keyout", key_path, "-out", cert_path, "-days", "1",
        "-config", config_path, "-extensions", "v3_req"
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        with open(bundle_path, "wb") as bundle, open(key_path, "rb") as key_file, open(cert_path, "rb") as cert_file:
            bundle.write(key_file.read())
            bundle.write(cert_file.read())
        return bundle_path, [bundle_path, key_path, cert_path, config_path], temp_dir
    except Exception as e:
        print(f"⚠️ Failed to generate SSL cert: {e}")
        return None

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BW-Proxy: Secure Approval</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🔐</text></svg>">
    <link rel="manifest" href="/manifest.json">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #0f172a;
            --card-bg: rgba(30, 41, 59, 0.7);
            --primary: #38bdf8;
            --primary-hover: #0ea5e9;
            --danger: #ef4444;
            --danger-hover: #dc2626;
            --text: #f8fafc;
            --text-dim: #94a3b8;
            --border: rgba(255, 255, 255, 0.1);
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }

        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background-color: var(--bg);
            background-image: 
                radial-gradient(circle at 0% 0%, rgba(56, 189, 248, 0.1) 0, transparent 50%),
                radial-gradient(circle at 100% 100%, rgba(139, 92, 246, 0.1) 0, transparent 50%);
            color: var(--text);
            display: flex; justify-content: center; align-items: center;
            min-height: 100vh; padding: 20px; overflow-x: hidden;
        }

        .container {
            width: 100%; max-width: 500px;
            background: var(--card-bg);
            backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
            border: 1px solid var(--border); border-radius: 24px;
            padding: 40px; box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
            transition: all 0.3s ease; position: relative;
        }

        .container.expanded { max-width: 850px; }

        @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }

        .header { text-align: center; margin-bottom: 32px; }
        .logo { font-size: 28px; font-weight: 700; background: linear-gradient(to right, #38bdf8, #818cf8); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 4px; }
        .status-badge { display: inline-block; padding: 4px 12px; border-radius: 9999px; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em; background: rgba(56, 189, 248, 0.1); color: var(--primary); border: 1px solid rgba(56, 189, 248, 0.2); margin-bottom: 12px; }

        .destructive-alert { background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.2); color: #fca5a5; padding: 16px; border-radius: 12px; margin-bottom: 24px; display: flex; align-items: center; gap: 12px; }

        .rationale { font-size: 15px; line-height: 1.6; color: var(--text-dim); margin-bottom: 24px; padding: 16px; background: rgba(255,255,255,0.03); border-radius: 12px; border-left: 3px solid var(--primary); }
        .review-notice { font-size: 13px; line-height: 1.6; color: #bfdbfe; margin-bottom: 24px; padding: 14px 16px; background: rgba(56, 189, 248, 0.08); border-radius: 12px; border: 1px solid rgba(56, 189, 248, 0.2); }

        .content-area { background: rgba(0, 0, 0, 0.2); border-radius: 16px; padding: 20px; margin-bottom: 24px; max-height: 400px; overflow-y: auto; border: 1px solid var(--border); }

        table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 14px; }
        th { text-align: left; color: var(--text-dim); padding: 12px; border-bottom: 1px solid var(--border); }
        td { padding: 12px; border-bottom: 1px solid var(--border); vertical-align: top; }
        tr:last-child td { border-bottom: none; }
        .val-pill { display: inline-block; padding: 2px 8px; border-radius: 4px; background: rgba(255,255,255,0.05); font-family: monospace; }
        .diff-tag { font-weight: bold; }
        .match { color: #4ade80; }
        .mismatch { color: #f87171; }

        .op-item { font-family: 'ui-monospace', monospace; font-size: 13px; padding: 10px 0; border-bottom: 1px solid var(--border); display: flex; gap: 12px; }
        .op-item:last-child { border-bottom: none; }
        .op-index { color: var(--primary); font-weight: bold; min-width: 20px; }
        .op-card { padding: 16px; border-radius: 14px; border: 1px solid var(--border); background: rgba(255, 255, 255, 0.03); margin-bottom: 16px; }
        .op-card:last-child { margin-bottom: 0; }
        .op-card h4 { font-size: 15px; margin-bottom: 10px; }
        .op-summary { font-size: 13px; color: var(--text); margin-bottom: 12px; word-break: break-word; }
        .op-section-title { font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-dim); margin-bottom: 8px; }
        .op-ref-list { margin-bottom: 12px; }
        .op-ref-row { display: flex; gap: 10px; font-size: 12px; color: var(--text-dim); margin-bottom: 6px; flex-wrap: wrap; }
        .op-ref-row strong { color: var(--text); }
        .op-json { margin: 0; padding: 12px; border-radius: 10px; background: rgba(15, 23, 42, 0.8); border: 1px solid var(--border); font-family: 'ui-monospace', monospace; font-size: 12px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; }
        .step-label { display: inline-block; margin-bottom: 12px; padding: 4px 10px; border-radius: 9999px; border: 1px solid var(--border); font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-dim); }

        .input-group { margin-bottom: 24px; }
        label { display: block; margin-bottom: 8px; font-weight: 600; font-size: 13px; color: var(--text-dim); }
        input[type="password"], input[type="text"] { width: 100%; background: rgba(0, 0, 0, 0.4); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; color: white; font-size: 16px; outline: none; transition: all 0.2s; }
        input[type="password"]:focus, input[type="text"]:focus { border-color: var(--primary); box-shadow: 0 0 0 4px rgba(56, 189, 248, 0.1); }

        .actions { display: flex; gap: 16px; }
        button { flex: 1; padding: 14px; border-radius: 12px; font-size: 15px; font-weight: 700; cursor: pointer; transition: all 0.2s; border: none; }
        .btn-approve { background: var(--primary); color: var(--bg); }
        .btn-approve:hover { background: var(--primary-hover); transform: translateY(-1px); box-shadow: 0 8px 20px -4px rgba(56, 189, 248, 0.4); }
        .btn-reject { background: transparent; color: var(--text-dim); border: 1px solid var(--border); }
        .btn-reject:hover { background: rgba(255, 255, 255, 0.05); color: var(--text); }

        .timeout-bar { position: absolute; top: 0; left: 0; height: 3px; background: var(--primary); width: 100%; border-radius: 24px 24px 0 0; transition: width linear; }

        #step-auth { animation: fadeIn 0.3s ease-out; }
        #step-review { display: none; animation: fadeIn 0.3s ease-out; }

        .success-overlay { display: none; position: absolute; top: 0; left: 0; right: 0; bottom: 0; background: var(--bg); border-radius: 24px; z-index: 50; flex-direction: column; justify-content: center; align-items: center; text-align: center; }

        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 10px; }
    </style>
</head>
<body>
    <div class="container" id="main-container">
        <div class="timeout-bar" id="timeout-bar"></div>
        <div class="header">
            <div class="status-badge" id="req-type-badge">🔒 Encrypted Session</div>
            <div class="logo">BW-Proxy</div>
        </div>

        <!-- STEP 1: PROMPT -->
        <div id="step-auth">
            <div class="step-label" id="prompt-step-label">Step 1/2 · Input</div>
            <div style="text-align: center; margin-bottom: 24px">
                <div style="font-size: 40px; margin-bottom: 12px" id="prompt-icon">🔑</div>
                <h3 style="margin-bottom: 8px" id="prompt-heading">Unlock to Review</h3>
                <p style="color: var(--text-dim); font-size: 14px" id="prompt-copy">Enter the required value to continue.</p>
            </div>
            <div class="input-group">
                <label for="prompt-input" id="prompt-label">Value</label>
                <input type="password" id="prompt-input" placeholder="Enter value" autocomplete="one-time-code" spellcheck="false" autofocus>
            </div>
            <div class="actions">
                <button type="button" class="btn-reject" id="cancel-auth">Cancel</button>
                <button type="button" class="btn-approve" id="unlock-btn">Continue</button>
            </div>
        </div>

        <!-- STEP 2: REVIEW -->
        <div id="step-review">
            <div class="step-label" id="review-step-label">Step 2/2 · Final Authorization</div>
            <div id="destructive-warning" class="destructive-alert" style="display: none;">
                <span style="font-size: 20px">⚠️</span>
                <div style="font-size: 14px"><strong>Destructive Operations:</strong> Deletions or irreversible moves detected.</div>
            </div>

            <div class="rationale" id="rationale-text"></div>
            <div class="review-notice" id="review-notice"></div>

            <div class="content-area" id="main-content">
                <!-- Dynamic Content -->
            </div>

            <div class="actions">
                <button type="button" class="btn-reject" id="reject-btn">Reject</button>
                <button type="button" class="btn-approve" id="approve-btn">Authorize Execution</button>
            </div>
        </div>

        <div class="success-overlay" id="success-overlay">
            <div style="font-size: 50px; margin-bottom: 20px">🔐</div>
            <h2 style="margin-bottom: 8px">Action Authorized</h2>
            <p style="color: var(--text-dim); font-size: 14px">The proxy is now executing your request.<br>You can close this tab.</p>
        </div>
    </div>

    <script>
        const data = {{DATA_JSON}};
        const token = "{{TOKEN}}";
        let promptValue = "";
        let timeoutSec = 300; // 5 minutes

        const mainContainer = document.getElementById('main-container');
        const stepAuth = document.getElementById('step-auth');
        const stepReview = document.getElementById('step-review');
        const badge = document.getElementById('req-type-badge');
        const timeoutBar = document.getElementById('timeout-bar');
        const reviewNotice = document.getElementById('review-notice');
        const reviewStepLabel = document.getElementById('review-step-label');
        const promptStepLabel = document.getElementById('prompt-step-label');
        const promptHeading = document.getElementById('prompt-heading');
        const promptCopy = document.getElementById('prompt-copy');
        const promptLabel = document.getElementById('prompt-label');
        const promptInput = document.getElementById('prompt-input');
        const promptIcon = document.getElementById('prompt-icon');
        const unlockBtn = document.getElementById('unlock-btn');
        const approveBtn = document.getElementById('approve-btn');
        const flow = data.flow || 'review';
        const inputKind = data.input_kind || 'password';

        promptStepLabel.textContent = flow === 'prompt_review' ? 'Step 1/2 · Input' : 'Step 1/1 · Input';
        promptHeading.textContent = data.prompt_title || 'Input Required';
        promptCopy.textContent = data.rationale || 'Enter the required value to continue.';
        promptLabel.textContent = data.input_label || 'Value';
        promptInput.placeholder = data.input_placeholder || 'Enter value';
        promptInput.type = inputKind === 'password' ? 'password' : 'text';
        promptInput.autocomplete = inputKind === 'password' ? 'one-time-code' : 'off';
        promptIcon.textContent = inputKind === 'password' ? '🔑' : '📝';
        unlockBtn.textContent = flow === 'prompt' ? (data.primary_action || 'Submit') : 'Continue';
        approveBtn.textContent = data.primary_action || 'Authorize';

        // Initialize Review Step
        document.getElementById('rationale-text').innerText = data.rationale || "No rationale provided.";
        reviewNotice.innerText = data.review_notice || "Execution starts only after the final authorization button.";
        const container = document.getElementById('main-content');

        if (data.type === 'comparison') {
            badge.innerText = "Secret Comparison";
            let html = '<table><thead><tr><th>Target Item</th><th>Field</th><th>Match?</th></tr></thead><tbody>';
            data.comparisons.forEach(c => {
                const tagClass = c.result === data.match_tag ? 'match' : 'mismatch';
                html += `<tr>
                    <td><b>${c.name_a}</b> vs <b>${c.name_b}</b></td>
                    <td><span class="val-pill">${c.field}</span></td>
                    <td><span class="diff-tag ${tagClass}">${c.result}</span></td>
                </tr>`;
            });
            html += '</tbody></table>';
            container.innerHTML = html;
        } 
        else if (data.type === 'duplicate_scan') {
            badge.innerText = "Duplicate Scan";
            let html = `<p style="margin-bottom:12px; font-size:14px;">Found <b>${data.duplicates.length}</b> matches for <b>${data.target_name}</b> (${data.field_path}):</p>`;
            html += '<table><tbody>';
            data.duplicates.forEach(d => {
                html += `<tr><td>${d.name}</td><td><span class="val-pill">${d.id}</span></td></tr>`;
            });
            html += '</tbody></table>';
            container.innerHTML = html;
        }
        else {
            badge.innerText = data.review_title || ((data.formatted_ops && data.formatted_ops.length > 1) ? "Transaction Review" : "Review");
            const details = data.operations_details || [];
            if (details.length > 0) {
                details.forEach((op, i) => {
                    const card = document.createElement('div');
                    card.className = 'op-card';

                    const title = document.createElement('h4');
                    title.textContent = `${i + 1}. ${op.action}`;
                    card.appendChild(title);

                    const summary = document.createElement('div');
                    summary.className = 'op-summary';
                    summary.textContent = op.summary || '';
                    card.appendChild(summary);

                    if (op.resolved_refs && op.resolved_refs.length > 0) {
                        const refsTitle = document.createElement('div');
                        refsTitle.className = 'op-section-title';
                        refsTitle.textContent = 'Resolved Targets';
                        card.appendChild(refsTitle);

                        const refs = document.createElement('div');
                        refs.className = 'op-ref-list';
                        op.resolved_refs.forEach((ref) => {
                            const row = document.createElement('div');
                            row.className = 'op-ref-row';
                            row.innerHTML = `<strong>${ref.field}</strong><span>${ref.name ? `${ref.name} · ` : ''}${ref.id}</span>`;
                            refs.appendChild(row);
                        });
                        card.appendChild(refs);
                    }

                    const jsonTitle = document.createElement('div');
                    jsonTitle.className = 'op-section-title';
                    jsonTitle.textContent = 'Exact Operation Payload';
                    card.appendChild(jsonTitle);

                    const jsonBlock = document.createElement('pre');
                    jsonBlock.className = 'op-json';
                    jsonBlock.textContent = op.raw_json || '{}';
                    card.appendChild(jsonBlock);

                    container.appendChild(card);
                });
            } else {
                (data.formatted_ops || []).forEach((op, i) => {
                    const div = document.createElement('div');
                    div.className = 'op-item';
                    div.innerHTML = `<span class="op-index">${i+1}.</span><span>${op}</span>`;
                    container.appendChild(div);
                });
            }
        }

        if (data.has_destructive) document.getElementById('destructive-warning').style.display = 'flex';

        // Session Timeout Logic
        const rejectFn = async (reason = 'user') => {
            try { await fetch('/reject', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token, reason }) }); } 
            finally { window.close(); }
        };

        const timer = setInterval(() => {
            timeoutSec--;
            timeoutBar.style.width = (timeoutSec / 300 * 100) + '%';
            if (timeoutSec <= 0) {
                clearInterval(timer);
                rejectFn('timeout');
            }
        }, 1000);

        // Transition: Unlock -> Review
        const submitApproval = async () => {
            clearInterval(timer);
            approveBtn.disabled = true;
            approveBtn.innerText = 'Processing...';

            try {
                const body = { token };
                if (inputKind === 'password' && promptValue) body.password = promptValue;
                if (inputKind === 'text' && promptValue) body.input_text = promptValue;
                const res = await fetch('/approve', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                if (res.ok) {
                    document.getElementById('success-overlay').style.display = 'flex';
                    timeoutBar.style.display = 'none';
                } else {
                    alert('Session expired or invalid token.');
                }
            } catch (err) {
                alert('Communication error.');
            }
        };

        unlockBtn.onclick = () => {
            if (flow === 'review') {
                return;
            }
            if (!promptInput.value) {
                alert(`${data.input_label || 'Value'} required.`);
                return;
            }
            promptValue = promptInput.value;
            if (flow === 'prompt') {
                submitApproval();
                return;
            }
            stepAuth.style.display = 'none';
            stepReview.style.display = 'block';
            mainContainer.classList.add('expanded');
            badge.innerText = data.review_title || "Transparent Review";
        };

        // Submit Approval
        approveBtn.onclick = submitApproval;
        document.getElementById('reject-btn').onclick = () => rejectFn();
        document.getElementById('cancel-auth').onclick = () => rejectFn();
        promptInput.onkeypress = (e) => {
            if (e.key === 'Enter') unlockBtn.click();
        };

        if (flow === 'review') {
            stepAuth.style.display = 'none';
            stepReview.style.display = 'block';
            mainContainer.classList.add('expanded');
            reviewStepLabel.textContent = 'Final Authorization';
        }
    </script>
</body>
</html>
"""

class ThreadingHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Multi-threaded server to handle parallel requests (HTML, Manifest, Favicon)."""
    daemon_threads = True
    allow_reuse_address = True

class HITLHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        global _hitl_token, _hitl_request_data, _custom_get_handler
        if _custom_get_handler is not None:
            return _custom_get_handler(self)
        
        # Handle Manifest for PWA feel
        if self.path == "/manifest.json":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            manifest = {
                "name": "BW-Proxy HITL",
                "short_name": "BW-Proxy",
                "start_url": "/",
                "display": "standalone",
                "background_color": "#0f172a",
                "theme_color": "#38bdf8"
            }
            self.wfile.write(json.dumps(manifest).encode("utf-8"))
            return

        # Handle Root with Token
        if "/?token=" in self.path:
            try:
                token_provided = self.path.split("token=")[1].split("&")[0]
                if token_provided == _hitl_token:
                    self.send_response(200)
                    self.send_header("Content-type", "text/html")
                    self.end_headers()
                    content = HTML_TEMPLATE.replace("{{DATA_JSON}}", json.dumps(_hitl_request_data))
                    content = content.replace("{{TOKEN}}", _hitl_token)
                    self.wfile.write(content.encode("utf-8"))
                    return
            except: pass
                
        self.send_response(403)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"403 Forbidden: Invalid or expired token.")

    def do_POST(self):
        global _hitl_token, _hitl_response, _custom_post_handler
        if _custom_post_handler is not None:
            return _custom_post_handler(self)
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = json.loads(self.rfile.read(content_length))
            if post_data.get("token") != _hitl_token:
                self.send_response(403)
                self.end_headers()
                return
            
            if self.path == "/approve":
                pw = post_data.get("password")
                input_text = post_data.get("input_text")
                _hitl_response = {
                    "approved": True,
                    "password": bytearray(pw, "utf-8") if pw else None,
                    "input_text": input_text,
                }
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"OK")
                # Delayed shutdown to allow response to finish
                threading.Timer(0.5, self.server.shutdown).start()
            elif self.path == "/reject":
                _hitl_response = {"approved": False}
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"OK")
                threading.Timer(0.5, self.server.shutdown).start()
        except:
            self.send_response(500)
            self.end_headers()

class WebHITLManager:
    @staticmethod
    def request_approval(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        global _hitl_request_data, _hitl_response, _hitl_token, _hitl_server, _custom_get_handler, _custom_post_handler
        _hitl_request_data = data
        _hitl_response = None
        _hitl_token = str(uuid.uuid4())
        _custom_get_handler = None
        _custom_post_handler = None
        
        from .config import HITL_USE_HTTPS
        cert_bundle = _generate_self_signed_cert(HITL_HOST) if HITL_USE_HTTPS else None
        cert_path = cert_bundle[0] if cert_bundle else None
        
        try:
            with ThreadingHTTPServer((HITL_HOST, HITL_PORT), HITLHandler) as httpd:
                if cert_path:
                    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                    context.load_cert_chain(certfile=cert_path)
                    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
                
                _hitl_server = httpd
                protocol = "https" if cert_path else "http"
                url = f"{protocol}://{HITL_HOST}:{HITL_PORT}/?token={_hitl_token}"
                
                print(f"\n\n🔐 [BW-Proxy] SECURE APPROVAL REQUIRED", flush=True)
                print(f"   Rationale: {data.get('rationale')}", flush=True)
                print(f"   Action   : Please open your browser to authorize:", flush=True)
                print(f"   URL      : \033[1;34m{url}\033[0m", flush=True)
                print(f"   (Waiting for your decision...)\n", flush=True)
                
                if HITL_AUTO_OPEN:
                    webbrowser.open(url)
                httpd.serve_forever()
        except Exception as e:
            print(f"⚠️ Web HITL Server failed: {e}")
            return None
        finally:
            if cert_bundle:
                _, cleanup_paths, temp_dir = cert_bundle
                for path in cleanup_paths:
                    if os.path.exists(path):
                        try:
                            os.remove(path)
                        except Exception:
                            pass
                if os.path.isdir(temp_dir):
                    try:
                        os.rmdir(temp_dir)
                    except Exception:
                        pass
                
        return _hitl_response


CONFIG_EDITOR_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>BW-Proxy Config Editor</title>
  <style>
    :root {
      --bg: #0f172a;
      --panel: rgba(15, 23, 42, 0.88);
      --line: rgba(148, 163, 184, 0.25);
      --text: #e2e8f0;
      --muted: #94a3b8;
      --accent: #38bdf8;
      --accent-2: #0ea5e9;
      --danger: #ef4444;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, system-ui, sans-serif;
      background:
        radial-gradient(circle at top left, rgba(56,189,248,0.14), transparent 35%),
        radial-gradient(circle at bottom right, rgba(14,165,233,0.10), transparent 40%),
        var(--bg);
      color: var(--text);
      min-height: 100vh;
      padding: 24px;
    }
    .shell {
      max-width: 1100px;
      margin: 0 auto;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 24px;
      box-shadow: 0 30px 80px rgba(0,0,0,0.45);
    }
    h1 { margin: 0 0 8px; font-size: 28px; }
    .lead { color: var(--muted); margin: 0 0 20px; line-height: 1.5; }
    .notice {
      margin-bottom: 16px;
      padding: 12px 14px;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.03);
      color: var(--muted);
    }
    textarea {
      width: 100%;
      min-height: 560px;
      resize: vertical;
      border-radius: 16px;
      border: 1px solid var(--line);
      background: rgba(2, 6, 23, 0.92);
      color: var(--text);
      font: 14px/1.6 "Fira Code", "JetBrains Mono", monospace;
      padding: 18px;
      outline: none;
    }
    textarea:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(56,189,248,0.14); }
    .actions { display: flex; gap: 12px; margin-top: 16px; }
    button {
      border: none;
      border-radius: 12px;
      padding: 12px 18px;
      font-weight: 700;
      cursor: pointer;
    }
    .save { background: var(--accent); color: #082f49; }
    .save:hover { background: var(--accent-2); }
    .cancel { background: transparent; color: var(--text); border: 1px solid var(--line); }
    .error {
      margin-top: 14px;
      padding: 14px;
      border-radius: 12px;
      background: rgba(239,68,68,0.14);
      border: 1px solid rgba(239,68,68,0.35);
      color: #fecaca;
      display: none;
      white-space: pre-wrap;
    }
    .success {
      margin-top: 14px;
      padding: 14px;
      border-radius: 12px;
      background: rgba(34,197,94,0.12);
      border: 1px solid rgba(34,197,94,0.28);
      color: #bbf7d0;
      display: none;
    }
  </style>
</head>
<body>
  <div class="shell">
    <h1>BW-Proxy Config Editor</h1>
    <p class="lead">Edit the full <code>config.yaml</code>, then validate and apply it. The real file is only updated after successful validation and explicit approval.</p>
    <div class="notice">This editor is browser-based to stay cross-platform and consistent with the project HITL workflow.</div>
    <textarea id="editor">{{CONFIG_TEXT}}</textarea>
    <div class="actions">
      <button class="save" id="save-btn">Validate and Apply</button>
      <button class="cancel" id="cancel-btn">Cancel</button>
    </div>
    <div class="error" id="error-box"></div>
    <div class="success" id="success-box">Configuration updated successfully. You can close this tab.</div>
  </div>
  <script>
    const token = "{{TOKEN}}";
    const saveBtn = document.getElementById("save-btn");
    const cancelBtn = document.getElementById("cancel-btn");
    const editor = document.getElementById("editor");
    const errorBox = document.getElementById("error-box");
    const successBox = document.getElementById("success-box");

    function showError(message) {
      errorBox.style.display = "block";
      errorBox.textContent = message;
      successBox.style.display = "none";
    }

    saveBtn.onclick = async () => {
      errorBox.style.display = "none";
      saveBtn.disabled = true;
      saveBtn.textContent = "Validating...";
      try {
        const res = await fetch("/save", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token, text: editor.value })
        });
        const payload = await res.json();
        if (!res.ok || !payload.ok) {
          showError(payload.error || "Validation failed.");
          saveBtn.disabled = false;
          saveBtn.textContent = "Validate and Apply";
          return;
        }
        successBox.style.display = "block";
        saveBtn.textContent = "Applied";
      } catch (err) {
        showError("Communication error while saving configuration.");
        saveBtn.disabled = false;
        saveBtn.textContent = "Validate and Apply";
      }
    };

    cancelBtn.onclick = async () => {
      await fetch("/cancel", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token })
      });
      window.close();
    };
  </script>
</body>
</html>
"""


class WebEditorManager:
    @staticmethod
    def edit_text(*, title: str, initial_text: str, on_save) -> Optional[Dict[str, Any]]:
        global _hitl_response, _hitl_token, _hitl_server, _custom_get_handler, _custom_post_handler
        _hitl_response = None
        _hitl_token = str(uuid.uuid4())

        def custom_get(handler):
            if handler.path == f"/?token={_hitl_token}" or handler.path.startswith(f"/?token={_hitl_token}&"):
                handler.send_response(200)
                handler.send_header("Content-type", "text/html")
                handler.end_headers()
                content = CONFIG_EDITOR_TEMPLATE.replace("{{TOKEN}}", _hitl_token)
                content = content.replace("{{CONFIG_TEXT}}", html.escape(initial_text))
                content = content.replace("BW-Proxy Config Editor", html.escape(title))
                handler.wfile.write(content.encode("utf-8"))
                return
            handler.send_response(403)
            handler.end_headers()

        def custom_post(handler):
            global _hitl_response
            content_length = int(handler.headers["Content-Length"])
            post_data = json.loads(handler.rfile.read(content_length))
            if post_data.get("token") != _hitl_token:
                handler.send_response(403)
                handler.end_headers()
                return
            if handler.path == "/save":
                try:
                    saved = on_save(post_data.get("text", ""))
                    _hitl_response = {"approved": True, "data": saved}
                    handler.send_response(200)
                    handler.send_header("Content-type", "application/json")
                    handler.end_headers()
                    handler.wfile.write(json.dumps({"ok": True}).encode("utf-8"))
                    threading.Timer(0.5, handler.server.shutdown).start()
                except Exception as exc:
                    handler.send_response(400)
                    handler.send_header("Content-type", "application/json")
                    handler.end_headers()
                    handler.wfile.write(json.dumps({"ok": False, "error": str(exc)}).encode("utf-8"))
                return
            if handler.path == "/cancel":
                _hitl_response = {"approved": False}
                handler.send_response(200)
                handler.send_header("Content-type", "application/json")
                handler.end_headers()
                handler.wfile.write(json.dumps({"ok": True}).encode("utf-8"))
                threading.Timer(0.5, handler.server.shutdown).start()
                return
            handler.send_response(404)
            handler.end_headers()

        _custom_get_handler = custom_get
        _custom_post_handler = custom_post
        try:
            with ThreadingHTTPServer((HITL_HOST, HITL_PORT), HITLHandler) as httpd:
                _hitl_server = httpd
                url = f"http://{HITL_HOST}:{HITL_PORT}/?token={_hitl_token}"
                print(f"\n\n🔐 [BW-Proxy] CONFIG EDIT REQUIRED", flush=True)
                print(f"   URL      : \033[1;34m{url}\033[0m", flush=True)
                print(f"   (Waiting for your edit...)\n", flush=True)
                if HITL_AUTO_OPEN:
                    webbrowser.open(url)
                httpd.serve_forever()
        finally:
            _custom_get_handler = None
            _custom_post_handler = None
        return _hitl_response
