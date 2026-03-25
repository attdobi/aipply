#!/usr/bin/env python3
"""Aipply dashboard — local web server to view reports and download artifacts."""

import os
import sys
import mimetypes
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(PROJECT_ROOT)


class AipplyHandler(SimpleHTTPRequestHandler):
    """Serve files from the project root."""

    def translate_path(self, path):
        # Serve from project root
        return str(PROJECT_ROOT / path.lstrip("/"))

    def end_headers(self):
        # Force .docx to download instead of display
        if self.path.endswith('.docx'):
            filename = os.path.basename(self.path)
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
            self.send_header('Content-Type', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        super().end_headers()

    def log_message(self, format, *args):
        # Quieter logging
        pass


if __name__ == "__main__":
    print(f"🚀 Aipply Dashboard running at: http://localhost:{PORT}/output/reports/applications_report.html")
    print(f"   Press Ctrl+C to stop")
    server = HTTPServer(("", PORT), AipplyHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Dashboard stopped")
