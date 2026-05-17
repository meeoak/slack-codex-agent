import hashlib
import hmac
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import error, request


SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "")
PORT = int(os.environ.get("PORT", "10000"))


def json_response(handler, status, payload):
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def text_response(handler, status, text):
    body = text.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/plain; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def verify_slack_signature(headers, raw_body):
    if not SLACK_SIGNING_SECRET:
        return True

    timestamp = headers.get("X-Slack-Request-Timestamp", "")
    signature = headers.get("X-Slack-Signature", "")
    if not timestamp or not signature:
        return False

    try:
        request_time = int(timestamp)
    except ValueError:
        return False

    if abs(time.time() - request_time) > 60 * 5:
        return False

    base = f"v0:{timestamp}:".encode("utf-8") + raw_body
    digest = hmac.new(
        SLACK_SIGNING_SECRET.encode("utf-8"),
        base,
        hashlib.sha256,
    ).hexdigest()
    expected = f"v0={digest}"
    return hmac.compare_digest(expected, signature)


def post_json(url, token, payload):
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = request.Request(url, data=data, headers=headers, method="POST")
    with request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def ask_openai(user_text):
    if not OPENAI_API_KEY:
        return "OPENAI_API_KEY is not configured on the server yet."
    if not OPENAI_MODEL:
        return "OPENAI_MODEL is not configured on the server yet."

    payload = {
        "model": OPENAI_MODEL,
        "input": [
            {
                "role": "system",
                "content": (
                    "You are a helpful coding assistant in Slack. "
                    "Answer in Korean unless the user asks otherwise. "
                    "Keep replies concise and practical."
                ),
            },
            {"role": "user", "content": user_text},
        ],
    }

    try:
        result = post_json("https://api.openai.com/v1/responses", OPENAI_API_KEY, payload)
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"OpenAI API request failed: {exc.code} {detail[:300]}", flush=True)
        return f"OpenAI API request failed. Status code: {exc.code}\n{detail[:500]}"
    except Exception as exc:
        print(f"OpenAI API connection failed: {exc}", flush=True)
        return f"OpenAI API connection failed: {exc}"

    if result.get("output_text"):
        return result["output_text"]

    parts = []
    for item in result.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in ("output_text", "text"):
                parts.append(content.get("text", ""))
    return "\n".join(part for part in parts if part).strip() or "No response text was generated."


def reply_to_slack(channel, thread_ts, text):
    if not SLACK_BOT_TOKEN:
        print("Slack reply skipped: SLACK_BOT_TOKEN is missing", flush=True)
        return

    payload = {
        "channel": channel,
        "text": text[:3500],
    }
    if thread_ts:
        payload["thread_ts"] = thread_ts

    try:
        result = post_json("https://slack.com/api/chat.postMessage", SLACK_BOT_TOKEN, payload)
        if not result.get("ok"):
            print(f"Slack reply failed: {result}", flush=True)
            return
        print(f"Slack reply sent: channel={channel}", flush=True)
    except Exception as exc:
        print(f"Slack reply failed: {exc}", flush=True)


def handle_event(event):
    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return

    event_type = event.get("type")
    if event_type not in ("app_mention", "message"):
        print(f"Ignoring unsupported event: {event_type}", flush=True)
        return

    channel = event.get("channel")
    text = event.get("text", "").strip()
    thread_ts = event.get("thread_ts") or event.get("ts")
    if not channel or not text:
        print(f"Ignoring event with missing channel/text: {event}", flush=True)
        return

    print(f"Handling Slack event: type={event_type} channel={channel}", flush=True)
    answer = ask_openai(text)
    reply_to_slack(channel, thread_ts, answer)


class SlackHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(fmt % args, flush=True)

    def do_GET(self):
        if self.path == "/":
            text_response(self, 200, "Slack Codex agent server is running.")
            return
        text_response(self, 404, "Not found")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length)

        if self.path != "/slack/events":
            text_response(self, 404, "Not found")
            return

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            text_response(self, 400, "Invalid JSON")
            return

        if payload.get("type") == "url_verification":
            text_response(self, 200, payload.get("challenge", ""))
            return

        if not verify_slack_signature(self.headers, raw_body):
            print("Slack signature verification failed", flush=True)
            text_response(self, 401, "Invalid Slack signature")
            return

        if payload.get("type") == "event_callback":
            json_response(self, 200, {"ok": True})
            handle_event(payload.get("event", {}))
            return

        json_response(self, 200, {"ok": True})


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", PORT), SlackHandler)
    print(f"Listening on port {PORT}", flush=True)
    server.serve_forever()
