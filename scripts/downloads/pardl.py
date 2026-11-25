#!/usr/bin/env python3
"""
pardl - parallel downloader for a list of direct URLs (e.g. Real-Debrid links).

Reads URLs from a text file (one per line) and downloads them with high
parallelism to saturate bandwidth:
  * several files at once
  * each file split into multiple connections (HTTP range requests)
  * resume support (re-running skips finished files and finished chunks)

Pure standard library - no pip installs needed. Works on Windows (python.exe),
MSYS2, Linux, macOS.

Usage:
    python pardl.py links.txt
    python pardl.py links.txt -o downloads -j 6 -x 8
    python pardl.py links.txt --help
"""

import argparse
import json
import os
import queue
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import unquote, urlparse

# ----------------------------------------------------------------------------
# global bandwidth counter (for the live speed readout)
# ----------------------------------------------------------------------------
_bytes_total = 0
_bytes_lock = threading.Lock()


def _add_bytes(n):
    global _bytes_total
    with _bytes_lock:
        _bytes_total += n


def _read_bytes():
    with _bytes_lock:
        return _bytes_total


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
USER_AGENT = "pardl/1.0 (+https://localhost)"


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


def make_request(url, headers=None, method="GET"):
    h = {"User-Agent": USER_AGENT}
    if headers:
        h.update(headers)
    return urllib.request.Request(url, headers=h, method=method)


def filename_from(url, resp_headers):
    # Prefer Content-Disposition, fall back to the URL path.
    cd = resp_headers.get("Content-Disposition", "") if resp_headers else ""
    if "filename=" in cd:
        part = cd.split("filename=", 1)[1].strip().strip('";')
        if part.startswith("UTF-8''"):
            part = part[7:]
        name = unquote(part)
        if name:
            return os.path.basename(name)
    path = urlparse(url).path
    name = unquote(os.path.basename(path))
    return name or "download"


def probe(url, timeout):
    """Return (size_or_None, supports_ranges, filename)."""
    size = None
    ranges = False
    name = None
    # A ranged GET for the first byte is the most reliable probe; many CDNs
    # answer HEAD poorly but answer Range correctly.
    try:
        req = make_request(url, headers={"Range": "bytes=0-0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            name = filename_from(url, r.headers)
            status = r.status
            cr = r.headers.get("Content-Range")
            if status == 206 and cr and "/" in cr:
                ranges = True
                try:
                    size = int(cr.split("/")[1])
                except ValueError:
                    size = None
            else:
                # Server ignored the Range header -> no multi-connection.
                cl = r.headers.get("Content-Length")
                size = int(cl) if cl and cl.isdigit() else None
    except urllib.error.HTTPError as e:
        # Range not satisfiable / not supported -> single stream.
        name = filename_from(url, getattr(e, "headers", None))
        cl = e.headers.get("Content-Length") if e.headers else None
        size = int(cl) if cl and cl.isdigit() else None
    return size, ranges, (name or "download")


def preallocate(path, size):
    with open(path, "wb") as f:
        if size:
            f.truncate(size)


def download_range(url, dest, start, end, timeout, retries):
    """Download bytes [start, end] inclusive into dest at the right offset."""
    attempt = 0
    while True:
        try:
            req = make_request(url, headers={"Range": f"bytes={start}-{end}"})
            with urllib.request.urlopen(req, timeout=timeout) as r, \
                    open(dest, "r+b") as f:
                f.seek(start)
                while True:
                    buf = r.read(1024 * 256)
                    if not buf:
                        break
                    f.write(buf)
                    _add_bytes(len(buf))
            return
        except Exception:
            attempt += 1
            if attempt > retries:
                raise
            time.sleep(min(2 ** attempt, 15))


def download_single(url, dest, timeout, retries):
    attempt = 0
    while True:
        try:
            req = make_request(url)
            with urllib.request.urlopen(req, timeout=timeout) as r, \
                    open(dest, "wb") as f:
                while True:
                    buf = r.read(1024 * 256)
                    if not buf:
                        break
                    f.write(buf)
                    _add_bytes(len(buf))
            return
        except Exception:
            attempt += 1
            if attempt > retries:
                raise
            time.sleep(min(2 ** attempt, 15))


def load_progress(path):
    try:
        with open(path) as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_progress(path, done):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(sorted(done), f)
    os.replace(tmp, path)


def download_file(url, out_dir, connections, timeout, retries, log):
    size, ranges, name = probe(url, timeout)
    dest = os.path.join(out_dir, name)

    # already complete?
    if size and os.path.exists(dest) and os.path.getsize(dest) == size \
            and not os.path.exists(dest + ".progress"):
        return ("skip", name, size or 0)

    if not (ranges and size and size > 1024 * 1024):
        # tiny file, unknown size, or no range support -> single stream
        download_single(url, dest, timeout, retries)
        return ("ok", name, os.path.getsize(dest) if os.path.exists(dest) else 0)

    parts = max(1, connections)
    chunk = -(-size // parts)  # ceil
    ranges_list = []
    for i in range(parts):
        start = i * chunk
        if start >= size:
            break
        end = min(start + chunk, size) - 1
        ranges_list.append((start, end))

    progress_path = dest + ".progress"
    done = load_progress(progress_path)
    if not (os.path.exists(dest) and os.path.getsize(dest) == size):
        preallocate(dest, size)
        done = set()  # file was reset, redo everything

    lock = threading.Lock()

    def do_part(i):
        if i in done:
            # account for already-downloaded bytes in the readout
            s, e = ranges_list[i]
            _add_bytes(e - s + 1)
            return
        s, e = ranges_list[i]
        download_range(url, dest, s, e, timeout, retries)
        with lock:
            done.add(i)
            save_progress(progress_path, done)

    with ThreadPoolExecutor(max_workers=len(ranges_list)) as ex:
        futs = [ex.submit(do_part, i) for i in range(len(ranges_list))]
        for f in as_completed(futs):
            f.result()  # surface exceptions

    if os.path.exists(progress_path):
        os.remove(progress_path)
    return ("ok", name, size)


# ----------------------------------------------------------------------------
# reporter thread - live aggregate speed
# ----------------------------------------------------------------------------
def reporter(stop_event, state):
    last_t = time.time()
    last_b = _read_bytes()
    while not stop_event.is_set():
        time.sleep(1.0)
        now = time.time()
        cur = _read_bytes()
        speed = (cur - last_b) / max(now - last_t, 1e-6)
        last_t, last_b = now, cur
        done = state["done"]
        total = state["total"]
        line = (f"\r[{done}/{total}] downloaded {human(cur)}  "
                f"speed {human(speed)}/s   ")
        sys.stderr.write(line)
        sys.stderr.flush()


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description="Parallel downloader for a list of direct URLs.")
    ap.add_argument("listfile", help="text file with one URL per line")
    ap.add_argument("-o", "--out", default="downloads",
                    help="output directory (default: downloads)")
    ap.add_argument("-j", "--jobs", type=int, default=4,
                    help="files to download at once (default: 4)")
    ap.add_argument("-x", "--connections", type=int, default=8,
                    help="connections per file (default: 8)")
    ap.add_argument("-t", "--timeout", type=float, default=30.0,
                    help="socket timeout seconds (default: 30)")
    ap.add_argument("-r", "--retries", type=int, default=5,
                    help="retries per chunk (default: 5)")
    args = ap.parse_args()

    if not os.path.isfile(args.listfile):
        print(f"error: list file not found: {args.listfile}", file=sys.stderr)
        return 2

    with open(args.listfile, encoding="utf-8", errors="replace") as f:
        urls = [ln.strip() for ln in f
                if ln.strip() and not ln.lstrip().startswith("#")]

    if not urls:
        print("error: no URLs found in list file.", file=sys.stderr)
        return 1

    os.makedirs(args.out, exist_ok=True)
    print(f"{len(urls)} URLs | {args.jobs} files x {args.connections} "
          f"connections -> {args.out}/", file=sys.stderr)

    state = {"done": 0, "total": len(urls)}
    stop_event = threading.Event()
    rep = threading.Thread(target=reporter, args=(stop_event, state),
                           daemon=True)
    rep.start()

    failures = []
    done_lock = threading.Lock()

    def worker(u):
        try:
            status, name, size = download_file(
                u, args.out, args.connections, args.timeout, args.retries,
                None)
            with done_lock:
                state["done"] += 1
            return (status, name, u, None)
        except Exception as e:
            with done_lock:
                state["done"] += 1
            return ("fail", None, u, repr(e))

    results = []
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = [ex.submit(worker, u) for u in urls]
        for fut in as_completed(futs):
            results.append(fut.result())

    stop_event.set()
    rep.join(timeout=2)
    sys.stderr.write("\n")

    ok = sum(1 for r in results if r[0] in ("ok", "skip"))
    for status, name, u, err in results:
        if status == "fail":
            failures.append((u, err))

    print(f"\nfinished: {ok}/{len(urls)} succeeded, "
          f"{len(failures)} failed", file=sys.stderr)
    if failures:
        with open("failed.txt", "w", encoding="utf-8") as f:
            for u, err in failures:
                f.write(u + "\n")
        print("failed URLs written to failed.txt "
              "(re-run with that file to retry)", file=sys.stderr)
        for u, err in failures[:10]:
            print(f"  FAIL {u}  ({err})", file=sys.stderr)
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
