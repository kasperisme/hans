#!/usr/bin/env python3
"""
Simple webhook listener for auto-deployment.
Listens for GitHub webhook POSTs and pulls latest changes.

Run with: python deploy/update-hook.py
Or set up as a systemd service.
"""

import os
import subprocess
import hmac
import hashlib
from http.server import HTTPServer, BaseHTTPRequestHandler

# Configuration
PORT = 9000
PROJECT_DIR = os.path.expanduser("~/hans")
WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")


def verify_signature(payload: bytes, signature: str) -> bool:
    """Verify GitHub webhook signature."""
    if not WEBHOOK_SECRET:
        return True  # Skip verification if no secret set

    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


def pull_and_restart():
    """Pull latest changes and restart the bot."""
    os.chdir(PROJECT_DIR)

    # Pull latest changes
    result = subprocess.run(
        ["git", "pull", "--ff-only"],
        capture_output=True,
        text=True
    )
    print(f"Git pull: {result.stdout}")

    if result.returncode != 0:
        print(f"Git pull error: {result.stderr}")
        return False

    # Restart the bot service
    result = subprocess.run(
        ["sudo", "systemctl", "restart", "hans-bot"],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        print(f"Restart error: {result.stderr}")
        return False

    print("Successfully updated and restarted")
    return True


class WebhookHandler(BaseHTTPRequestHandler):
    """Handle incoming webhook requests."""

    def do_POST(self):
        """Handle POST request from GitHub."""
        content_length = int(self.headers.get("Content-Length", 0))
        payload = self.rfile.read(content_length)

        # Verify signature
        signature = self.headers.get("X-Hub-Signature-256", "")
        if not verify_signature(payload, signature):
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"Invalid signature")
            return

        # Perform update
        success = pull_and_restart()

        if success:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Updated successfully")
        else:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"Update failed")

    def do_GET(self):
        """Health check endpoint."""
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Hans webhook listener running")


def main():
    """Start the webhook server."""
    server = HTTPServer(("0.0.0.0", PORT), WebhookHandler)
    print(f"Webhook listener running on port {PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
