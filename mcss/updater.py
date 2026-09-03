# -*- coding: utf-8 -*-
"""自动更新模块：检查 GitHub Release 最新版，下载源码包并自动重建。

工作流（方案 B —— 源码包自动更新，贴合「源码 + 工具链」部署方式）：
  1. 查询 GitHub Releases 最新版本 tag，与本地 __version__ 比对
  2. 有新版 → 下载 Release 里的源码 zip
  3. 解压并覆盖项目源码（保留 data / tools / venv / build / dist 等运行期目录）
  4. 自动运行 build_windows.bat 重建 EXE（Windows 下）

配置保存在 data/updater_config.json（GUI 中勾选「启动时检查更新」）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
import urllib.error
import zipfile
from typing import Dict, List, Optional, Tuple

OWNER = "bbGJ-email"
REPO = "mc-seed-scanner"
KEEP_DIRS = ("data", "tools", "venv", "build", "dist", ".git", "__pycache__")


def parse_version(v) -> Optional[Tuple[int, ...]]:
    """'v1.1.0' / '1.1' -> (1,1,0)；无法解析返回 None。"""
    m = re.match(r"[vV]?(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(v).strip())
    if not m:
        return None
    parts = [int(x) for x in m.groups() if x is not None]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


class UpdaterConfig:
    """自动更新设置。"""
    check_on_start: bool = False

    @classmethod
    def load(cls, path: str) -> "UpdaterConfig":
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            c = cls()
            c.check_on_start = bool(d.get("check_on_start", False))
            return c
        except Exception:
            return cls()

    def save(self, path: str):
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"check_on_start": self.check_on_start}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


def _api_get(url: str, timeout: int = 20) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "mc-seed-scanner", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def latest_release() -> dict:
    """查询 GitHub 最新 Release；返回 {tag, name, zip_url, published_at}。"""
    data = _api_get(f"https://api.github.com/repos/{OWNER}/{REPO}/releases/latest")
    zip_asset = next((a for a in data.get("assets", []) if a.get("name", "").endswith(".zip")), None)
    return {
        "tag": data.get("tag_name", ""),
        "name": data.get("name", data.get("tag_name", "")),
        "zip_url": zip_asset.get("browser_download_url") if zip_asset else None,
        "published_at": data.get("published_at", ""),
    }


def check_update(current_version: str) -> Tuple[bool, dict, str]:
    """检查是否有可用更新。

    返回 (has_update, release_info, message)。
    """
    try:
        rel = latest_release()
    except urllib.error.HTTPError as e:
        return False, {}, f"查询 GitHub 失败 (HTTP {e.code})，请检查网络"
    except Exception as e:
        return False, {}, f"查询 GitHub 失败: {e}"
    cur = parse_version(current_version)
    new = parse_version(rel.get("tag", ""))
    if not new:
        return False, rel, f"GitHub 上的版本号 {rel.get('tag')!r} 无法识别"
    if not cur:
        return False, rel, f"本地版本号 {current_version!r} 无法识别"
    if new <= cur:
        return False, rel, f"已是最新版本 v{'.'.join(map(str, cur))}"
    if not rel.get("zip_url"):
        return False, rel, f"发现新版 {rel['tag']}，但 Release 未附带源码包，请到仓库手动下载"
    return True, rel, f"发现新版本 {rel['tag']}（当前 v{'.'.join(map(str, cur))}）"


def download_zip(url: str, dest: str) -> str:
    """下载 Release 源码包到本地，返回文件路径。"""
    req = urllib.request.Request(url, headers={"User-Agent": "mc-seed-scanner"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)
    return dest


def apply_update(zip_path: str, project_root: str, keep: Optional[List[str]] = None) -> int:
    """解压并覆盖项目源码（保留 keep 顶层目录），返回覆盖的文件/目录数。"""
    keep = keep or KEEP_DIRS
    tmp_dir = tempfile.mkdtemp(prefix="mcss_upd_")
    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp_dir)
        # 定位解压后的顶层目录（zip 内通常为 mc-seed-scanner/）
        entries = [os.path.join(tmp_dir, e) for e in os.listdir(tmp_dir)]
        dirs = [e for e in entries if os.path.isdir(e)]
        src_root = dirs[0] if len(dirs) == 1 else tmp_dir
        count = 0
        for item in os.listdir(src_root):
            if item in keep:
                continue
            s = os.path.join(src_root, item)
            dst = os.path.join(project_root, item)
            if os.path.isdir(s):
                if os.path.exists(dst):
                    shutil.rmtree(dst, ignore_errors=True)
                shutil.copytree(s, dst)
            else:
                if os.path.exists(dst):
                    os.remove(dst)
                shutil.copy2(s, dst)
            count += 1
        return count
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def rebuild(project_root: str) -> bool:
    """Windows 下自动运行 build_windows.bat 重建 EXE；返回是否已启动。"""
    if os.name != "nt":
        return False
    bat = os.path.join(project_root, "build_windows.bat")
    if not os.path.exists(bat):
        return False
    try:
        subprocess.Popen(["cmd", "/c", "start", "", "cmd", "/k", bat],
                         cwd=project_root)
        return True
    except Exception:
        return False


def do_update(project_root: str, release: dict, zip_path: str) -> dict:
    """执行一次完整更新：下载 → 覆盖 → （自动重建）。返回结果信息。"""
    try:
        download_zip(release["zip_url"], zip_path)
    except Exception as e:
        return {"ok": False, "step": "下载", "message": f"下载失败: {e}"}
    try:
        n = apply_update(zip_path, project_root)
    except Exception as e:
        return {"ok": False, "step": "解压覆盖", "message": f"覆盖失败: {e}"}
    finally:
        try:
            if os.path.exists(zip_path):
                os.remove(zip_path)
        except Exception:
            pass
    rebuilt = rebuild(project_root)
    return {
        "ok": True,
        "step": "完成",
        "message": f"已更新到 {release['tag']}（覆盖 {n} 项源码，保留 data/tools/venv）。"
                   + ("正在后台重新构建，构建完成后请重新打开程序。" if rebuilt
                      else "请运行 build_windows.bat 完成重建。"),
    }
