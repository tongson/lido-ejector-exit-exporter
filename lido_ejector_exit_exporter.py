from __future__ import annotations
import time
import argparse
import prometheus_client
from prometheus_client import REGISTRY
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
from functools import partial
import multiprocessing as mp
from multiprocessing.sharedctypes import Synchronized
from typing import Any


def read_args() -> argparse.Namespace:
    try:
        parser = argparse.ArgumentParser(description="Exporter for notifying exits.")
    except Exception as e:
        e.add_note("\n Exception at read_args()")
        raise SystemExit("Error parsing arguments.")
    else:
        parser.add_argument(
            "--webhook_port",
            metavar="WEBHOOK_PORT",
            type=int,
            default=8099,
            help="The listening port for the webhook. Default is 8099.",
        )
        parser.add_argument(
            "--exporter_port",
            metavar="EXPORTER_PORT",
            type=int,
            default=9099,
            help="The listening port for exporting the metrics. Default is 9099.",
        )
        parser.add_argument(
            "--freq",
            metavar="SEC",
            type=int,
            default=300,
            help="Update frequency in seconds. Default is 300 seconds (5 minutes).",
        )
        return parser.parse_args()


class Hook(BaseHTTPRequestHandler):
    def __init__(self, notify: Any, *args: Any, **kwargs: Any):
        self.notify = notify
        super().__init__(*args, **kwargs)

    def _set_headers(self) -> None:
        self.send_response(202)
        self.send_header("Content-type", "text/html")
        self.end_headers()

    def do_GET(self) -> None:
        self._set_headers()

    def do_HEAD(self) -> None:
        self._set_headers()

    def do_POST(self) -> None:
        content_length = int(self.headers["Content-Length"])
        post_data = self.rfile.read(content_length)
        self._set_headers()
        post = post_data.decode("utf-8")
        current_timestamp = datetime.now()
        formatted_timestamp = current_timestamp.strftime("%Y-%m-%d %H:%M:%S")
        self.notify.value = int(1)
        print(f"{post}")
        with open("lido_ejector_exit_exporter.log", "a") as nlog:
            nlog.write(formatted_timestamp)
            nlog.write("\n")
            nlog.write(post)
            nlog.write("\n")


def webhook(notify: Synchronized[int], args: argparse.Namespace) -> None:
    handler = partial(Hook, notify)
    httpd = HTTPServer(("127.0.0.1", args.webhook_port), handler)
    try:
        httpd.serve_forever()
    except Exception as e:
        e.add_note("\n Exception at webhook()")
        raise SystemExit("Error starting webhook HTTP server.")

def exporter(notify: Synchronized[int], args: argparse.Namespace) -> None:
    for coll in list(REGISTRY._collector_to_names.keys()):
        REGISTRY.unregister(coll)
    try:
        prometheus_client.start_http_server(args.exporter_port)
    except Exception as e:
        e.add_note("\n Exception at exporter()")
        raise SystemExit("Error starting exporter HTTP server.")
    else:
        register = prometheus_client.Gauge(
            "lido_ejector_exit",
            "Lido Ejector Exit",
        )
        while True:
            if int(notify.value) > 0:
                register.set(float(1))
            else:
                register.set(float(0))
            notify.value = int(0)
            time.sleep(args.freq)


if __name__ == "__main__":
    mp.set_start_method("fork")
    notify: Synchronized[int] = mp.Value("i", 0)
    cmd_args: argparse.Namespace = read_args()
    p_webhook = mp.Process(target=webhook, args=(notify, cmd_args))
    p_exporter = mp.Process(target=exporter, args=(notify, cmd_args))
    p_webhook.start()
    p_exporter.start()
    p_webhook.join()
    p_exporter.join()
