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

App self-update section: put the release APK in server/app/ plus
server/app/app.json {"versionCode": N, "versionName": "x.y.z",
"notes": "...", "minSdk": 26}. The highest parsed APK version is emitted
only after its embedded version and signing certificate are verified.

Usage:
  python3 server/build_manifest.py           # bump catalogVersion, write manifest
  python3 server/build_manifest.py --keep    # keep catalogVersion

Serve locally:
  python3 -m http.server 8080 --directory server
  # then point the app at http://<LAN-IP>:8080/ via
  # ./gradlew assembleDebug -PLATENT_UPDATE_BASE_URL=http://<LAN-IP>:8080/
"""

import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

import release_signing as signing

HERE = os.path.dirname(os.path.abspath(__file__))
LOOKS = os.path.join(HERE, "looks")
MANIFEST = os.path.join(HERE, "manifest.json")
CATALOG = os.path.join(HERE, "catalog.json")


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def parsed_version(value: str) -> tuple[int, int, int]:
    match = re.search(r"v?(\d+)\.(\d+)\.(\d+)", value)
    if match is None:
        return 0, 0, 0
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def find_android_build_tool(name: str) -> str:
    tool_path = shutil.which(name)
    if tool_path is not None:
        return tool_path
    sdk_root = (
        os.environ.get("ANDROID_HOME")
        or os.environ.get("ANDROID_SDK_ROOT")
        or os.path.expanduser("~/Library/Android/sdk")
    )
    if not os.path.isdir(sdk_root):
        sdk_root = os.path.expanduser("~/Android/Sdk")
    candidates = glob.glob(os.path.join(sdk_root, "build-tools", "*", name))
    if candidates:
        return max(
            candidates,
            key=lambda path: tuple(
                int(part)
                for part in os.path.basename(os.path.dirname(path)).split(".")
                if part.isdigit()
            ),
        )
    sys.exit(
        f"ERROR: {name} was not found — install Android build-tools "
        "or set ANDROID_HOME before building the manifest"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="keep catalogVersion")
    ap.add_argument(
        "--baseline-manifest",
        help="published manifest used to reject version downgrades",
    )
    args = ap.parse_args()

    baseline_path = args.baseline_manifest or MANIFEST
    baseline_app = None
    if os.path.exists(baseline_path):
        with open(baseline_path) as f:
            baseline_app = json.load(f).get("app")
    elif args.baseline_manifest:
        sys.exit(f"ERROR: baseline manifest not found: {baseline_path}")

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

    # optional app self-update section: server/app/<file>.apk + app.json
    app_dir = os.path.join(HERE, "app")
    app_meta_path = os.path.join(app_dir, "app.json")
    if os.path.isdir(app_dir) and os.path.exists(app_meta_path):
        # newest by PARSED version, not by name: "v1.10.0" sorts before
        # "v1.9.28" lexicographically, which silently shipped the old APK
        # under the new versionCode (found preparing the v1.10.0 release)
        def version_key(name: str) -> tuple[tuple[int, int, int], str]:
            return parsed_version(name), name

        apks = sorted(
            (f for f in os.listdir(app_dir) if f.endswith(".apk")),
            key=version_key,
        )
        if apks:
            apk_name = apks[-1]
            apk_path = os.path.join(app_dir, apk_name)
            with open(app_meta_path) as f:
                meta = json.load(f)
            declared_code = int(meta["versionCode"])
            declared_name = str(meta["versionName"])
            if baseline_app is not None:
                baseline_code = int(baseline_app["versionCode"])
                baseline_name = str(baseline_app["versionName"])
                if declared_code < baseline_code:
                    sys.exit(
                        f"ERROR: versionCode {declared_code} is lower than the "
                        f"published baseline {baseline_code} ({baseline_name})"
                    )
                if args.baseline_manifest and declared_code == baseline_code:
                    sys.exit(
                        f"ERROR: versionCode {declared_code} is already published; "
                        "the next OTA release must use a higher versionCode"
                    )
                if declared_code == baseline_code and declared_name != baseline_name:
                    sys.exit(
                        f"ERROR: versionCode {declared_code} is already published "
                        f"as {baseline_name}, not {declared_name}"
                    )
                if parsed_version(declared_name) < parsed_version(baseline_name):
                    sys.exit(
                        f"ERROR: versionName {declared_name} is lower than the "
                        f"published baseline {baseline_name}"
                    )
            expected = f"latent-v{meta['versionName']}.apk"
            if apk_name != expected:
                sys.exit(
                    f"ERROR: app.json says v{meta['versionName']} but the newest "
                    f"APK in server/app/ is {apk_name} — drop {expected} in "
                    "first (or fix app.json), then re-run"
                )
            # stale-build trap (bit us on v1.10.1): if assembleRelease
            # didn't actually run, the cp stages the PREVIOUS build output
            # under the new name — metadata all self-consistent, binary
            # unchanged. A new release must never be byte-identical to an
            # already-released APK.
            new_sha = sha256(apk_path)
            for other in apks[:-1]:
                if sha256(os.path.join(app_dir, other)) == new_sha:
                    sys.exit(
                        f"ERROR: {apk_name} is byte-identical to {other} — "
                        "the build output is stale. Run ./gradlew clean "
                        "assembleRelease and re-copy the APK, then re-run"
                    )
            aapt2_path = find_android_build_tool("aapt2")
            badging_result = subprocess.run(
                [aapt2_path, "dump", "badging", apk_path],
                check=False,
                capture_output=True,
                text=True,
            )
            if badging_result.returncode != 0:
                sys.exit(
                    f"ERROR: aapt2 could not inspect {apk_name}: "
                    f"{badging_result.stderr.strip()}"
                )
            badging = re.search(
                r"^package: .*?versionCode='(\d+)'.*?versionName='([^']+)'",
                badging_result.stdout,
                re.MULTILINE,
            )
            if badging is None:
                sys.exit(f"ERROR: aapt2 returned no package version for {apk_name}")
            embedded_code = int(badging.group(1))
            embedded_name = badging.group(2)
            if embedded_code != declared_code or embedded_name != declared_name:
                sys.exit(
                    f"ERROR: APK embeds versionCode {embedded_code} / "
                    f"versionName {embedded_name}, but app.json declares "
                    f"versionCode {declared_code} / versionName {declared_name}"
                )
            apksigner_path = find_android_build_tool("apksigner")
            signature_result = subprocess.run(
                [apksigner_path, "verify", "--print-certs", apk_path],
                check=False,
                capture_output=True,
                text=True,
            )
            if signature_result.returncode != 0:
                sys.exit(
                    f"ERROR: apksigner could not verify {apk_name}: "
                    f"{signature_result.stderr.strip()}"
                )
            certificate_sha256 = signing.certificate_sha256(signature_result.stdout)
            if certificate_sha256 is None:
                sys.exit(
                    f"ERROR: apksigner returned no signing certificate for {apk_name}"
                )
            if certificate_sha256 != signing.EXPECTED_CERTIFICATE_SHA256:
                sys.exit(
                    f"ERROR: APK signing certificate {certificate_sha256} does not "
                    "match the installed-app certificate "
                    f"{signing.EXPECTED_CERTIFICATE_SHA256}"
                )
            manifest["app"] = {
                "versionCode": int(meta["versionCode"]),
                "versionName": meta["versionName"],
                "apkUrl": f"app/{apk_name}",
                "sha256": sha256(apk_path),
                "sizeBytes": os.path.getsize(apk_path),
                "notes": meta.get("notes", ""),
            }
            if "minSdk" in meta:
                manifest["app"]["minSdk"] = int(meta["minSdk"])
            print(
                f"  app v{meta['versionName']} ({meta['versionCode']}) "
                f"{os.path.getsize(apk_path)} bytes"
            )
        else:
            print("  app.json present but no .apk in server/app/ — skipped")

    with open(MANIFEST, "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"catalogVersion={catalog_version}, {len(entries)} looks -> {MANIFEST}")
    for e in entries:
        print(f"  {e['lookId']} v{e['version']} ({e['sizeBytes']} bytes)")


if __name__ == "__main__":
    sys.exit(main())
