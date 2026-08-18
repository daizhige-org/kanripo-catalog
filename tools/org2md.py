#!/usr/bin/env python3
"""Generate browsable Markdown views of the Kanseki Repository catalog.

The Org-mode sources (KR/*.txt, general/*.org, daoist/*.org, buddhist/*.org)
remain the authoritative data.  This script renders a parallel tree of *.md
files so that the catalog is readable on GitHub, and links every text to its
repository at https://github.com/kanripo/<KR_ID>.

Usage:  python3 tools/org2md.py [repo-root]
"""

import os
import re
import sys

REPO_URL = "https://github.com/kanripo/{}"
KR_ID_RE = re.compile(r"^KR\d[a-z]\d{4}$")
KR_ID_IN_TITLE_RE = re.compile(r"^(KR\d[a-z]\d{4})\b")

HEADLINE_RE = re.compile(r"^(\*+)\s+(.*)$")
TODO_RE = re.compile(r"^(TODO|DONE|WAITING|CANCELLED)\s+")
TAGS_RE = re.compile(r"\s+((?::[\w@#%-]+)+:)\s*$")
KEYWORD_RE = re.compile(r"^#\+([A-Za-z_]+):\s*(.*)$")
PROP_RE = re.compile(r"^\s*:([^:\s]+):\s*(.*)$")
LINK_RE = re.compile(r"\[\[([^\]\[]+?)\](?:\[([^\]\[]*?)\])?\]")

# Property keys whose name adds nothing to a rendered person/edition line.
BARE_KEYS = ("DYNASTY", "FUNCTION", "DATES")
# Keys that are rendered elsewhere (heading, link) and dropped from the props line.
SKIP_KEYS = ("KR_ID",)

# Org link schemes that point at local image/text databases; on GitHub only the
# label is meaningful, so the target is dropped (it survives in the Org source).
LOCAL_SCHEMES = ("krpimg", "dz", "dzjy", "dzjycan", "dzcont", "mandoku", "cbeta", "at")


class Node:
    def __init__(self, level, title, todo=None, tags=()):
        self.level = level
        self.title = title
        self.todo = todo
        self.tags = list(tags)
        self.props = []          # list of (key, value), source order
        self.body = []           # list of str
        self.children = []

    def prop(self, key):
        for k, v in self.props:
            if k == key:
                return v
        return None


# --------------------------------------------------------------------------
# parsing


def parse_org(path):
    root = Node(0, "")
    stack = [root]
    keywords = {}
    in_drawer = False
    in_src = False

    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip("\n")

            if in_src:
                if line.strip().lower().startswith("#+end_src"):
                    in_src = False
                continue
            if line.strip().lower().startswith("#+begin_src"):
                in_src = True
                continue

            kw = KEYWORD_RE.match(line)
            if kw:
                keywords.setdefault(kw.group(1).upper(), kw.group(2).strip())
                continue
            if line.startswith("#"):
                continue

            hl = HEADLINE_RE.match(line)
            if hl:
                in_drawer = False
                level = len(hl.group(1))
                title = hl.group(2).strip()
                tags = ()
                mt = TAGS_RE.search(title)
                if mt:
                    tags = [t for t in mt.group(1).strip(":").split(":") if t]
                    title = title[: mt.start()].strip()
                todo = None
                md = TODO_RE.match(title)
                if md:
                    todo = md.group(1)
                    title = title[md.end():].strip()
                node = Node(level, title, todo, tags)
                while stack[-1].level >= level:
                    stack.pop()
                stack[-1].children.append(node)
                stack.append(node)
                continue

            node = stack[-1]
            stripped = line.strip()
            if stripped == ":PROPERTIES:":
                in_drawer = True
                continue
            if in_drawer:
                if stripped == ":END:":
                    in_drawer = False
                    continue
                mp = PROP_RE.match(line)
                if mp:
                    node.props.append((mp.group(1), mp.group(2).strip()))
                continue
            if stripped:
                node.body.append(stripped)

    return root, keywords


# --------------------------------------------------------------------------
# inline formatting


def md_escape(text):
    return re.sub(r"([<>*`\[\]])", r"\\\1", text)


def convert_links(text):
    def repl(m):
        target, label = m.group(1), m.group(2)
        label = label if label else target
        scheme, _, rest = target.partition(":")
        if scheme in ("http", "https"):
            return "[{}]({})".format(label, target)
        if scheme == "ia":
            return "[{}](https://archive.org/details/{})".format(label, rest)
        if scheme == "file":
            href = re.sub(r"\.(txt|org)$", ".md", rest)
            return "[{}]({})".format(label, href)
        if scheme in LOCAL_SCHEMES:
            return label
        return label
    return LINK_RE.sub(repl, text)


def inline(text):
    parts = []
    pos = 0
    for m in LINK_RE.finditer(text):
        parts.append(md_escape(text[pos:m.start()]))
        parts.append(convert_links(m.group(0)))
        pos = m.end()
    parts.append(md_escape(text[pos:]))
    return "".join(parts).strip()


def render_props(node, extra=None):
    bits = list(extra or [])
    bare = []
    rest = []
    for key, value in node.props:
        if key in SKIP_KEYS or not value:
            continue
        value = inline(value)
        if key in BARE_KEYS:
            bare.append((BARE_KEYS.index(key), value))
        else:
            rest.append("`{}` {}".format(key, value))
    bits += [v for _, v in sorted(bare, key=lambda x: x[0])]
    bits += rest
    return " · ".join(bits)


def badges(node):
    bits = []
    if node.todo:
        bits.append("**{}**".format(node.todo))
    for tag in node.tags:
        bits.append("`{}`".format(tag))
    return bits


def kr_id(node):
    value = node.prop("KR_ID")
    if value and KR_ID_RE.match(value.strip()):
        return value.strip()
    m = KR_ID_IN_TITLE_RE.match(node.title)
    return m.group(1) if m else None


# --------------------------------------------------------------------------
# rendering


def is_plain_leaf(node):
    return not node.props and not node.body and not node.children and not node.todo


def render_bullets(node, depth, out):
    """Render a sub-entry node (below text level) as a bullet list item."""
    pad = "  " * depth
    head = inline(node.title)
    bits = badges(node)
    props = render_props(node, bits)
    if props:
        head = "{} — {}".format(head, props) if head else props
    if node.body:
        body = " ".join(inline(b) for b in node.body)
        head = "{} — {}".format(head, body) if head else body
    out.append("{}- {}".format(pad, head) if head else "{}-".format(pad))
    for child in node.children:
        render_bullets(child, depth + 1, out)


def render_section(node, out):
    """Render a direct child of a text entry (人物 / 版本 / 圖 …)."""
    label = "**{}**".format(inline(node.title)) if node.title else ""
    props = render_props(node, badges(node))
    body = " ".join(inline(b) for b in node.body)

    if node.children and not props and not body and all(is_plain_leaf(c) for c in node.children):
        names = "、".join(inline(c.title) for c in node.children)
        out.append("{} {}".format(label, names).strip())
        out.append("")
        return

    header = label
    if props:
        header = "{} {}".format(header, props).strip()
    if body:
        header = "{} — {}".format(header, body).strip() if header else body
    if header:
        out.append(header)
    for child in node.children:
        render_bullets(child, 0, out)
    out.append("")


def render_entry(node, hashes, out):
    """Render a text entry: heading linked to its Kanripo repository."""
    ident = kr_id(node)
    title = inline(node.title)
    extra = []
    if ident:
        url = REPO_URL.format(ident)
        if node.title.startswith(ident):
            title = "[{}]({})".format(title, url)
        else:
            extra.append("[{}]({})".format(ident, url))
    out.append("{} {}".format(hashes, title))
    out.append("")

    props = render_props(node, extra + badges(node))
    if props:
        out.append(props)
        out.append("")
    if node.body:
        out.append("  \n".join(inline(b) for b in node.body))
        out.append("")
    for child in node.children:
        render_section(child, out)


def render_heading(node, hashes, out):
    out.append("{} {}".format(hashes, inline(node.title)))
    out.append("")
    props = render_props(node, badges(node))
    if props:
        out.append(props)
        out.append("")
    if node.body:
        out.append("  \n".join(inline(b) for b in node.body))
        out.append("")


def walk(node, org_level, entry_level, top_level, out):
    if "noexport" in node.tags:
        return
    hashes = "#" * min(6, 2 + org_level - top_level)
    if org_level >= entry_level:
        render_entry(node, hashes, out)
    else:
        render_heading(node, hashes, out)
        for child in node.children:
            walk(child, org_level + 1, entry_level, top_level, out)


def find_entry_level(root):
    """Shallowest level carrying a KR_ID / a text identifier in its title."""
    best = [None]

    def visit(node):
        if node.level and (node.prop("KR_ID") or node.prop("CUSTOM_ID")):
            if best[0] is None or node.level < best[0]:
                best[0] = node.level
        for child in node.children:
            visit(child)

    visit(root)
    return best[0] or 3


# --------------------------------------------------------------------------
# files


def convert_index(src, dst, part, part_name, cats):
    out = ["# {} {}".format(part, part_name), "",
           "[← 漢籍リポジトリ目録](../README.md)", "",
           "<sub>由 [`tools/org2md.py`](../tools/org2md.py) 自動生成，請勿直接編輯；"
           "資料源為 [`{}`]({})。</sub>".format(os.path.basename(src), os.path.basename(src)),
           ""]
    for code in sorted(c for c in cats if c.startswith(part)):
        out.append("- [{} {}]({}.md)".format(code, cats[code], code))
    out.append("")
    write(dst, out)


def convert(src, dst, title=None, breadcrumb=None):
    root, keywords = parse_org(src)
    tops = [c for c in root.children if "noexport" not in c.tags]
    entry_level = find_entry_level(root)
    top_level = min((c.level for c in tops), default=1)

    out = []
    if title is None:
        title = keywords.get("TITLE")
    if title is None and len(tops) == 1 and tops[0].level < entry_level:
        title = tops[0].title
        tops = tops[0].children
        top_level = min((c.level for c in tops), default=top_level + 1)
    if title is None:
        title = os.path.splitext(os.path.basename(src))[0]

    out.append("# {}".format(inline(title)))
    out.append("")
    if breadcrumb:
        out.append(breadcrumb)
        out.append("")
    out.append("<sub>由 [`{}`]({}) 自動生成，請勿直接編輯；資料源為 [`{}`]({})。</sub>".format(
        "tools/org2md.py", relpath("tools/org2md.py", dst),
        os.path.basename(src), os.path.basename(src)))
    out.append("")

    for node in tops:
        walk(node, node.level, entry_level, top_level, out)

    write(dst, out)


def relpath(target, from_file):
    return os.path.relpath(target, os.path.dirname(from_file)) or "."


def write(path, lines):
    text = "\n".join(lines).rstrip() + "\n"
    text = re.sub(r"\n{3,}", "\n\n", text)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return text


# --------------------------------------------------------------------------

PARTS = [
    ("KR1", "經部"), ("KR2", "史部"), ("KR3", "子部"),
    ("KR4", "集部"), ("KR5", "道部"), ("KR6", "佛部"),
]

COLLECTIONS = [
    ("general", "sbck.org", "四部叢刊", "Sibu congkan"),
    ("general", "skqs1.org", "四庫全書 1 經部", "Siku quanshu"),
    ("general", "skqs2.org", "四庫全書 2 史部", "Siku quanshu"),
    ("general", "skqs3.org", "四庫全書 3 子部", "Siku quanshu"),
    ("general", "skqs4.org", "四庫全書 4 集部", "Siku quanshu"),
    ("daoist", "ztdz.org", "正統道藏", "Zhengtong daozang"),
    ("daoist", "dzjy.org", "道藏輯要", "Daozang jiyao"),
    ("buddhist", "taisho.org", "大正新脩大藏經", "Taishō shinshū daizōkyō"),
]


def category_titles(root_dir):
    """Map KR1a -> 易類, read from the KR<n>.txt index files."""
    titles = {}
    for part, _ in PARTS:
        path = os.path.join(root_dir, "KR", part + ".txt")
        if not os.path.exists(path):
            continue
        for line in open(path, encoding="utf-8"):
            m = re.search(r"\[\[file:(KR\d[a-z])\.txt\]\[\1\s+([^\]]+)\]\]", line)
            if m:
                titles[m.group(1)] = m.group(2).strip()
    return titles


def main():
    root_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    root_dir = os.path.abspath(root_dir)
    cats = category_titles(root_dir)

    for part, part_name in PARTS:
        src = os.path.join(root_dir, "KR", part + ".txt")
        dst = os.path.join(root_dir, "KR", part + ".md")
        convert_index(src, dst, part, part_name, cats)

        for code in sorted(c for c in cats if c.startswith(part)):
            csrc = os.path.join(root_dir, "KR", code + ".txt")
            if not os.path.exists(csrc):
                continue
            cdst = os.path.join(root_dir, "KR", code + ".md")
            convert(csrc, cdst, breadcrumb="[← 目録](../README.md) · [{} {}]({}.md)".format(
                part, part_name, part))

    for folder, name, title, _ in COLLECTIONS:
        src = os.path.join(root_dir, folder, name)
        if not os.path.exists(src):
            continue
        dst = os.path.join(root_dir, folder, os.path.splitext(name)[0] + ".md")
        convert(src, dst, title=title, breadcrumb="[← 漢籍リポジトリ目録](../README.md)")

    write(os.path.join(root_dir, "README.md"), readme_lines(cats))
    print("done")


def readme_lines(cats):
    out = [
        "# Kanseki Repository 各種漢籍目録",
        "",
        "漢籍リポジトリ（[Kanseki Repository](https://www.kanripo.org/)）の書目データです。",
        "各テキストの見出しは、対応するリポジトリ "
        "`https://github.com/kanripo/<KR_ID>` にリンクしています。",
        "",
        "Org-mode 形式の `KR/*.txt`, `general/*.org`, `daoist/*.org`, `buddhist/*.org` "
        "が原データで、GitHub 上で読むための Markdown 版を "
        "[`tools/org2md.py`](tools/org2md.py) で生成しています。",
        "",
        "## Kanseki Repository",
        "",
    ]
    for part, part_name in PARTS:
        out.append("### [{} {}](KR/{}.md)".format(part, part_name, part))
        out.append("")
        for code in sorted(c for c in cats if c.startswith(part)):
            out.append("- [{} {}](KR/{}.md)".format(code, cats[code], code))
        out.append("")

    out += [
        "## General collections 叢書",
        "",
        "- Sibu congkan 四部叢刊 — [sbck](general/sbck.md)",
        "- Siku quanshu 四庫全書 — [1 經部](general/skqs1.md) · "
        "[2 史部](general/skqs2.md) · [3 子部](general/skqs3.md) · "
        "[4 集部](general/skqs4.md)",
        "- Sibu beiyao 四部備要 (sbby) — *todo*",
        "- Zhongguo jiben gujiku 中國基本古籍庫 (jbgjk) — *todo*",
        "",
        "## Daoist Texts 道教文献",
        "",
        "- Zhengtong daozang 正統道藏 — [ztdz](daoist/ztdz.md)",
        "- Daozang jiyao 道藏輯要 — [dzjy](daoist/dzjy.md)",
        "- Zhonghua daozang 中華道藏 (zhdz) — *todo*",
        "",
        "## Buddhist Texts 仏典",
        "",
        "- Taishō shinshū daizōkyō 大正新脩大藏經 — [T-taisho](buddhist/taisho.md)",
    ]
    for label, name, code in [
        ("Zokuzokyō 續藏經", "X", "xuzang"),
        ("Goryeo daejanggyeong 高麗大藏經", "K", "koreana"),
        ("Jiaxing dazangjing 嘉興大藏經", "J", "jiaxing"),
        ("Songzang yizhen 宋藏遺珍", "S", "songzang"),
        ("Zhaocheng jinzang 趙城金藏", "A", "jin"),
        ("Hongwu nanzang 洪武南藏", "U", "hongwu"),
        ("Yongle beizang 永樂北藏", "P", "yongle"),
        ("Qianlong dazangjing 乾隆大藏經", "L", "qianlong"),
        ("Dainippon kōtei kunten daizōkyō 大日本校訂訓點大藏經", "M", "kotei-daizokyo"),
        ("Fojiao dazangjing 佛教大藏經", "G", "fojiao"),
        ("Zhonghua dazangjing 中華大藏經", "C", "zhonghua"),
        ("Zangwai fojiao wenxian 藏外佛教文獻", "W", "zangwai"),
    ]:
        out.append("- {} ({}-{})".format(label, name, code))
    out.append("")
    return out


if __name__ == "__main__":
    main()
