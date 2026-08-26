"""Временная заглушка Qwen для проверки цепочки без корпоративной сети."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json

TABLE = """| Требование клиента | Покрытие по программе | Статус | Комментарий |
|---|---|---|---|
| Стационарная помощь | Программа А, п.3 | Есть | Покрывается полностью |
| Стоматология | Программа А, п.7 | Частично | Только неотложная |

Итог: выбрана Программа А."""

class H(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length', 0)))
        body = json.dumps({"choices": [{"text": TABLE}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a): pass

HTTPServer(("0.0.0.0", 8080), H).serve_forever()
