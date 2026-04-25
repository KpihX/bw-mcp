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
from typing import Optional, Dict, Any
from .config import HITL_HOST, HITL_PORT, HITL_AUTO_OPEN

# Global state for the temporary HITL server
_hitl_request_data = None
_hitl_response = None
_hitl_token = None
_hitl_server = None

def _generate_self_signed_cert():
    """Generates a temporary self-signed certificate in RAM-only storage."""
    cert_dir = "/dev/shm" if os.path.exists("/dev/shm") else tempfile.gettempdir()
    cert_path = os.path.join(cert_dir, f"bw_proxy_{uuid.uuid4()}.pem")
    
    cmd = [
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-keyout", cert_path,
        "-out", cert_path, "-days", "1", "-nodes",
        "-subj", "/CN=localhost"
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return cert_path
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

        .input-group { margin-bottom: 24px; }
        label { display: block; margin-bottom: 8px; font-weight: 600; font-size: 13px; color: var(--text-dim); }
        input[type="password"] { width: 100%; background: rgba(0, 0, 0, 0.4); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; color: white; font-size: 16px; outline: none; transition: all 0.2s; }
        input[type="password"]:focus { border-color: var(--primary); box-shadow: 0 0 0 4px rgba(56, 189, 248, 0.1); }

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

        <!-- STEP 1: AUTHENTICATION -->
        <div id="step-auth">
            <div style="text-align: center; margin-bottom: 24px">
                <div style="font-size: 40px; margin-bottom: 12px">🔑</div>
                <h3 style="margin-bottom: 8px">Unlock to Review</h3>
                <p style="color: var(--text-dim); font-size: 14px">Please enter your master password to decrypt and review the pending request.</p>
            </div>
            <div class="input-group">
                <label for="master-password-init">Master Password</label>
                <!-- Aggressive autocomplete disable using one-time-code and unique random names if needed, but autocomplete="off" + spellcheck="false" is standard -->
                <input type="password" id="master-password-init" placeholder="Enter password" autocomplete="one-time-code" spellcheck="false" autofocus>
            </div>
            <div class="actions">
                <button type="button" class="btn-reject" id="cancel-auth">Cancel</button>
                <button type="button" class="btn-approve" id="unlock-btn">Unlock</button>
            </div>
        </div>

        <!-- STEP 2: REVIEW -->
        <div id="step-review">
            <div id="destructive-warning" class="destructive-alert" style="display: none;">
                <span style="font-size: 20px">⚠️</span>
                <div style="font-size: 14px"><strong>Destructive Operations:</strong> Deletions or irreversible moves detected.</div>
            </div>

            <div class="rationale" id="rationale-text"></div>

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
        let masterPassword = "";
        let timeoutSec = 300; // 5 minutes

        const mainContainer = document.getElementById('main-container');
        const stepAuth = document.getElementById('step-auth');
        const stepReview = document.getElementById('step-review');
        const badge = document.getElementById('req-type-badge');
        const timeoutBar = document.getElementById('timeout-bar');

        // Initialize Review Step
        document.getElementById('rationale-text').innerText = data.rationale || "No rationale provided.";
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
            badge.innerText = (data.formatted_ops && data.formatted_ops.length > 1) ? "Transaction Review" : "Authentication";
            (data.formatted_ops || []).forEach((op, i) => {
                const div = document.createElement('div');
                div.className = 'op-item';
                div.innerHTML = `<span class="op-index">${i+1}.</span><span>${op}</span>`;
                container.appendChild(div);
            });
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
        document.getElementById('unlock-btn').onclick = () => {
            const pwInput = document.getElementById('master-password-init');
            if (!pwInput.value && data.needs_password) {
                alert("Master password required.");
                return;
            }
            masterPassword = pwInput.value;
            stepAuth.style.display = 'none';
            stepReview.style.display = 'block';
            mainContainer.classList.add('expanded');
            if (!data.needs_password) badge.innerText = "Authorized View";
            else badge.innerText = "Authorized Review";
            // Pause timeout bar once unlocked for review? Or just keep it.
            // Let's keep it for security.
        };

        // Submit Approval
        document.getElementById('approve-btn').onclick = async () => {
            clearInterval(timer);
            document.getElementById('approve-btn').disabled = true;
            document.getElementById('approve-btn').innerText = 'Processing...';

            try {
                const res = await fetch('/approve', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ token, password: masterPassword })
                });
                if (res.ok) {
                    document.getElementById('success-overlay').style.display = 'flex';
                    timeoutBar.style.display = 'none';
                }
                else alert('Session expired or invalid token.');
            } catch (err) { alert('Communication error.'); }
        };

        document.getElementById('reject-btn').onclick = () => rejectFn();
        document.getElementById('cancel-auth').onclick = () => rejectFn();
        document.getElementById('master-password-init').onkeypress = (e) => {
            if (e.key === 'Enter') document.getElementById('unlock-btn').click();
        };
    </script>
</body>
</html>
"""

class ThreadingHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Multi-threaded server to handle parallel requests (HTML, Manifest, Favicon)."""
    daemon_threads = True

class HITLHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        global _hitl_token, _hitl_request_data
        
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
        global _hitl_token, _hitl_response
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = json.loads(self.rfile.read(content_length))
            if post_data.get("token") != _hitl_token:
                self.send_response(403)
                self.end_headers()
                return
            
            if self.path == "/approve":
                pw = post_data.get("password")
                _hitl_response = {"approved": True, "password": bytearray(pw, "utf-8") if pw else None}
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
        global _hitl_request_data, _hitl_response, _hitl_token, _hitl_server
        _hitl_request_data = data
        _hitl_response = None
        _hitl_token = str(uuid.uuid4())
        
        from .config import HITL_USE_HTTPS
        cert_path = _generate_self_signed_cert() if HITL_USE_HTTPS else None
        
        try:
            # Use ThreadingHTTPServer instead of TCPServer
            with ThreadingHTTPServer((HITL_HOST, HITL_PORT), HITLHandler) as httpd:
                httpd.allow_reuse_address = True
                if cert_path:
                    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                    context.load_cert_chain(certfile=cert_path)
                    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
                
                _hitl_server = httpd
                protocol = "https" if cert_path else "http"
                url = f"{protocol}://{HITL_HOST}:{HITL_PORT}/?token={_hitl_token}"
                
                print(f"\n\n🔐 [BW-Proxy] SECURE APPROVAL REQUIRED")
                print(f"   Rationale: {data.get('rationale')}")
                print(f"   Action   : Please open your browser to authorize:")
                print(f"   URL      : \033[1;34m{url}\033[0m")
                print(f"   (Waiting for your decision...)\n")
                
                if HITL_AUTO_OPEN:
                    webbrowser.open(url)
                httpd.serve_forever()
        except Exception as e:
            print(f"⚠️ Web HITL Server failed: {e}")
            return None
        finally:
            if cert_path and os.path.exists(cert_path):
                try: os.remove(cert_path)
                except: pass
                
        return _hitl_response
