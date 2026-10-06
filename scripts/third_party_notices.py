#!/usr/bin/env python3
"""Regenerate THIRD_PARTY_NOTICES.md from the pinned dependencies that ship in the tuKang image.

Sources: backend/requirements.lock (installed with --no-deps into a temp dir, so the license files
match the exact pins) and the production packages of frontend/package-lock.json (read from
frontend/node_modules, so run `npm ci` in frontend/ first). Dev-only tools are not distributed and
are left out. Run it after every dependency change:  python3 scripts/third_party_notices.py
"""
from __future__ import annotations

import email
import json
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "backend" / "requirements.lock"
NPM_LOCK = ROOT / "frontend" / "package-lock.json"
NODE_MODULES = ROOT / "frontend" / "node_modules"
OUT = ROOT / "THIRD_PARTY_NOTICES.md"

LICENSE_FILE = re.compile(r"^(licen[cs]e|copying|notice|authors)([.-].*)?$", re.I)

# Packages whose license deserves a remark for a dual-licensed (AGPL + commercial) product
REMARKS = {
    "asyncssh": "Used under EPL-2.0 (one of its two options). Weak copyleft: changes to asyncssh's own "
                "files must be published under EPL-2.0; tuKang's code that only imports it is unaffected.",
}


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def python_packages() -> list[dict]:
    pins = {}
    for line in LOCK.read_text().splitlines():
        line = line.split("#")[0].strip()
        if line:
            name, version = line.split("==")
            pins[norm(name)] = version
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "--no-deps", "--no-compile",
             "--disable-pip-version-check", "--target", tmp, "-r", str(LOCK)],
            check=True,
        )
        result = []
        for dist in sorted(Path(tmp).glob("*.dist-info")):
            meta = email.message_from_string((dist / "METADATA").read_text(encoding="utf-8"))
            name = meta["Name"]
            if norm(name) not in pins:
                continue
            lic = meta.get("License-Expression") or ""
            if not lic:
                classifiers = [c.split(" :: ")[-1] for c in meta.get_all("Classifier") or []
                               if c.startswith("License ::") and not c.endswith(":: OSI Approved")]
                declared = (meta.get("License") or "").strip().splitlines()
                lic = " / ".join(classifiers) or (declared[0] if declared else "")
            urls = dict(u.split(", ", 1) for u in meta.get_all("Project-URL") or [] if ", " in u)
            url = (urls.get("Source") or urls.get("Source Code") or urls.get("Homepage")
                   or meta.get("Home-page") or f"https://pypi.org/project/{name}/")
            files = sorted(p for p in dist.rglob("*") if p.is_file() and LICENSE_FILE.match(p.name))
            result.append({
                "name": name, "version": meta["Version"], "license": lic or "see license text",
                "url": url, "texts": [f.read_text(encoding="utf-8", errors="replace").strip() for f in files],
            })
        missing = set(pins) - {norm(p["name"]) for p in result}
        if missing:
            sys.exit(f"pinned but not installed: {', '.join(sorted(missing))}")
        return result


def npm_packages() -> list[dict]:
    lock = json.loads(NPM_LOCK.read_text())
    result = []
    for path, info in sorted(lock["packages"].items()):
        if not path or info.get("dev") or info.get("devOptional"):
            continue
        pkg_dir = ROOT / "frontend" / path
        if not pkg_dir.is_dir():
            sys.exit(f"{path} missing: run `npm ci` in frontend/ first")
        installed = json.loads((pkg_dir / "package.json").read_text())
        if installed.get("version") != info.get("version"):
            sys.exit(f"{path}: installed {installed.get('version')} != locked {info.get('version')}; run `npm ci`")
        repo = installed.get("repository")
        url = (repo.get("url") if isinstance(repo, dict) else repo) or installed.get("homepage") or ""
        # git+ssh://git@github.com/a/b.git, git@github.com:a/b, github:a/b, a/b -> https://github.com/a/b
        url = re.sub(r"\.git$", "", url.strip())
        url = re.sub(r"^(git\+)?(ssh://|git://|https?://)?(git@)?github\.com[:/]|^github:", "https://github.com/", url)
        if re.fullmatch(r"[\w.-]+/[\w.-]+", url):
            url = "https://github.com/" + url
        files = sorted(p for p in pkg_dir.iterdir() if p.is_file() and LICENSE_FILE.match(p.name))
        result.append({
            "name": path.split("node_modules/")[-1], "version": info["version"],
            "license": info.get("license", "see license text"),
            "url": url or f"https://www.npmjs.com/package/{path.split('node_modules/')[-1]}",
            "texts": [f.read_text(encoding="utf-8", errors="replace").strip() for f in files],
        })
    return result


def table(packages: list[dict]) -> list[str]:
    rows = ["| Component | Version | License | Source |", "|---|---|---|---|"]
    for p in packages:
        remark = " ¹" if norm(p["name"]) in REMARKS else ""
        rows.append(f"| {p['name']}{remark} | {p['version']} | {p['license']} | <{p['url']}> |")
    return rows


def main() -> None:
    py, js = python_packages(), npm_packages()
    out = [
        "# Third-Party Notices",
        "",
        "tuKang is Copyright © 2026 AIT HENDI and licensed under the GNU AGPL-3.0-only (see [LICENSE](LICENSE)) "
        "or a separate commercial license. It includes the open-source components below, each under its own "
        "license. **These notices must be kept in every copy or distribution of tuKang, including commercially "
        "licensed ones**; the licenses of these components are not changed by tuKang's license.",
        "",
        "Generated by `scripts/third_party_notices.py` from `backend/requirements.lock` and the production "
        "packages of `frontend/package-lock.json`. Do not edit by hand.",
        "",
        "The container image is also built on `docker.io/library/python:3.12-slim` (Debian GNU/Linux and "
        "CPython, under the PSF License and the licenses of the respective Debian packages, listed in "
        "`/usr/share/doc/*/copyright` inside the image). Node.js is used only at build time and is not shipped.",
        "",
        f"## Backend (Python) — {len(py)} packages",
        "",
        *table(py),
        "",
        f"## Frontend (JavaScript, bundled into the web UI) — {len(js)} packages",
        "",
        *table(js),
        "",
    ]
    remarks = [(p["name"], REMARKS[norm(p["name"])]) for p in py + js if norm(p["name"]) in REMARKS]
    if remarks:
        out += ["¹ " + "  \n¹ ".join(f"**{n}**: {r}" for n, r in remarks), ""]

    # Identical license texts are printed once, followed by every component they apply to
    by_text: dict[str, list[str]] = defaultdict(list)
    for p in py + js:
        texts = p["texts"] or [f"(No license file is included in the {p['name']} {p['version']} package; "
                               f"its declared license is {p['license']}, see {p['url']}.)"]
        by_text["\n\n".join(texts)].append(f"{p['name']} {p['version']}")
    out += ["## License texts", ""]
    for text, users in sorted(by_text.items(), key=lambda kv: kv[1][0].lower()):
        fence = "~~~~" if "```" in text else "```"
        out += [f"### {', '.join(users)}", "", fence + "text", text, fence, ""]

    OUT.write_text("\n".join(out))
    print(f"wrote {OUT.relative_to(ROOT)}: {len(py)} Python + {len(js)} npm packages, "
          f"{len(by_text)} distinct license texts")


if __name__ == "__main__":
    main()
