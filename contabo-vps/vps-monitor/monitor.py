"""Acronous VPS monitor — tiny stdlib-only HTTP service for the private dashboard.

Exposes real CPU / memory / disk / Docker-container stats to
dashboard.acronous.com (which shows them in its VPS card).

- Internal port only (never published on the host): dashboard reaches it as
  http://vps-monitor:9100/metrics over the compose network.
- GET /health        → {ok:true}            (public, for Docker healthcheck)
- GET /metrics       → {at, cpu, mem, disk, docker, uptime_s}
                       requires: Authorization: Bearer <VPS_METRICS_TOKEN>
Everything else → 404. No dependencies beyond the Python standard library.
"""
import hmac
import json
import os
import socket
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.getenv("PORT", "9100"))
TOKEN = os.getenv("VPS_METRICS_TOKEN", "")
STARTED = time.time()


def read_cpu_times():
    with open("/proc/stat") as f:
        parts = f.readline().split()[1:8]
    vals = [int(x) for x in parts]
    total = sum(vals)
    idle = vals[3] + vals[4]  # idle + iowait
    return total, idle


def cpu_pct():
    t0, i0 = read_cpu_times()
    time.sleep(0.5)
    t1, i1 = read_cpu_times()
    dt, di = t1 - t0, i1 - i0
    if dt <= 0:
        return 0.0
    return round((1 - di / dt) * 100, 1)


def mem_info():
    info = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, _, v = line.partition(":")
            info[k.strip()] = int(v.strip().split()[0])  # kB
    total = info.get("MemTotal", 0)
    avail = info.get("MemAvailable", info.get("MemFree", 0))
    used = max(total - avail, 0)
    return {
        "total_mb": round(total / 1024),
        "used_mb": round(used / 1024),
        "pct": round(used / total * 100, 1) if total else 0.0,
    }


def disk_info(path="/"):
    st = os.statvfs(path)
    total = st.f_blocks * st.f_frsize
    free = st.f_bavail * st.f_frsize
    used = total - free
    return {
        "total_gb": round(total / 1073741824, 1),
        "used_gb": round(used / 1073741824, 1),
        "pct": round(used / total * 100, 1) if total else 0.0,
    }


def docker_ps():
    """List containers via the Docker socket (read-only GET). None if unavailable."""
    sock_path = "/var/run/docker.sock"
    if not os.path.exists(sock_path):
        return None
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect(sock_path)
        s.sendall(b"GET /v1.41/containers/json?all=1 HTTP/1.0\r\nHost: localhost\r\n\r\n")
        chunks = []
        while True:
            data = s.recv(65536)
            if not data:
                break
            chunks.append(data)
        s.close()
        body = b"".join(chunks).split(b"\r\n\r\n", 1)[1]
        # Handle chunked transfer encoding from the daemon.
        if body[:1] not in (b"[", b"{"):
            out = b""
            rest = body
            while rest:
                line, _, rest = rest.partition(b"\r\n")
                try:
                    n = int(line.strip().split(b";")[0], 16)
                except ValueError:
                    break
                if n == 0:
                    break
                out += rest[:n]
                rest = rest[n + 2 :]
            body = out
        result = []
        for c in json.loads(body or "[]"):
            names = c.get("Names") or []
            result.append({
                "name": (names[0].lstrip("/") if names else (c.get("Id") or "")[:12]),
                "image": c.get("Image"),
                "state": c.get("State"),
                "status": c.get("Status"),
            })
        return result
    except Exception:
        return None


class Handler(BaseHTTPRequestHandler):
    server_version = "VPSMonitor/1.0"

    def log_message(self, *args):  # quiet: docker logs stay clean
        pass

    def send_json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        if not TOKEN:
            return False
        got = self.headers.get("Authorization") or ""
        return hmac.compare_digest(got, f"Bearer {TOKEN}")

    def do_GET(self):
        if self.path == "/health":
            self.send_json(200, {"ok": True, "service": "vps-monitor"})
            return
        if self.path == "/metrics":
            if not self.authorized():
                self.send_json(401, {"error": "Unauthorized"})
                return
            self.send_json(200, {
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "uptime_s": int(time.time() - STARTED),
                "cpu": {"pct": cpu_pct()},
                "mem": mem_info(),
                "disk": disk_info("/"),
                "docker": docker_ps(),
            })
            return
        self.send_json(404, {"error": "Not found"})


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
