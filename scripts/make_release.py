#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布端脚本：创建 GitHub Release 并上传源码 zip（供自动更新模块拉取）。

用法：
    GH_TOKEN=<token> python3 scripts/make_release.py <tag> <zip_path> [--name NAME] [--body BODY]

示例：
    GH_TOKEN=ghp_xxx python3 scripts/make_release.py v1.1.0 MCSeedScanner-v1.1.0.zip \
        --body "AI 智能推荐持续探测系统 + 自动更新"
"""
from __future__ import annotations
import json
import os
import sys
import urllib.request
import urllib.error

OWNER = "bbGJ-email"
REPO = "mc-seed-scanner"
BASE = f"https://api.github.com/repos/{OWNER}/{REPO}"


def _req(url: str, data: bytes = None, headers: dict = None, method: str = None) -> dict:
    token = os.environ.get("GH_TOKEN", "")
    h = {"Authorization": f"token {token}", "User-Agent": "mc-seed-scanner"}
    if data is not None:
        h["Content-Type"] = headers.get("Content-Type", "application/json") if headers else "application/json"
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
        return json.loads(raw.decode("utf-8")) if raw else {}


def create_release(tag: str, name: str, body: str) -> dict:
    payload = {"tag_name": tag, "name": name, "body": body,
               "draft": False, "prerelease": False}
    return _req(f"{BASE}/releases", data=json.dumps(payload).encode("utf-8"), method="POST")


def upload_asset(upload_url: str, zip_path: str, asset_name: str) -> dict:
    with open(zip_path, "rb") as f:
        data = f.read()
    # upload_url 形如 https://uploads.github.com/repos/.../releases/{id}/assets{?name,label}
    url = upload_url.replace("{?name,label}", "") + f"?name={urllib.parse.quote(asset_name)}"
    return _req(url, data=data, headers={"Content-Type": "application/zip"},
                method="POST")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    tag = sys.argv[1]
    zip_path = sys.argv[2]
    args = sys.argv[3:]
    name = "MCSeedScanner " + tag
    body = ""
    if "--name" in args:
        name = args[args.index("--name") + 1]
    if "--body" in args:
        body = args[args.index("--body") + 1]
    if not os.environ.get("GH_TOKEN"):
        print("[错误] 未设置 GH_TOKEN 环境变量")
        sys.exit(1)
    asset_name = os.path.basename(zip_path)
    print(f"[1/2] 创建 Release {tag} ...")
    rel = create_release(tag, name, body)
    rid = rel.get("id")
    upload_url = rel.get("upload_url", "")
    if not rid or not upload_url:
        print("[错误] 创建 Release 失败:", rel.get("message", rel))
        sys.exit(1)
    print(f"      Release id={rid} url={rel.get('html_url')}")
    print(f"[2/2] 上传源码包 {asset_name} ({os.path.getsize(zip_path)//1024} KB) ...")
    try:
        a = upload_asset(upload_url, zip_path, asset_name)
        print(f"      上传成功: {a.get('browser_download_url')}")
    except urllib.error.HTTPError as e:
        print(f"[错误] 上传失败 HTTP {e.code}: {e.read().decode('utf-8','replace')[:300]}")
        sys.exit(1)
    print("完成。自动更新模块已可检测到该版本。")


if __name__ == "__main__":
    import urllib.parse
    main()
