"""
Re-derive signatures for every encrypted request in bandai_capture.har and
compare against the real headers. Confirms that our _sort_and_coerce rule
matches the JS o(e, r, t).
"""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from bandai_sniper.crypto import (  # noqa: E402
    PUBLIC_KEY,
    _sort_and_coerce,
    aes_decrypt,
)

HAR_PATH = Path(
    "/mnt/c/2025.10.16_move/IVIS_new/IT相关/【自开发_代码&发布版win仓库】"
    "/BandaiRedComet_win/capture/bandai_capture.har"
)


def header(entry: dict, name: str) -> str:
    for h in entry["request"]["headers"]:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def derive_sign(params, token: str, nonce: str, timestamp: str) -> str:
    sign_form = _sort_and_coerce(params, sign_mode=True)
    sign_json = json.dumps(sign_form, separators=(",", ":"), ensure_ascii=False)
    combo = f"{token}{sign_json}{nonce}{timestamp}{PUBLIC_KEY}"
    return hashlib.md5(bytes(ord(c) & 0xFF for c in combo)).hexdigest().lower()


def main() -> int:
    har = json.loads(HAR_PATH.read_text(encoding="utf-8"))
    entries = har["log"]["entries"]

    checked = 0
    ok = 0
    for entry in entries:
        url = entry["request"]["url"]
        if "bandainamcoshanghai.com/api/" not in url:
            continue

        real_sig = header(entry, "signature")
        token = header(entry, "api-access-token")
        nonce = header(entry, "nonce")
        timestamp = header(entry, "timestamp")
        method = entry["request"]["method"]

        if not real_sig or not timestamp:
            continue

        # Extract params
        params = None
        if method == "GET":
            qs = parse_qs(urlparse(url).query)
            enc = qs.get("encryptionUrlParams", [None])[0]
            if enc is None:
                params = {}
            else:
                try:
                    params = aes_decrypt(enc)
                except Exception:
                    continue
        else:
            post_data = entry["request"].get("postData", {})
            text = post_data.get("text", "")
            if not text or text == "{}":
                params = {}
            else:
                try:
                    body = json.loads(text)
                    enc = body.get("encryptionBodyParams")
                    params = aes_decrypt(enc) if enc else {}
                except Exception:
                    continue

        our_sig = derive_sign(params, token, nonce, timestamp)
        checked += 1
        status = "OK " if our_sig == real_sig else "FAIL"
        if our_sig == real_sig:
            ok += 1
        else:
            short_url = url.split("bandainamcoshanghai.com")[-1][:80]
            print(f"[{status}] {method} {short_url}")
            print(f"       params={json.dumps(params, ensure_ascii=False)[:120]}")
            print(f"       real={real_sig}  ours={our_sig}")

    print(f"\n{ok}/{checked} signatures matched.")
    return 0 if ok == checked and checked > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
