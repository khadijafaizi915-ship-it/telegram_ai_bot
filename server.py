import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import os


PORT = int(os.getenv("PORT", "8000"))


class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Telegram AI Bot is running!")

    def log_message(self, format, *args):
        pass


def run_web_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    print(f"Web server running on port {PORT}")
    server.serve_forever()


web_thread = threading.Thread(
    target=run_web_server,
    daemon=True
)

web_thread.start()


print("Starting Telegram AI Bot...")

subprocess.run(
    ["python", "bot.py"],
    check=True
  )
