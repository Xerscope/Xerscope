"""xerscope-remote: one container, three processes, configured by environment variables.

    tailscaled (userspace)  ->  tailscale funnel  ->  Caddy (:8080, basic auth)  ->  xerscope (:8501)

Nothing is published on the host: tailscaled keeps an outbound connection to Tailscale,
visitors reach https://<TS_HOSTNAME>.<tailnet>.ts.net through it, Caddy asks for a
username and password, xerscope listens on the container's loopback only.

Variables
    TS_AUTHKEY               auth key of a tagged node (Funnel allowed for the tag in the ACL)
    TS_HOSTNAME              node name, default "xerscope"
    XERSCOPE_USER            login, default "xerscope"
    XERSCOPE_PASSWORD_HASH   bcrypt hash (caddy hash-password), or
    XERSCOPE_PASSWORD        the password itself, hashed at start (weaker: readable in the UI)
    XERSCOPE_DATA            folder of XER exports, default /data (mount it read-only)
    XERSCOPE_BASELINE        optional baseline XER
    XERSCOPE_PATH            optional secret URL prefix, e.g. /<random>: Funnel then exposes only
                             https://<host>.<tailnet>.ts.net/<random>/ (keep the trailing slash:
                             the page's relative asset URLs must resolve under the prefix) and
                             Tailscale answers 404 to everything else before it reaches the
                             container (internet scanners probe "/", "/.env", "/wp-admin"...).
                             Tailscale strips the prefix before proxying, so the app itself is
                             unaware of it. Letters, digits, - and _ only.

Volumes
    /data                    the exports
    /var/lib/tailscale       the node's state, so it keeps its identity across restarts. The
                             state itself lives in the "node" subfolder, created by the
                             container's own user: tailscaled chmods its state directory to
                             0700, which fails on a bind mount owned by someone else (a NAS
                             share) but not on a folder it created.

Runs as PID 1 without a shell (distroless): starts the processes, restarts one that dies
(5 s back-off), stops all of them on SIGTERM.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

SOCK = "/tmp/tailscaled.sock"
STATE = Path(os.environ.get("TS_STATE_DIR", "/var/lib/tailscale")) / "node"
CADDYFILE = Path("/tmp/caddy/Caddyfile")
TS = os.environ.get("TAILSCALE_BIN", "tailscale")
TSD = os.environ.get("TAILSCALED_BIN", "tailscaled")
CADDY = os.environ.get("CADDY_BIN", "caddy")
PYTHON = os.environ.get("XERSCOPE_PYTHON", sys.executable)


def url_path() -> str:
    """XERSCOPE_PATH normalised to "/..." or "" (whole site)."""
    p = os.environ.get("XERSCOPE_PATH", "").strip().strip("/")
    if not p:
        return ""
    if not all(c.isalnum() or c in "-_" for c in p):
        log("XERSCOPE_PATH may only contain letters, digits, - and _")
        sys.exit(2)
    return "/" + p


def log(msg: str) -> None:
    print(f"[remote] {msg}", flush=True)


def need(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        log(f"{name} is not set: see the image documentation")
        sys.exit(2)
    return v


def password_hash() -> str:
    h = os.environ.get("XERSCOPE_PASSWORD_HASH", "").strip()
    if h:
        return h
    pw = need("XERSCOPE_PASSWORD")
    if len(pw) < 12:
        log("XERSCOPE_PASSWORD must be at least 12 characters")
        sys.exit(2)
    out = subprocess.run([CADDY, "hash-password", "--plaintext", pw], capture_output=True, text=True, check=True)
    return out.stdout.strip()


def write_caddyfile() -> None:
    user = os.environ.get("XERSCOPE_USER", "xerscope").strip() or "xerscope"
    CADDYFILE.parent.mkdir(parents=True, exist_ok=True)
    CADDYFILE.write_text(
        # default_bind keeps the listener on loopback; the site address stays ":8080" because
        # a host in it ("127.0.0.1:8080") also filters the Host header, and Funnel requests
        # arrive with Host: <node>.<tailnet>.ts.net (Caddy then answers nothing, status 0).
        "{\n    auto_https off\n    default_bind 127.0.0.1\n}\n\n:8080 {\n"
        f"    basic_auth {{\n        {user} {password_hash()}\n    }}\n"
        "    reverse_proxy 127.0.0.1:8501\n    log {\n        output stdout\n"
        # the Referer carries the full URL, i.e. XERSCOPE_PATH: keep it out of the logs
        "        format filter {\n            wrap console\n            request>headers>Referer delete\n        }\n    }\n}\n"
    )


def ts(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run([TS, "--socket", SOCK, *args], capture_output=True, text=True, check=check)


def tailscale_up(authkey: str, hostname: str) -> None:
    for _ in range(60):  # tailscaled needs a moment to open its socket
        if ts("status", check=False).returncode in (0, 1):
            break
        time.sleep(0.5)
    up = ts("up", "--authkey", authkey, "--hostname", hostname, "--advertise-tags=tag:xerscope", "--accept-routes=false",
            check=False)  # never raise: a CalledProcessError would print the auth key
    if up.returncode != 0:
        log(f"tailscale up failed: {(up.stderr or up.stdout).strip()}")
        sys.exit(1)
    ts("serve", "reset", check=False)  # the serve config persists in the state dir: drop old handlers
    path = url_path()
    if path:  # only this prefix is published. Tailscale strips it before proxying, so Caddy and
        # Streamlit still see "/": the prefix exists only in the public URL.
        ts("funnel", "--bg", "--set-path", path, "8080")
    else:
        ts("funnel", "--bg", "8080")  # https://<hostname>.<tailnet>.ts.net -> Caddy
    status = ts("funnel", "status", check=False)
    log(status.stdout.strip() or status.stderr.strip())
    if path:
        log(f"hand out the URL WITH its trailing slash: https://{hostname}.<tailnet>.ts.net{path}/")


class Procs:
    def __init__(self) -> None:
        self.specs: dict[str, list[str]] = {}
        self.procs: dict[str, subprocess.Popen] = {}
        self.last: dict[str, float] = {}
        self.stopping = False

    def start(self, name: str, argv: list[str]) -> None:
        self.specs[name] = argv
        self.procs[name] = subprocess.Popen(argv)
        self.last[name] = time.monotonic()
        log(f"started {name} (pid {self.procs[name].pid})")

    def stop(self, *_: object) -> None:
        self.stopping = True
        for name, p in self.procs.items():
            if p.poll() is None:
                log(f"stopping {name}")
                p.terminate()

    def watch(self) -> int:
        while True:
            time.sleep(1)
            for name, p in list(self.procs.items()):
                code = p.poll()
                if code is None:
                    continue
                if self.stopping:
                    continue
                wait = max(0.0, 5 - (time.monotonic() - self.last[name]))
                log(f"{name} exited with {code}; restarting in {wait:.0f} s")
                time.sleep(wait)
                self.start(name, self.specs[name])
            if self.stopping and all(p.poll() is not None for p in self.procs.values()):
                return 0


def main() -> int:
    authkey = need("TS_AUTHKEY")
    hostname = os.environ.get("TS_HOSTNAME", "xerscope").strip() or "xerscope"
    STATE.mkdir(parents=True, exist_ok=True)
    write_caddyfile()
    procs = Procs()
    signal.signal(signal.SIGTERM, procs.stop)
    signal.signal(signal.SIGINT, procs.stop)
    try:
        return run(procs, authkey, hostname)
    finally:
        procs.stop()  # whatever happened, no child outlives the supervisor
        for p in procs.procs.values():
            p.wait(timeout=10)


def run(procs: Procs, authkey: str, hostname: str) -> int:
    procs.start(
        "tailscaled",
        # --statedir, not --state: it is also tailscaled's "var root", where the ts.net TLS
        # certificate for Funnel is kept. With --state alone every Funnel handshake fails with
        # "no TailscaleVarRoot" and the public name never resolves.
        [TSD, "--tun=userspace-networking", f"--statedir={STATE}", f"--socket={SOCK}", "--port=0"],
    )
    tailscale_up(authkey, hostname)
    # Streamlit itself, not the `xerscope app` wrapper: a wrapper would not pass SIGTERM on
    from xerscope.cli import APP_PATH

    os.environ.setdefault("XERSCOPE_DATA", "/data")
    os.chdir(APP_PATH.parent)  # the packaged .streamlit/config.toml (theme, localhost) applies
    app = [PYTHON, "-m", "streamlit", "run", str(APP_PATH), "--server.address", "127.0.0.1", "--server.port", "8501",
           "--browser.gatherUsageStats", "false"]  # fmt: skip
    # No --server.baseUrlPath: Funnel strips XERSCOPE_PATH before proxying, Streamlit lives at "/".
    procs.start("xerscope", app)
    procs.start("caddy", [CADDY, "run", "--config", str(CADDYFILE), "--adapter", "caddyfile"])
    return procs.watch()


if __name__ == "__main__":
    sys.exit(main())
