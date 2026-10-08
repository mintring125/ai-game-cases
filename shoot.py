#!/usr/bin/env python3
"""Capture one public post into an image file.

Usage:
  python3 shoot.py URL OUTPUT

OUTPUT may end in .jpg, .jpeg, .webp, or .png. JPEG/WebP are compressed
to stay under about 250 KB.

Uses a fresh temporary Chrome profile every run (logged out; no existing
cookies or desktop session). Viewport is 430x932.

If the page is a login wall, blank, or error, the script retries once with
a longer wait. If that still fails it uses the page og:image. For x.com or
twitter.com status URLs it then tries the public embed
https://platform.twitter.com/embed/Tweet.html?id=<id>.

Prints one JSON object to stdout:
  {"status":"capture"|"og:image"|"embed", "path":"...", "bytes":N}
or, on failure, exits 2 with
  {"status":"fail", "reason":"..."}
"""

from __future__ import annotations

import base64
import html
import io
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

CHROME = os.environ.get("CHROME", "/usr/bin/google-chrome")
VIEW_W = 430
VIEW_H = 932
MAX_BYTES = 250 * 1024
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

LOGIN_MARKERS = (
    "log in to instagram",
    "log into instagram",
    "sign up for instagram",
    "log in to threads to",
    "join threads to see",
    "see this thread on the app",
    "log in to x",
    "sign in to x",
    "log in to twitter",
    "sign in to twitter",
    "this page isn't available",
    "sorry, this page isn't available",
    "this account is private",
    "page not found",
    "something went wrong",
    "please log in to continue",
    "log in to continue",
    "continue with google",
    "로그인이 필요합니다",
    "로그인하여",
    "access to x.com was denied",
    "you don't have authorization",
    "http error 403",
    "http error 404",
    "access denied",
    "just a moment",
)


class Ws:
    def __init__(self, host: str, port: int, path: str):
        self.sock = socket.create_connection((host, port), timeout=30)
        self.sock.settimeout(60)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("websocket handshake failed")
            buf += chunk
        status = buf.split(b"\r\n", 1)[0]
        if b" 101 " not in status:
            raise RuntimeError("websocket upgrade rejected: " + status.decode("latin1", "replace"))
        self._extra = buf.split(b"\r\n\r\n", 1)[1]

    def _recvn(self, n: int) -> bytes:
        buf = self._extra
        self._extra = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise RuntimeError("websocket closed")
            buf += chunk
        self._extra = buf[n:]
        return buf[:n]

    def send_text(self, text: str) -> None:
        payload = text.encode()
        mask = os.urandom(4)
        n = len(payload)
        hdr = bytearray([0x81])
        if n < 126:
            hdr.append(0x80 | n)
        elif n < 65536:
            hdr.append(0x80 | 126)
            hdr.extend(struct.pack(">H", n))
        else:
            hdr.append(0x80 | 127)
            hdr.extend(struct.pack(">Q", n))
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(hdr) + mask + masked)

    def recv_text(self) -> str:
        parts: list[bytes] = []
        while True:
            b0, b1 = self._recvn(2)
            opcode = b0 & 0x0F
            fin = b0 & 0x80
            ln = b1 & 0x7F
            if ln == 126:
                ln = struct.unpack(">H", self._recvn(2))[0]
            elif ln == 127:
                ln = struct.unpack(">Q", self._recvn(8))[0]
            if b1 & 0x80:
                mask = self._recvn(4)
                raw = bytes(b ^ mask[i % 4] for i, b in enumerate(self._recvn(ln)))
            else:
                raw = self._recvn(ln)
            if opcode == 8:
                raise RuntimeError("websocket closed by peer")
            if opcode == 9:
                # pong
                payload = raw
                n = len(payload)
                hdr = bytearray([0x8A, 0x80 | n]) if n < 126 else bytearray([0x8A])
                mask = os.urandom(4)
                if n >= 126:
                    hdr.append(0x80 | 126)
                    hdr.extend(struct.pack(">H", n))
                masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
                self.sock.sendall(bytes(hdr) + mask + masked)
                continue
            if opcode in (0, 1, 2):
                parts.append(raw)
            if fin and opcode != 9:
                break
        return b"".join(parts).decode("utf-8", "replace")


class Cdp:
    def __init__(self, ws: Ws):
        self.ws = ws
        self.n = 0

    def call(self, method: str, params: dict | None = None, session: str | None = None, timeout: float = 45) -> dict:
        self.n += 1
        mid = self.n
        msg = {"id": mid, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        self.ws.send_text(json.dumps(msg))
        deadline = time.time() + timeout
        while True:
            self.ws.sock.settimeout(max(1, deadline - time.time()))
            data = json.loads(self.ws.recv_text())
            if data.get("id") == mid:
                if "error" in data:
                    raise RuntimeError(f"{method}: {data['error']}")
                return data.get("result") or {}


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


DISMISS_JS = r"""
(() => {
  const junk = /cookie|privacy|terms of use|개인정보|쿠키|consent|gdpr/i;
  const closer = /^(x|×|✕)$|close|닫기|dismiss|reject|decline|거부|essential|필수만|not now|나중에/i;
  const removed = [];
  document.querySelectorAll('[role="dialog"], [aria-modal="true"], div, section').forEach((el) => {
    if (removed.length > 8) return;
    const text = (el.innerText || '').slice(0, 400);
    if (!junk.test(text)) return;
    const style = getComputedStyle(el);
    const fixed = style.position === 'fixed' || style.position === 'sticky' || el.getAttribute('role') === 'dialog';
    if (!fixed && el.getAttribute('role') !== 'dialog') return;
    const btns = el.querySelectorAll('button, [role="button"], a');
    let clicked = false;
    btns.forEach((b) => {
      const label = ((b.getAttribute('aria-label') || '') + ' ' + (b.innerText || '')).trim();
      if (closer.test(label)) { b.click(); clicked = true; }
    });
    if (!clicked) el.remove();
    removed.push(text.slice(0, 60));
  });
  return removed.join(' | ').slice(0, 300);
})()
"""

TEXT_JS = r"""
(() => {
  const t = document.body ? document.body.innerText : '';
  return t.replace(/\s+/g, ' ').trim().slice(0, 1800);
})()
"""


def looks_like_wall(text: str) -> str | None:
    low = (text or "").lower()
    compact = re.sub(r"\s+", " ", low).strip()
    if len(compact) < 40:
        return "blank or nearly empty page"
    for marker in LOGIN_MARKERS:
        if marker in compact:
            return "login or error page (" + marker + ")"
    # A page that is mostly a login form: many login words, little else.
    login_hits = len(re.findall(r"\blog in\b|\bsign up\b|\bpassword\b", compact))
    words = compact.split()
    if login_hits >= 2 and len(words) < 80:
        return "login form with little post text"
    return None


def trim_empty_edges(im):
    """Cut trailing blank margin so a short post fills the frame."""
    g = im.convert("L")
    w, h = g.size
    px = g.load()

    def row_ink(y):
        ink = 0
        for x in range(0, w, 3):
            if px[x, y] < 242:
                ink += 1
                if ink > 4:
                    return True
        return False

    bottom = h - 1
    for y in range(h - 1, int(h * 0.25), -1):
        if row_ink(y):
            bottom = y
            break
    bottom = min(h - 1, bottom + 28)
    if bottom < h - 12:
        im = im.crop((0, 0, w, bottom + 1))
    return im


def save_image(png_or_bytes: bytes, dest: str, already_image: bool = False) -> int:
    from PIL import Image

    im = Image.open(io.BytesIO(png_or_bytes))
    im = im.convert("RGB")
    im = trim_empty_edges(im)
    # Drop a very tall capture to the viewport so the post fills the frame.
    max_h = int(im.width * (VIEW_H / VIEW_W) * 1.05)
    if im.height > max_h + 8:
        im = im.crop((0, 0, im.width, max_h))
    ext = os.path.splitext(dest)[1].lower()
    os.makedirs(os.path.dirname(os.path.abspath(dest)) or ".", exist_ok=True)
    if ext == ".png":
        im.save(dest, "PNG", optimize=True)
        return os.path.getsize(dest)
    if ext == ".webp":
        for q in (70, 58, 46, 36):
            im.save(dest, "WEBP", quality=q, method=4)
            if os.path.getsize(dest) <= MAX_BYTES:
                break
        return os.path.getsize(dest)
    # jpeg
    for q, scale in ((72, 1), (62, 1), (54, 1), (58, 0.85), (50, 0.75)):
        out = im
        if scale != 1:
            out = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.Resampling.LANCZOS)
        out.save(dest, "JPEG", quality=q, optimize=True, progressive=True)
        if os.path.getsize(dest) <= MAX_BYTES:
            break
    return os.path.getsize(dest)


def image_is_blank(data: bytes) -> bool:
    from PIL import Image

    im = Image.open(io.BytesIO(data)).convert("L").resize((32, 32))
    lo, hi = im.getextrema()
    return (hi - lo) < 14


def fetch_bytes(url: str, timeout: int = 30, ua: str | None = None) -> tuple[bytes, str]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": ua or UA, "Accept": "*/*", "Accept-Language": "en"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        ctype = resp.headers.get("Content-Type", "")
        return resp.read(), ctype


def og_image_url(page_url: str) -> str | None:
    raw = None
    for ua in ("facebookexternalhit/1.1", "Twitterbot/1.0", UA):
        try:
            raw, _ = fetch_bytes(page_url, timeout=30, ua=ua)
        except Exception:
            continue
        if b"og:image" in raw or b"twitter:image" in raw:
            break
    if raw is None:
        return None
    text = raw.decode("utf-8", "replace")
    patterns = [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            url = html.unescape(m.group(1)).strip()
            if url.startswith("//"):
                url = "https:" + url
            if url.startswith("http"):
                return url
    return None


def x_status_id(url: str) -> str | None:
    m = re.search(r"(?:x\.com|twitter\.com)/[^/]+/status(?:es)?/(\d+)", url)
    return m.group(1) if m else None


def is_x(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host.endswith("x.com") or host.endswith("twitter.com")


def instagram_embed(url: str) -> str | None:
    m = re.search(r"instagram\.com/(?:p|reel|tv)/([^/?#]+)", url, re.I)
    if not m:
        return None
    return "https://www.instagram.com/p/%s/embed/captioned/" % m.group(1)


class Browser:
    def __init__(self):
        self.profile = tempfile.mkdtemp(prefix="shoot-chrome-")
        self.port = free_port()
        self.proc = subprocess.Popen(
            [
                CHROME,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-extensions",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-sync",
                "--disable-background-networking",
                "--hide-scrollbars",
                "--lang=ko",
                "--window-size=%d,%d" % (VIEW_W, VIEW_H),
                "--user-data-dir=" + self.profile,
                "--remote-debugging-port=%d" % self.port,
                "--remote-allow-origins=*",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.cdp = None
        self.session = None
        deadline = time.time() + 20
        last = None
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError("chrome exited early")
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/json/version" % self.port, timeout=2) as resp:
                    info = json.loads(resp.read().decode())
                wsurl = info["webSocketDebuggerUrl"]
                u = urlparse(wsurl)
                self.cdp = Cdp(Ws(u.hostname, u.port, u.path))
                break
            except Exception as exc:
                last = exc
                time.sleep(0.2)
        if not self.cdp:
            raise RuntimeError("devtools not ready: %s" % last)
        created = self.cdp.call("Target.createTarget", {"url": "about:blank"})
        attached = self.cdp.call(
            "Target.attachToTarget",
            {"targetId": created["targetId"], "flatten": True},
        )
        self.session = attached["sessionId"]
        self.cdp.call("Page.enable", session=self.session)
        self.cdp.call(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": VIEW_W,
                "height": VIEW_H,
                "deviceScaleFactor": 2,
                "mobile": False,
            },
            session=self.session,
        )

    def close(self):
        try:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
        finally:
            shutil.rmtree(self.profile, ignore_errors=True)

    def screenshot(self, url: str, wait_s: float) -> tuple[bytes, str, str | None]:
        self.cdp.call("Page.navigate", {"url": url}, session=self.session, timeout=30)
        time.sleep(wait_s)
        dismissed = ""
        try:
            dismissed = str(
                self.cdp.call(
                    "Runtime.evaluate",
                    {"expression": DISMISS_JS, "returnByValue": True},
                    session=self.session,
                ).get("result", {}).get("value", "")
            )
        except Exception:
            dismissed = ""
        time.sleep(0.6)
        text = ""
        try:
            text = str(
                self.cdp.call(
                    "Runtime.evaluate",
                    {"expression": TEXT_JS, "returnByValue": True},
                    session=self.session,
                ).get("result", {}).get("value", "")
            )
        except Exception:
            text = ""
        shot = self.cdp.call(
            "Page.captureScreenshot",
            {"format": "png", "fromSurface": True},
            session=self.session,
            timeout=40,
        )
        png = base64.b64decode(shot["data"])
        reason = looks_like_wall(text)
        if reason is None and image_is_blank(png):
            reason = "blank image"
        note = text[:180]
        if dismissed:
            note = ("dismissed: " + dismissed + " | " + note)[:300]
        return png, note, reason


def try_og(page_url: str, dest: str) -> int | None:
    img = og_image_url(page_url)
    if not img:
        return None
    try:
        data, ctype = fetch_bytes(img, timeout=30)
    except Exception:
        return None
    if "image" not in ctype and not data[:8].startswith(b"\x89PNG") and not data[:2] == b"\xff\xd8":
        # still try pillow; some CDNs omit the type
        pass
    if len(data) < 4000:
        return None
    try:
        if image_is_blank(data):
            return None
        return save_image(data, dest)
    except Exception:
        return None


def capture(url: str, dest: str) -> dict:
    browser = Browser()
    try:
        png, note, reason = browser.screenshot(url, wait_s=4.5)
        hard = reason and any(s in (reason or "") for s in ("403", "404", "denied"))
        # A hard error page will not improve with a longer wait. The second try
        # is the public embed or og:image below. Soft login walls get one longer wait.
        if reason and not hard:
            png2, note2, reason2 = browser.screenshot(url, wait_s=9.0)
            if not reason2:
                png, note, reason = png2, note2, None
            else:
                reason = reason2
                note = note2
        if not reason:
            nbytes = save_image(png, dest)
            return {"status": "capture", "path": dest, "bytes": nbytes, "note": note[:160]}
    finally:
        browser.close()

    # Fallbacks. Do not keep a login-wall screenshot.
    alt_urls = []
    ig = instagram_embed(url)
    if ig:
        alt_urls.append(("embed", ig))
    sid = x_status_id(url) if is_x(url) else None
    if sid:
        alt_urls.append(("embed", "https://platform.twitter.com/embed/Tweet.html?id=%s" % sid))

    for kind, alt in alt_urls:
        browser = Browser()
        try:
            png, note, reason2 = browser.screenshot(alt, wait_s=6.0)
            if reason2:
                png, note, reason2 = browser.screenshot(alt, wait_s=10.0)
            if not reason2:
                nbytes = save_image(png, dest)
                return {"status": kind, "path": dest, "bytes": nbytes, "note": note[:160], "via": alt}
            reason = reason2 or reason
        finally:
            browser.close()

    n = try_og(url, dest)
    if n:
        return {"status": "og:image", "path": dest, "bytes": n, "reason": reason}
    for _kind, alt in alt_urls:
        n = try_og(alt, dest)
        if n:
            return {"status": "og:image", "path": dest, "bytes": n, "reason": reason}

    return {"status": "fail", "reason": reason or "unusable capture"}


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: python3 shoot.py URL OUTPUT", file=sys.stderr)
        return 1
    url, dest = sys.argv[1], sys.argv[2]
    try:
        result = capture(url, dest)
    except Exception as exc:
        result = {"status": "fail", "reason": str(exc)}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("status") != "fail" else 2


if __name__ == "__main__":
    sys.exit(main())
