from __future__ import annotations

import os
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request


EXPECTED_ROOT = "/g-box"
DEFAULT_MP_URL = "http://mp.odn.cc"

REQUIRED_SECRET_ENV = (
    "MP_TEST_USERNAME",
    "MP_TEST_PASSWORD",
    "GY_TEST_GUANGYA_SHARE",
    "GY_TEST_XUNLEI_SHARE",
    "GY_TEST_MAGNET",
    "GY_TEST_ED2K",
)


def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    raise SystemExit(1)


def ok(message: str) -> None:
    print(f"[ OK ] {message}")


def require_env() -> dict[str, str]:
    values: dict[str, str] = {}
    missing: list[str] = []
    for key in REQUIRED_SECRET_ENV:
        value = (os.environ.get(key) or "").strip()
        if not value:
            missing.append(key)
        values[key] = value
    if missing:
        fail("missing GitHub Secrets: " + ", ".join(missing))
    ok("all required secret-backed inputs are present")
    return values


def validate_test_root() -> str:
    root = (os.environ.get("GUANGYA_TEST_ROOT") or EXPECTED_ROOT).rstrip("/") or "/"
    if root != EXPECTED_ROOT:
        fail(f"GUANGYA_TEST_ROOT must be exactly {EXPECTED_ROOT!r}, got {root!r}")
    ok(f"write-safety root pinned to {root}")
    return root


def validate_resources(values: dict[str, str]) -> None:
    gy = values["GY_TEST_GUANGYA_SHARE"]
    xl = values["GY_TEST_XUNLEI_SHARE"]
    magnet = values["GY_TEST_MAGNET"]
    ed2k = values["GY_TEST_ED2K"]

    if not gy.startswith(("https://www.guangyapan.com/", "https://guangyapan.com/")):
        fail("GY_TEST_GUANGYA_SHARE is not a GuangYa share URL")
    ok("GuangYa share input shape")

    if not xl.startswith("https://pan.xunlei.com/"):
        fail("GY_TEST_XUNLEI_SHARE is not a Xunlei share URL")
    ok("Xunlei share input shape")

    if not magnet.lower().startswith("magnet:?xt=urn:btih:"):
        fail("GY_TEST_MAGNET is not a BT magnet URI")
    ok("Magnet input shape")

    if not ed2k.lower().startswith("ed2k://|file|"):
        fail("GY_TEST_ED2K is not an ED2K file URI")
    ok("ED2K input shape")


def probe_moviepilot() -> None:
    base = (os.environ.get("MP_TEST_BASE_URL") or DEFAULT_MP_URL).strip().rstrip("/")
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        fail(f"invalid MP_TEST_BASE_URL: {base!r}")

    try:
        socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except OSError as exc:
        fail(f"MoviePilot DNS/connect preflight failed for {parsed.hostname}: {exc}")
    ok(f"MoviePilot host resolves: {parsed.hostname}")

    request = urllib.request.Request(
        base + "/",
        headers={"User-Agent": "GuangYaTransferAssistant-E2E/1.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            status = int(getattr(response, "status", 0) or 0)
            final_url = response.geturl()
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        final_url = exc.geturl()
    except Exception as exc:
        fail(f"MoviePilot HTTP preflight failed: {type(exc).__name__}: {exc}")

    if status < 200 or status >= 500:
        fail(f"MoviePilot returned unexpected HTTP status {status} ({final_url})")
    ok(f"MoviePilot reachable: HTTP {status} -> {final_url}")


def main() -> int:
    print("=== GuangYa Transfer Assistant E2E preflight ===")
    validate_test_root()
    values = require_env()
    validate_resources(values)
    probe_moviepilot()
    print("=== PRELIGHT PASS: no remote write operation was executed ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
