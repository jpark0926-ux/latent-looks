#!/usr/bin/env python3
"""Build manifest.json for the Latent OTA look catalog.

Scans server/looks/*.cube. Per-look metadata comes from an optional
sidecar JSON next to each cube: server/looks/<stem>.json with fields
  {"lookId": "...", "brand": "...", "label": "...", "version": 2,
   "notes": "...", "minAppVersion": 12}
Defaults when no sidecar: lookId=<stem>, brand=<stem prefix before first
underscore>, label=<stem>, version=1, notes="".

catalogVersion comes from server/catalog.json {"catalogVersion": N} (auto-
incremented by 1 on each run unless --keep is passed).

Usage:
  python3 server/build_manifest.py           # bump catalogVersion, write manifest
  python3 server/build_manifest.py --keep    # keep catalogVersion

Serve locally:
  python3 -m http.server 8080 --directory server
  # then point the app at http://<LAN-IP>:8080/ via
  # ./gradlew assembleDebug -PLATENT_UPDATE_BASE_URL=http://<LAN-IP>:8080/
"""
import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LOOKS = os.path.join(HERE, "looks")
MANIFEST = os.path.join(HERE, "manifest.json")
CATALOG = os.path.join(HERE, "catalog.json")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="keep catalogVersion")
    args = ap.parse_args()

    catalog_version = 1
    if os.path.exists(CATALOG):
        with open(CATALOG) as f:
            catalog_version = json.load(f)["catalogVersion"]
        if not args.keep:
            catalog_version += 1
    with open(CATALOG, "w") as f:
        json.dump({"catalogVersion": catalog_version}, f)

    entries = []
    for name in sorted(os.listdir(LOOKS)):
        if not name.endswith(".cube"):
            continue
        stem = name[:-5]
        path = os.path.join(LOOKS, name)
        meta = {}
        sidecar = os.path.join(LOOKS, stem + ".json")
        if os.path.exists(sidecar):
            with open(sidecar) as f:
                meta = json.load(f)
        entry = {
            "lookId": meta.get("lookId", stem),
            "brand": meta.get("brand", stem.split("_")[0]),
            "label": meta.get("label", stem),
            "version": int(meta.get("version", 1)),
            "cubeUrl": f"looks/{name}",
            "sha256": sha256(path),
            "sizeBytes": os.path.getsize(path),
            "notes": meta.get("notes", ""),
        }
        if "minAppVersion" in meta:
            entry["minAppVersion"] = int(meta["minAppVersion"])
        entries.append(entry)

    manifest = {
        "formatVersion": 1,
        "catalogVersion": catalog_version,
        "looks": entries,
    }
    with open(MANIFEST, "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"catalogVersion={catalog_version}, {len(entries)} looks -> {MANIFEST}")
    for e in entries:
        print(f"  {e['lookId']} v{e['version']} ({e['sizeBytes']} bytes)")


if __name__ == "__main__":
    sys.exit(main())
