#!/usr/bin/env python3
"""把 kanripo org 中實際存在的典籍 repo 以 submodule 形式登記進本 repo。

用法:
    python3 tools/gen_submodules.py KR1        # 只處理經部
    python3 tools/gen_submodules.py --all      # 全部

不會 clone 任何 repo：直接查 GitHub GraphQL 取得各 repo 預設分支的 commit,
再寫 .gitmodules 並以 `git update-index --cacheinfo 160000` 登記 gitlink。
因此 clone 本 repo 依然是輕量的（除非加 --recurse-submodules）。
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ID_RE = re.compile(r"^\*{3} (KR\d[a-z]\d{4})\b", re.M)
BATCH = 100


def collect_ids(prefix):
    ids = set()
    for f in sorted((ROOT / "KR").glob("*.txt")):
        ids.update(ID_RE.findall(f.read_text(encoding="utf-8")))
    return sorted(i for i in ids if i.startswith(prefix))


def head_oids(ids):
    """回傳 {id: oid}，org 中不存在的 repo 直接略過。"""
    out = {}
    for start in range(0, len(ids), BATCH):
        chunk = ids[start : start + BATCH]
        parts = [
            'r%d: repository(owner:"kanripo",name:"%s"){name defaultBranchRef{target{oid}}}'
            % (n, kid)
            for n, kid in enumerate(chunk)
        ]
        query = "{ " + " ".join(parts) + " }"
        # 不存在的 repo 會讓 gh 以非零退出，但 data 仍然完整，故只看 stdout。
        # 偶發的 502／限流則重試。
        data = None
        for attempt in range(5):
            proc = subprocess.run(
                ["gh", "api", "graphql", "-f", "query=" + query],
                capture_output=True, text=True,
            )
            try:
                data = json.loads(proc.stdout).get("data") or {}
                break
            except ValueError:
                print("  批次失敗（第 %d 次）: %s" % (attempt + 1,
                      (proc.stderr or proc.stdout)[:200].strip()), file=sys.stderr)
                time.sleep(5 * (attempt + 1))
        if data is None:
            sys.exit("gh api graphql 連續失敗，已中止（尚未寫入任何東西）。")
        for n, kid in enumerate(chunk):
            node = data.get("r%d" % n)
            ref = (node or {}).get("defaultBranchRef")
            if ref and ref.get("target"):
                out[kid] = ref["target"]["oid"]
        print("  %d/%d ..." % (min(start + BATCH, len(ids)), len(ids)), file=sys.stderr)
    return out


def path_for(kid):
    # 與 KR/KR1a.txt 等目錄檔並排，例如 KR/KR1/KR1a/KR1a0001
    return "KR/%s/%s/%s" % (kid[:3], kid[:4], kid)


GM_RE = re.compile(r'\[submodule "([^"]+)"\]\n(?:\t[^\n]*\n)*', re.M)


def merge_gitmodules(entries):
    """把 entries({path: url}) 併入現有 .gitmodules，依 path 排序輸出。"""
    gm = ROOT / ".gitmodules"
    known = {}
    if gm.exists():
        text = gm.read_text(encoding="utf-8")
        for m in GM_RE.finditer(text):
            block = m.group(0)
            url = re.search(r"url\s*=\s*(\S+)", block)
            if url:
                known[m.group(1)] = url.group(1)
    known.update(entries)
    gm.write_text(
        "".join(
            '[submodule "%s"]\n\tpath = %s\n\turl = %s\n' % (p, p, u)
            for p, u in sorted(known.items())
        ),
        encoding="utf-8",
    )
    return len(known)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prefix", nargs="?", default="", help="例如 KR1、KR1a；留空或 --all 表示全部")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    prefix = "" if args.all else args.prefix

    ids = collect_ids(prefix)
    print("目錄中符合 %r 的書號: %d" % (prefix or "全部", len(ids)), file=sys.stderr)
    oids = head_oids(ids)
    print("org 中實際存在的 repo: %d（缺 %d）" % (len(oids), len(ids) - len(oids)), file=sys.stderr)

    entries = {}
    for kid, oid in sorted(oids.items()):
        p = path_for(kid)
        entries[p] = "https://github.com/kanripo/%s.git" % kid
        subprocess.run(
            ["git", "update-index", "--add", "--cacheinfo", "160000,%s,%s" % (oid, p)],
            cwd=ROOT, check=True,
        )
    total = merge_gitmodules(entries)
    subprocess.run(["git", "add", ".gitmodules"], cwd=ROOT, check=True)
    print("已登記 %d 個 submodule，.gitmodules 共 %d 條。" % (len(entries), total), file=sys.stderr)


if __name__ == "__main__":
    main()
