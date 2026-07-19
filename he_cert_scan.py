#!/usr/bin/env python

import argparse
import ipaddress
import json
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

API = "https://bgp.he.net/certs/api/ip-search"
HEADERS = {"User-Agent": "Mozilla/5.0"}
REQUEST_DELAY = 0.4   # pause between requests
MAX_RETRIES = 3


def query(prefix: str) -> dict:
    # Query the API for a single CIDR prefix and return the parsed JSON.
    # Retries with backoff on network errors.
    url = f"{API}?ip={urllib.parse.quote(prefix, safe='')}"
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            wait = attempt * 1.5
            print(f"  ! error on {prefix} ({e}), retry {attempt}/{MAX_RETRIES} in {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"Failed to fetch {prefix} after {MAX_RETRIES} attempts")


def split_prefix(net):
    # Split a network into its two child halves (prefix length + 1).
    new_prefix = net.prefixlen + 1
    return list(net.subnets(new_prefix=new_prefix))


def scan(cidr: str, max_depth: int = 12):
    # Recursively query a CIDR range. If a query reports more results
    # than it returned, split the range in half and query each half
    # separately, continuing until each sub-range is fully returned
    # or max_depth is reached. Results are merged and deduplicated by IP.
    root = ipaddress.ip_network(cidr)
    results = {}
    stats = {"queries": 0, "capped_leaves": 0, "leaves": 0}

    def recurse(net, depth):
        stats["queries"] += 1
        prefix_str = str(net)
        print(f"[{'  '*depth}] querying {prefix_str} ...", file=sys.stderr)
        data = query(prefix_str)
        time.sleep(REQUEST_DELAY)

        entries = data.get("entries", [])
        has_more = data.get("has_more", False)

        # merge this batch into the running result set
        for e in entries:
            ip = e["ip"]
            results.setdefault(ip, set()).update(e.get("hostnames", []))

        if has_more and depth < max_depth:
            # more results exist than were returned; narrow the range and recurse
            children = split_prefix(net)
            if len(children) == 2:
                for child in children:
                    recurse(child, depth + 1)
                return

        # base case: either the range returned everything, or we hit max_depth
        stats["leaves"] += 1
        if has_more:
            stats["capped_leaves"] += 1
            print(f"  ! WARNING: {prefix_str} still capped at max_depth "
                  f"({len(entries)} entries) - results incomplete here", file=sys.stderr)

    recurse(root, 0)
    return results, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cidr")
    ap.add_argument("--out", default=None)
    ap.add_argument("--max-depth", type=int, default=12)
    args = ap.parse_args()

    results, stats = scan(args.cidr, max_depth=args.max_depth)

    total_hostnames = sum(len(v) for v in results.values())
    print(f"\nDone. Queries made: {stats['queries']}, leaf ranges: {stats['leaves']}, "
          f"still-capped leaves: {stats['capped_leaves']}", file=sys.stderr)
    print(f"Unique IPs found: {len(results)}, unique hostname entries: {total_hostnames}", file=sys.stderr)

    # convert sets to sorted lists for JSON output
    out_data = {ip: sorted(hostnames) for ip, hostnames in sorted(results.items())}
    if args.out:
        with open(args.out, "w") as f:
            json.dump(out_data, f, indent=2)
        print(f"Wrote {args.out}", file=sys.stderr)
    else:
        json.dump(out_data, sys.stdout, indent=2)
        print()


if __name__ == "__main__":
    main()
