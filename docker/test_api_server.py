#!/usr/bin/env python3
"""Simple HTTP API server for exercising snapshot notification hooks."""

from __future__ import annotations

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

LOG_PATH = Path(os.environ.get("NOTIFY_LOG_PATH", "/tmp/test_api_notifications.log"))
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


class NotificationHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))
            return

        self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "not_found"}).encode("utf-8"))

    def do_POST(self) -> None:
        if self.path != "/notify":
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "not_found"}).encode("utf-8"))
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            payload = {"raw": raw_body.decode("utf-8", errors="replace")}

        record = {
            "path": self.path,
            "payload": payload,
        }
        with LOG_PATH.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(record, ensure_ascii=False) + "\n")

        logging.info("Received notification payload: %s", payload)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok", "received": payload}).encode("utf-8"))

    def log_message(self, format: str, *args) -> None:
        logging.info("%s - - [%s] %s", self.address_string(), self.log_date_time_string(), format % args)


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    server = HTTPServer((host, port), NotificationHandler)
    logging.info("Test API server listening on http://%s:%s", host, port)
    server.serve_forever()
