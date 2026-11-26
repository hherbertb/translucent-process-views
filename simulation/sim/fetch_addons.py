"""Download the one third-party Odoo addon the ticket scenario needs.

OCA `helpdesk_mgmt` (AGPL-3.0) from https://github.com/OCA/helpdesk, branch
17.0, pinned to one commit. Only that addon's folder is extracted, into
`addons/helpdesk_mgmt`, which docker-compose mounts into the Odoo container.
The code is not part of this project and is not modified.

    python -m sim.fetch_addons
"""
from __future__ import annotations

import io
import tarfile
import urllib.request
from pathlib import Path

REPO = "OCA/helpdesk"
COMMIT = "27dfbf3f8a2f7f929cf6badbe5631322381ca961"  # 17.0 branch, 2026-11-10
ADDON = "helpdesk_mgmt"
ADDONS_DIR = Path(__file__).resolve().parent.parent / "addons"


def fetch(force: bool = False) -> Path:
    target = ADDONS_DIR / ADDON
    if (target / "__manifest__.py").exists() and not force:
        return target
    url = f"https://codeload.github.com/{REPO}/tar.gz/{COMMIT}"
    print(f"[addons] downloading {REPO}@{COMMIT[:10]} ({ADDON} only)")
    data = urllib.request.urlopen(url, timeout=120).read()
    prefix = f"helpdesk-{COMMIT}/{ADDON}/"
    root = target.resolve()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for m in tar.getmembers():
            if not m.name.startswith(prefix) or not (m.isfile() or m.isdir()):
                continue  # other addons, links and special files are skipped
            dest = (target / m.name[len(prefix):]).resolve()
            if root != dest and root not in dest.parents:
                raise RuntimeError(f"unsafe path in archive: {m.name}")
            if m.isdir():
                dest.mkdir(parents=True, exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(tar.extractfile(m).read())
    (target / "PINNED_COMMIT.txt").write_text(f"{REPO} {COMMIT}\n", encoding="utf-8")
    return target


if __name__ == "__main__":
    print(fetch())
