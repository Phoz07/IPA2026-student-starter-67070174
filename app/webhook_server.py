"""Part 4 student implementation."""

import json

import logging

import os

from concurrent.futures import ThreadPoolExecutor

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pathlib import Path

from tempfile import TemporaryDirectory

from app.integration import process_request

from app.webex_client import WEBEX_API_BASE, WebexClient

logger = logging.getLogger(__name__)

MAX_BODY = 1_000_000


class WebexEventHandler:
    def __init__(self, client, bot_person_id, processor=None):
        self.client = client
        self.bot_person_id = bot_person_id
        self.processor = processor or process_request

    def _process(self, message):
        mentioned = message.get('mentionedPeople')
        files = message.get('files') or []

        if len(files) > 1:
            return {'status': 'error', 'result': 'multiple_attachments'}

        if not files:
            return self.processor(mentioned, None, self.bot_person_id)

        with TemporaryDirectory() as directory:
            path = Path(directory) / 'request.yaml'
            path.write_bytes(self.client.download_file(files[0]))
            return self.processor(mentioned, path, self.bot_person_id)

    def handle_event(self, event):
        if not isinstance(event, dict):
            return None
        if event.get('resource') != 'messages' or event.get('event') != 'created':
            return None
        data = event.get('data')
        if not isinstance(data, dict):
            return None
        message_id = data.get('id')
        if not isinstance(message_id, str) or not message_id:
            return None
        if data.get('personId') == self.bot_person_id:
            return None

        message = self.client.get_message(message_id)
        if message.get('personId') == self.bot_person_id:
            return None
        room_id = message.get('roomId')
        if not room_id:
            return None

        try:
            result = self._process(message)
        except Exception:
            logger.exception('request processing failed')
            result = {'status': 'error', 'result': 'backend_failed'}

        self.client.send_message(room_id, json.dumps(result))
        return result


def make_http_handler(submit_event):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body):
            payload = json.dumps(body).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            if self.path == '/health':
                self._send(200, {'status': 'ok', 'result': 'healthy'})
            else:
                self._send(404, {'status': 'error', 'result': 'not_found'})

        def do_POST(self):
            if self.path != '/webhook':
                self._send(404, {'status': 'error', 'result': 'not_found'})
                return

            invalid = {'status': 'error', 'result': 'invalid_event'}
            try:
                length = int(self.headers.get('Content-Length', ''))
            except ValueError:
                length = 0
            if not 1 <= length <= MAX_BODY:
                self._send(400, invalid)
                return

            try:
                event = json.loads(self.rfile.read(length))
            except (ValueError, UnicodeDecodeError):
                self._send(400, invalid)
                return
            if not isinstance(event, dict):
                self._send(400, invalid)
                return

            submit_event(event)
            self._send(200, {'status': 'ok', 'result': 'accepted'})

        def log_message(self, format, *args):
            logger.info('%s - %s', self.address_string(), format % args)

    return Handler


def main():
    import requests

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )

    client = WebexClient()
    response = requests.get(
        f'{WEBEX_API_BASE}/people/me',
        headers=client.headers,
        timeout=10,
    )
    response.raise_for_status()
    bot_person_id = response.json()['id']

    handler = WebexEventHandler(client, bot_person_id)
    # A single worker keeps router changes strictly sequential.
    executor = ThreadPoolExecutor(max_workers=1)

    def run(event):
        try:
            handler.handle_event(event)
        except Exception:
            logger.exception('event handling failed')

    def submit_event(event):
        executor.submit(run, event)

    host = os.environ.get('WEBHOOK_HOST', '0.0.0.0')
    port = int(os.environ.get('WEBHOOK_PORT', '8000'))
    server = ThreadingHTTPServer((host, port), make_http_handler(submit_event))
    logger.info('listening on %s:%s', host, port)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        executor.shutdown(wait=False)


if __name__ == "__main__":
    main()
