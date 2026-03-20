# ============================================================
# keep_alive.py — ANTI-SLEEP SERVER + OTP WEB FORM
# Prevents Render from sleeping
# Also serves OTP entry page for Telegram scanner setup
# ============================================================

from flask import Flask, request, jsonify
from threading import Thread
import queue

app = Flask(__name__)

# OTP queue — telegram_scanner.py reads from this
otp_queue = queue.Queue()

# Status flags
otp_submitted  = False
otp_value      = None
scanner_status = "waiting"  # waiting / authenticating / active / disabled


# ============================================================
# ROUTES
# ============================================================

@app.route("/")
def home():
    return "Solana Sniper Bot is running.", 200


@app.route("/health")
def health():
    return "OK", 200


@app.route("/otp", methods=["GET"])
def otp_page():
    """
    Web page for entering Telegram OTP code from phone.
    Open this URL in your phone browser when bot first starts.
    """
    global scanner_status

    if scanner_status == "active":
        return """
        <html>
        <head>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                body { font-family: Arial; background: #0a0a0a; color: #00ff88;
                       display: flex; justify-content: center; align-items: center;
                       min-height: 100vh; margin: 0; padding: 20px; box-sizing: border-box; }
                .box { background: #111; border: 1px solid #00ff88; border-radius: 12px;
                       padding: 30px; max-width: 400px; width: 100%; text-align: center; }
                h2 { color: #00ff88; margin-bottom: 10px; }
                p  { color: #aaa; font-size: 14px; }
            </style>
        </head>
        <body>
            <div class="box">
                <h2>✅ Scanner Active</h2>
                <p>Telegram scanner is already authenticated and running.</p>
                <p>No action needed.</p>
            </div>
        </body>
        </html>
        """, 200

    if scanner_status == "disabled":
        return """
        <html>
        <head>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                body { font-family: Arial; background: #0a0a0a; color: #ffaa00;
                       display: flex; justify-content: center; align-items: center;
                       min-height: 100vh; margin: 0; padding: 20px; box-sizing: border-box; }
                .box { background: #111; border: 1px solid #ffaa00; border-radius: 12px;
                       padding: 30px; max-width: 400px; width: 100%; text-align: center; }
                h2 { color: #ffaa00; }
                p  { color: #aaa; font-size: 14px; }
            </style>
        </head>
        <body>
            <div class="box">
                <h2>⚠️ Scanner Disabled</h2>
                <p>Add TELEGRAM_API_ID, TELEGRAM_API_HASH, and TELEGRAM_PHONE to Render environment variables to enable.</p>
            </div>
        </body>
        </html>
        """, 200

    return """
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            * { box-sizing: border-box; }
            body { font-family: Arial, sans-serif; background: #0a0a0a; color: #fff;
                   display: flex; justify-content: center; align-items: center;
                   min-height: 100vh; margin: 0; padding: 20px; }
            .box { background: #111; border: 1px solid #333; border-radius: 16px;
                   padding: 30px; max-width: 420px; width: 100%; }
            h2  { color: #00ff88; margin: 0 0 8px 0; font-size: 22px; }
            p   { color: #999; font-size: 13px; line-height: 1.5; margin: 0 0 20px 0; }
            input { width: 100%; padding: 14px; font-size: 20px; letter-spacing: 6px;
                    text-align: center; border: 2px solid #333; border-radius: 10px;
                    background: #1a1a1a; color: #fff; margin-bottom: 16px;
                    font-family: monospace; }
            input:focus { border-color: #00ff88; outline: none; }
            button { width: 100%; padding: 14px; background: #00ff88; color: #000;
                     border: none; border-radius: 10px; font-size: 16px;
                     font-weight: bold; cursor: pointer; }
            button:hover { background: #00cc70; }
            .note { margin-top: 16px; padding: 12px; background: #1a1a1a;
                    border-radius: 8px; color: #888; font-size: 12px; }
        </style>
    </head>
    <body>
        <div class="box">
            <h2>🔐 Telegram OTP</h2>
            <p>Telegram sent a verification code to your phone number. Enter it below to activate the alpha group scanner.</p>
            <input type="number" id="otp" placeholder="12345" maxlength="6" autofocus />
            <button onclick="submitOTP()">Verify & Activate Scanner</button>
            <div class="note">
                This is a one-time setup. After this the bot authenticates automatically on every restart.
            </div>
            <div id="status" style="margin-top:16px; text-align:center; font-size:14px;"></div>
        </div>
        <script>
            function submitOTP() {
                const code = document.getElementById('otp').value.trim();
                if (!code || code.length < 4) {
                    document.getElementById('status').innerHTML =
                        '<span style="color:#ff4444">Enter the code from Telegram</span>';
                    return;
                }
                document.getElementById('status').innerHTML =
                    '<span style="color:#ffaa00">Verifying...</span>';
                fetch('/otp/submit', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ code: code })
                })
                .then(r => r.json())
                .then(data => {
                    if (data.success) {
                        document.getElementById('status').innerHTML =
                            '<span style="color:#00ff88">✅ ' + data.message + '</span>';
                    } else {
                        document.getElementById('status').innerHTML =
                            '<span style="color:#ff4444">❌ ' + data.message + '</span>';
                    }
                })
                .catch(() => {
                    document.getElementById('status').innerHTML =
                        '<span style="color:#ff4444">Connection error — try again</span>';
                });
            }
            // Submit on Enter key
            document.addEventListener('keydown', e => {
                if (e.key === 'Enter') submitOTP();
            });
        </script>
    </body>
    </html>
    """, 200


@app.route("/otp/submit", methods=["POST"])
def submit_otp():
    """Receives OTP code from web form and passes to scanner"""
    global otp_submitted, otp_value
    try:
        data = request.get_json()
        code = str(data.get("code", "")).strip()

        if not code or len(code) < 4:
            return jsonify({"success": False, "message": "Invalid code"})

        otp_queue.put(code)
        otp_submitted = True
        otp_value     = code

        return jsonify({
            "success": True,
            "message": "Code received! Scanner authenticating... check Telegram for confirmation."
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route("/otp/status")
def otp_status():
    """Returns current scanner status"""
    return jsonify({"status": scanner_status})


# ============================================================
# FUNCTIONS FOR telegram_scanner.py TO CALL
# ============================================================

def set_scanner_status(status):
    """Called by telegram_scanner to update status page"""
    global scanner_status
    scanner_status = status


def get_otp_from_web(timeout=300):
    """
    Blocking call — waits for OTP to be submitted via web form.
    Returns the code or None if timeout.
    Called by telegram_scanner.py instead of input().
    """
    try:
        code = otp_queue.get(timeout=timeout)
        return code
    except Exception:
        return None


# ============================================================
# SERVER STARTUP
# ============================================================

def run():
    app.run(host="0.0.0.0", port=10000, debug=False, use_reloader=False)


def keep_alive():
    t = Thread(target=run, daemon=True)
    t.start()
    print("[KEEP_ALIVE] ✅ Web server started on port 10000")
    print("[KEEP_ALIVE] OTP page: https://solana-sniper-8pb5.onrender.com/otp")
