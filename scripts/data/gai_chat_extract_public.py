#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gai_chat_extract.py - extract the full conversation from a saved Google "AI Mode" page.

Zero dependencies: Python 3.7+ standard library only. Single file; copy it anywhere.

    python gai_chat_extract.py chat.htm                 # -> chat.md next to the input
    python gai_chat_extract.py chat.htm -f json         # structured output
    python gai_chat_extract.py chat.htm -f all          # md + json + txt
    python gai_chat_extract.py export.zip -f md,json    # reads .htm/.html inside a zip
    python gai_chat_extract.py chat.htm --stdout        # print instead of writing a file
    cat chat.htm | python gai_chat_extract.py - --stdout

How it finds the chat: Google ships screen-reader headings for every message
("You said: ..." and "AI Mode reply for ..."). Those are used as anchors, rather than
Google's obfuscated CSS class names, which change between deployments. Everything
else (paragraphs, lists, tables, quotes, code) is converted with a generic
block/inline HTML walker that does not depend on class names either.

Privacy note: this source file contains no account-specific identifiers and does
not access browser profiles or credentials. Exported files preserve conversation
content, which may itself contain personal information. JSON output also includes
the page title, first query, and saved-page URL path. Source links may contain
tracking parameters. Review generated files before publishing; this tool is not a
personal-data anonymizer.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import zipfile
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlsplit

__version__ = "1.0.0"

# --------------------------------------------------------------------------- tunables
# Override on the command line (--user-heading / --ai-heading) for non-English pages.
USER_HEADING = r"^\s*You said\b\s*:?\s*"
AI_HEADING = r"^\s*AI Mode reply for\b\s*:?\s*"
TITLE_HEADING = r"^\s*AI Mode Conversation\s*:\s*(.*)$"

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
        "param", "source", "track", "wbr"}
RAW_TAGS = {"script", "style"}  # contents are never stored
SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "head", "button", "canvas",
             "iframe", "input", "select", "textarea", "link", "meta", "object", "embed",
             "audio", "video", "title"}
# UI widgets (copy/edit/share buttons, dialogs, progress spinners, tooltips...)
SKIP_ROLES = {"button", "alert", "progressbar", "status", "tooltip", "dialog", "alertdialog",
              "menu", "menubar", "toolbar", "navigation", "banner", "search", "tablist", "tab"}
BLOCK_TAGS = {"div", "p", "ul", "ol", "li", "table", "thead", "tbody", "tfoot", "tr", "td",
              "th", "blockquote", "pre", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "section",
              "article", "aside", "header", "footer", "figure", "figcaption", "details",
              "summary", "dl", "dt", "dd", "nav", "main", "form", "fieldset"}
NOTICE_HREF = "support.google.com/websearch"   # the "AI responses may include mistakes" link

WS = re.compile(r"[ \t\r\n\f\v\u00a0\u200b\u202f\u2009]+")
DISPLAY_NONE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)
HIGHLIGHT = re.compile(r"\s*\[Highlight (?:start|end)\]\s*")
TIME_ONLY = re.compile(r"^(?:[A-Z][a-z]{2,8}\.?\s+\d{1,2},?\s+(?:\d{4},?\s+)?)?"
                       r"\d{1,2}:\d{2}(?::\d{2})?(?:\s?[AaPp]\.?[Mm]\.?)?$")
LIST_LINE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")
BLOCK_START = re.compile(r"^(#{1,6}|[-+*]|\d+[.)]|>)(\s)", re.M)


# --------------------------------------------------------------------------- tiny DOM
class Node:
    __slots__ = ("tag", "attrs", "kids", "parent", "text")

    def __init__(self, tag, attrs=None, parent=None, text=None):
        self.tag, self.attrs, self.kids, self.parent, self.text = tag, attrs or {}, [], parent, text


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        n = Node(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur)
        self.cur.kids.append(n)
        if tag not in VOID:
            self.cur = n

    def handle_startendtag(self, tag, attrs):
        self.cur.kids.append(Node(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur))

    def handle_endtag(self, tag):
        n = self.cur
        while n is not None and n.tag != tag:
            n = n.parent
        if n is not None and n.parent is not None:
            self.cur = n.parent

    def handle_data(self, data):
        if self.cur.tag not in RAW_TAGS:
            self.cur.kids.append(Node("#text", parent=self.cur, text=data))


def parse_html(html):
    b = _Builder()
    b.feed(html)
    b.close()
    return b.root


def walk(n):
    """Depth-first, document order, iterative (no recursion limit issues)."""
    stack = [n]
    while stack:
        x = stack.pop()
        yield x
        stack.extend(reversed(x.kids))


def raw_text(n):
    """Text content with whitespace preserved (<br> -> newline); skips script/style."""
    out = []
    for x in walk(n):
        if x.tag == "#text":
            out.append(x.text)
        elif x.tag == "br":
            out.append("\n")
    return "".join(out)


def norm(s):
    return WS.sub(" ", s).strip()


def clean_url(u):
    """Unwrap google.com/url?q=... redirects and drop #:~:text= highlight fragments."""
    u = (u or "").strip()
    try:
        p = urlsplit(u)
        if p.netloc.endswith("google.com") and p.path == "/url":
            q = parse_qs(p.query)
            for key in ("q", "url"):
                if q.get(key):
                    u = unquote(q[key][0])
                    break
    except ValueError:
        pass
    return re.sub(r"#:~:.*$", "", u)


# --------------------------------------------------------------------------- HTML -> text
class Renderer:
    """Converts a DOM subtree to Markdown (plain=False) or plain text (plain=True)."""

    def __init__(self, plain, ignore_ids=()):
        self.plain = plain
        self.ignore = set(ignore_ids)
        self.notices = []
        self._notice_hit = False

    # -- visibility ---------------------------------------------------------------
    def skip(self, n):
        if n.tag in SKIP_TAGS or id(n) in self.ignore:
            return True
        a = n.attrs
        if a.get("aria-hidden") == "true" or "hidden" in a:
            return True
        st = a.get("style")
        if st and DISPLAY_NONE.search(st):
            return True
        if a.get("role") in SKIP_ROLES:
            return True
        # Google's side panel with source cards; handled separately as `sources`.
        return (a.get("data-xid") or "").startswith("aim-aside")

    # -- helpers ------------------------------------------------------------------
    def esc(self, s):
        if self.plain:
            return s
        return s.replace("\\", "\\\\").replace("*", "\\*").replace("`", "\\`").replace("<", "\\<")

    def wrap(self, mark, s):
        if self.plain or not s.strip():
            return s
        lead, trail = s[:len(s) - len(s.lstrip())], s[len(s.rstrip()):]
        return "%s%s%s%s%s" % (lead, mark, s.strip(), mark, trail)

    def clean(self, s):
        s = "\n".join(l.strip() for l in s.split("\n"))
        s = re.sub(r" {2,}", " ", s)
        s = re.sub(r"\n{2,}", "\n", s)
        return s.strip()

    def para(self, s):
        s = self.clean(s)
        if not self.plain and s:
            s = s.replace("****", "")
            s = BLOCK_START.sub(r"\\\1\2", s)          # on every line: stop "1. foo" / "# foo" becoming markup
            s = s.replace("\n", "  \n")                 # keep <br> line breaks
        return s

    # -- inline -------------------------------------------------------------------
    def inline(self, n):
        if n.tag == "#text":
            return self.esc(HIGHLIGHT.sub(" ", WS.sub(" ", n.text)))
        if self.skip(n):
            return ""
        t = n.tag
        if t == "br":
            return "\n"
        if t == "img":
            alt, src = norm(n.attrs.get("alt", "")), n.attrs.get("src", "")
            if src.startswith(("http://", "https://")) and not self.plain:
                return "![%s](%s)" % (alt, src)
            return "[Image: %s]" % alt if alt else ""
        if t == "code":
            s = raw_text(n)
            if self.plain or not s.strip():
                return s
            fence = "``" if "`" in s else "`"
            return "%s%s%s" % (fence, s, fence)
        inner = "".join(self.inline(c) for c in n.kids)
        if t in ("strong", "b"):
            return self.wrap("**", inner)
        if t in ("em", "i"):
            return self.wrap("*", inner)
        if t in ("del", "s", "strike"):
            return self.wrap("~~", inner)
        if t == "mark":
            return self.wrap("==", inner)
        if t == "a":
            href = clean_url(n.attrs.get("href", ""))
            if NOTICE_HREF in href:
                self._notice_hit = True
                return ""
            text = inner.strip()
            if not text or not href.startswith(("http://", "https://")):
                return inner        # citation chips have no text; collected as sources instead
            href_md = href.replace(" ", "%20").replace(")", "%29")
            return "%s (%s)" % (text, href) if self.plain else "[%s](%s)" % (text, href_md)
        return inner

    # -- blocks -------------------------------------------------------------------
    @staticmethod
    def is_block(n):
        if n.tag in BLOCK_TAGS or n.attrs.get("role") == "heading":
            return True
        return n.tag == "code" and "\n" in raw_text(n)

    def blocks(self, node):
        out, buf = [], []

        def flush():
            if not buf:
                return
            s = self.para("".join(buf))
            buf.clear()
            hit, self._notice_hit = self._notice_hit, False
            if s:
                (self.notices if hit else out).append(s)

        for c in node.kids:
            if c.tag == "#text":
                buf.append(self.inline(c))
            elif self.skip(c):
                continue
            elif self.is_block(c):
                flush()
                out.extend(self.block(c))
            else:
                buf.append(self.inline(c))
        flush()
        return out

    def block(self, n):
        t = n.tag
        if t in ("ul", "ol"):
            return self.list_(n)
        if t == "table":
            return self.table(n)
        if t == "blockquote":
            return self.quote(n)
        if t in ("pre", "code"):
            return self.fence(n)
        if t == "hr":
            return ["---"]
        lvl = 0
        if len(t) == 2 and t[0] == "h" and t[1].isdigit():
            lvl = int(t[1])
        elif n.attrs.get("role") == "heading":
            lvl = int(n.attrs.get("aria-level") or 2) if str(n.attrs.get("aria-level") or "2").isdigit() else 2
        if lvl:
            s = self.clean("".join(self.inline(c) for c in n.kids).replace("\n", " "))
            if not s:
                return []
            return [s if self.plain else "%s %s" % ("#" * max(3, min(6, lvl)), s)]
        return self.blocks(n)

    def list_(self, n):
        ordered = n.tag == "ol"
        num = int(n.attrs["start"]) if str(n.attrs.get("start", "")).lstrip("-").isdigit() else 1
        items = []
        for li in n.kids:
            if li.tag == "#text" or self.skip(li):
                continue
            if li.tag == "li":
                bl = self.blocks(li)
            elif self.is_block(li):          # e.g. a <ul> placed directly inside a <ul>
                bl = self.block(li)
            else:
                s = self.para(self.inline(li))
                bl = [s] if s else []
            if not bl:
                continue                      # Google emits empty spacer <li>s
            mark = "%d. " % num if ordered else "- "
            pad = " " * len(mark)
            text = mark + bl[0].replace("\n", "\n" + pad)
            for b in bl[1:]:
                text += ("\n" if LIST_LINE.match(b) else "\n\n") + pad + b.replace("\n", "\n" + pad)
            items.append(text)
            num += 1
        return ["\n".join(items)] if items else []

    def cell(self, c):
        s = " ".join(b.replace("\n", " ").replace("  ", " ") for b in self.blocks(c)).strip()
        return s if self.plain else s.replace("|", "\\|")

    def table(self, n):
        rows = []

        def collect(x):
            for c in x.kids:
                if c.tag == "tr":
                    rows.append(c)
                elif c.tag in ("thead", "tbody", "tfoot"):
                    collect(c)

        collect(n)
        grid = [[self.cell(c) for c in tr.kids if c.tag in ("td", "th")] for tr in rows]
        grid = [r for r in grid if any(r)]
        if not grid:
            return []
        w = max(len(r) for r in grid)
        grid = [r + [""] * (w - len(r)) for r in grid]
        if self.plain:
            return ["\n".join(" | ".join(r) for r in grid)]
        lines = ["| " + " | ".join(grid[0]) + " |", "| " + " | ".join(["---"] * w) + " |"]
        lines += ["| " + " | ".join(r) + " |" for r in grid[1:]]
        return ["\n".join(lines)]

    def quote(self, n):
        s = "\n\n".join(self.blocks(n))
        if not s:
            return []
        if self.plain:
            return [s]
        return ["\n".join(("> " + l) if l else ">" for l in s.split("\n"))]

    def fence(self, n):
        code = raw_text(n).strip("\n")
        if not code.strip():
            return []
        if self.plain:
            return [code]
        lang = ""
        for x in walk(n):
            m = re.search(r"(?:language|lang)-([\w+#.-]+)", x.attrs.get("class", "") if x.tag != "#text" else "")
            if m:
                lang = m.group(1)
                break
        fence = "```"
        while fence in code:
            fence += "`"
        return ["%s%s\n%s\n%s" % (fence, lang, code, fence)]

    def render(self, node):
        return self.blocks(node)


# --------------------------------------------------------------------------- extraction
def light_texts(n):
    """Visible text fragments under n (ignores buttons/svg/aria-hidden)."""
    out = []
    for x in walk(n):
        if x.tag == "#text":
            t = norm(x.text)
            if t:
                # drop the text if any ancestor (up to n) is hidden/skipped
                p, ok = x.parent, True
                while p is not None and p is not n.parent:
                    if p.tag in SKIP_TAGS or p.attrs.get("aria-hidden") == "true" or "hidden" in p.attrs:
                        ok = False
                        break
                    p = p.parent
                if ok:
                    out.append(t)
    return out


def find_sources(block):
    """Source cards / citation anchors for one AI reply, de-duplicated by URL.
    Cards from the sources panel come first (in panel order), then citation-only links."""
    cards, chips = {}, {}
    for a in walk(block):
        if a.tag != "a":
            continue
        href = clean_url(a.attrs.get("href", ""))
        if not href.startswith(("http://", "https://")) or NOTICE_HREF in href:
            continue
        if re.match(r"https?://(www\.)?google\.[a-z.]+/search", href):
            continue
        if norm(raw_text(a)):
            continue                      # an ordinary link in the prose; already in the text
        label = norm(a.attrs.get("aria-label") or a.attrs.get("title") or "")
        in_card, li, p = False, None, a.parent
        while p is not None and p is not block.parent:
            if li is None and p.tag == "li":
                li = p
            if (p.attrs.get("data-xid") or "").startswith("aim-aside"):
                in_card = True
            p = p.parent
        src = {"title": label, "url": href, "site": label, "snippet": ""}
        if in_card and li is not None:
            texts = [t for t in light_texts(li) if t != "\u00b7"]
            if label in texts:
                i = texts.index(label)
                src["site"] = " \u00b7 ".join(texts[:i])
                src["snippet"] = " ".join(texts[i + 1:])
            elif texts:
                src["site"], src["snippet"] = texts[0], (texts[-1] if len(texts) > 1 else "")
        (cards if in_card else chips).setdefault(href, src)
    return list(cards.values()) + [v for k, v in chips.items() if k not in cards]


def block_for(h, marker_ids):
    """Smallest ancestor of heading h that holds the message body, without crossing into
    another message."""
    own = len(raw_text(h).strip())
    n = h.parent
    while n.parent is not None and len(raw_text(n).strip()) <= own:
        n = n.parent
    if any(id(x) in marker_ids and x is not h for x in walk(n)):
        return h.parent
    return n


def decode(data):
    for enc in ("utf-8-sig",):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    m = re.search(rb"charset\s*=\s*[\"']?([\w-]+)", data[:4096], re.I)
    if m:
        try:
            return data.decode(m.group(1).decode("ascii"))
        except (LookupError, UnicodeDecodeError):
            pass
    return data.decode("utf-8", errors="replace")


def extract_chat(html, user_heading=USER_HEADING, ai_heading=AI_HEADING):
    """Parse the saved page and return a dict describing the conversation."""
    u_re, a_re, t_re = re.compile(user_heading, re.I), re.compile(ai_heading, re.I), re.compile(TITLE_HEADING, re.I)
    root = parse_html(html)

    title, marks = "", []
    for n in walk(root):
        if len(n.tag) == 2 and n.tag[0] == "h" and n.tag[1] in "123456":
            t = norm(raw_text(n))
            if not title:
                m = t_re.match(t)
                if m:
                    title = m.group(1).strip()
                    continue
            if u_re.match(t):
                marks.append((n, "user"))
            elif a_re.match(t):
                marks.append((n, "assistant"))
    if not title:
        for n in walk(root):
            if n.tag == "title":
                title = norm(raw_text(n))
                break

    saved = re.search(r"<!--\s*saved from url=\(\d+\)\s*(\S+)", html[:8192])
    saved_url = saved.group(1) if saved else ""
    first_query = ""
    if saved_url:
        try:
            first_query = (parse_qs(urlsplit(saved_url).query).get("q") or [""])[0]
        except ValueError:
            pass

    marker_ids = {id(h) for h, _ in marks}
    messages, turn = [], 0
    for h, role in marks:
        block = block_for(h, marker_ids)
        md_r, tx_r = Renderer(False, marker_ids), Renderer(True, marker_ids)
        md_blocks, tx_blocks = md_r.render(block), tx_r.render(block)
        msg = {"role": role}
        if role == "user":
            turn += 1
            when = ""
            if tx_blocks and TIME_ONLY.match(tx_blocks[-1]):
                when = tx_blocks[-1]
                tx_blocks, md_blocks = tx_blocks[:-1], md_blocks[:-1]
            msg.update(turn=turn, time=when)
        else:
            msg.update(turn=turn, time="")
        msg["text"] = "\n\n".join(tx_blocks)
        msg["markdown"] = "\n\n".join(md_blocks)
        msg["sources"] = find_sources(block) if role == "assistant" else []
        msg["notices"] = tx_r.notices
        messages.append(msg)

    return {
        "title": title,
        "first_query": first_query,
        "saved_from": (lambda p: "%s://%s%s" % (p.scheme, p.netloc, p.path))(urlsplit(saved_url)) if saved_url else "",
        "turn_count": turn,
        "message_count": len(messages),
        "messages": messages,
    }


# --------------------------------------------------------------------------- output formats
def to_markdown(doc, sources=True):
    out = ["# %s" % (doc["title"] or "Google AI Mode conversation"), "",
           "*%d turns · extracted from a saved Google AI Mode page*" % doc["turn_count"], ""]
    for m in doc["messages"]:
        out += ["---", ""]
        if m["role"] == "user":
            out.append("## You" + (" · %s" % m["time"] if m["time"] else ""))
        else:
            out.append("## AI Mode")
        out += ["", m["markdown"] or "*(empty)*", ""]
        if sources and m["sources"]:
            out += ["**Sources**", ""]
            for s in m["sources"]:
                label = s["title"] or s["url"]
                extra = " — %s" % s["site"] if s["site"] and s["site"] != s["title"] else ""
                out.append("- [%s](%s)%s" % (label.replace("]", "\\]"), s["url"], extra))
            out.append("")
        for n in m["notices"]:
            out += ["*%s*" % n, ""]
    return "\n".join(out).rstrip() + "\n"


def to_text(doc, sources=True):
    out = [doc["title"] or "Google AI Mode conversation", "=" * 60, ""]
    for m in doc["messages"]:
        head = "[You%s]" % (" · " + m["time"] if m["time"] else "") if m["role"] == "user" else "[AI Mode]"
        out += [head, m["text"] or "(empty)", ""]
        if sources and m["sources"]:
            out.append("Sources:")
            out += ["  - %s <%s>" % (s["title"] or s["site"], s["url"]) for s in m["sources"]]
            out.append("")
        out += [n for n in m["notices"]] + ([""] if m["notices"] else [])
    return "\n".join(out).rstrip() + "\n"


def to_json(doc, sources=True):
    d = dict(doc)
    if not sources:
        d["messages"] = [dict(m, sources=[]) for m in doc["messages"]]
    return json.dumps(d, ensure_ascii=False, indent=2) + "\n"


FORMATS = {"md": (to_markdown, ".md"), "json": (to_json, ".json"), "txt": (to_text, ".txt")}


# --------------------------------------------------------------------------- I/O
def log(msg):
    """stderr that never crashes on legacy console encodings."""
    enc = getattr(sys.stderr, "encoding", None) or "utf-8"
    sys.stderr.write(msg.encode(enc, "replace").decode(enc, "replace"))


def iter_inputs(path):
    """Yield (stem, html_text, directory_for_default_output)."""
    if path == "-":
        yield "chat", decode(sys.stdin.buffer.read()), os.getcwd()
        return
    base_dir = os.path.dirname(os.path.abspath(path))
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist()
                     if n.lower().endswith((".htm", ".html", ".xhtml"))
                     and not re.search(r"(_files|\.files)/", n, re.I) and not n.endswith("/")]
            if not names:
                raise ValueError("no .htm/.html file found inside %s" % path)
            for n in names:
                yield os.path.splitext(os.path.basename(n))[0], decode(z.read(n)), base_dir
        return
    with open(path, "rb") as f:
        yield os.path.splitext(os.path.basename(path))[0], decode(f.read()), base_dir


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="gai_chat_extract",
        description="Extract the full chat from a saved Google AI Mode web page (.htm/.html, or a .zip containing one).")
    ap.add_argument("inputs", nargs="+", help="saved page(s); '-' reads stdin")
    ap.add_argument("-f", "--format", default="md", help="md, json, txt (comma separated) or 'all' [default: md]")
    ap.add_argument("-o", "--output", help="output file (single result) or directory; default: next to the input")
    ap.add_argument("--stdout", action="store_true", help="print to stdout instead of writing files")
    ap.add_argument("--no-sources", action="store_true", help="omit the per-reply source lists")
    ap.add_argument("--user-heading", default=USER_HEADING, help="regex for your-message headings (non-English pages)")
    ap.add_argument("--ai-heading", default=AI_HEADING, help="regex for AI-reply headings (non-English pages)")
    ap.add_argument("--version", action="version", version="%(prog)s " + __version__)
    args = ap.parse_args(argv)

    fmts = list(FORMATS) if args.format == "all" else [f.strip().lower() for f in args.format.split(",") if f.strip()]
    bad = [f for f in fmts if f not in FORMATS]
    if bad or not fmts:
        ap.error("unknown format(s): %s (choose from md, json, txt, all)" % ", ".join(bad or ["<none>"]))
    if args.stdout and len(fmts) > 1:
        ap.error("--stdout needs exactly one format")

    results, status = [], 0
    for path in args.inputs:
        try:
            for stem, html, base_dir in iter_inputs(path):
                doc = extract_chat(html, args.user_heading, args.ai_heading)
                if not doc["messages"]:
                    log("%s: no conversation found (no '%s' / '%s' headings). Is this a saved "
                                     "Google AI Mode page? For other languages use --user-heading/--ai-heading.\n"
                                     % (stem, args.user_heading, args.ai_heading))
                    status = 2
                    continue
                results.append((stem, base_dir, doc))
        except (OSError, ValueError, zipfile.BadZipFile) as e:
            log("%s: %s\n" % (path, e))
            status = 2

    n_files = len(results) * len(fmts)
    single_file_out = (args.output and n_files == 1 and
                       os.path.splitext(args.output)[1].lower() in (".md", ".json", ".txt"))
    for stem, base_dir, doc in results:
        for f in fmts:
            fn, ext = FORMATS[f]
            body = fn(doc, sources=not args.no_sources)
            if args.stdout:
                sys.stdout.buffer.write(body.encode("utf-8"))
                continue
            if single_file_out:
                dest = args.output
            else:
                d = args.output or base_dir
                os.makedirs(d, exist_ok=True)
                dest = os.path.join(d, stem + ext)
            with open(dest, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(body)
            nsrc = sum(len(m["sources"]) for m in doc["messages"])
            log("%s -> %s  (%d turns, %d messages, %d sources)\n"
                             % (stem, dest, doc["turn_count"], doc["message_count"], nsrc))
    return status


if __name__ == "__main__":
    sys.exit(main())
