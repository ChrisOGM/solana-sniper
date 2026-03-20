# ============================================================
# keep_alive.py — PREVENTS RENDER FROM SLEEPING
# Runs a tiny web server so Render thinks service is active
# ============================================================

from flask import Flask
from threading import Thread

app = Flask("")

@app.route("/")
def home():
    return "Solana Sniper Bot is running."

@app.route("/health")
def health():
    return "OK", 200

def run():
    app.run(host="0.0.0.0", port=8080)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()
    print("[KEEP_ALIVE] ✅ Web server started — Render won't sleep")
