"""对新 HAR 里每个加密请求重新复现签名，确认 2026-04-22 HAR 全部通过。"""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from bandai_sniper.crypto import PUBLIC_KEY, _sort_and_coerce, aes_decrypt  # noqa: E402

HAR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("tools/bandai_capture_20260422.har")


def header(e: dict, name: str) -> str:
    for h in e["request"]["headers"]:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def derive(params, token: str, nonce: str, timestamp: str) -> str:
    sign_form = _sort_and_coerce(params, sign_mode=True)
    sign_json = json.dumps(sign_form, separators=(",", ":"), ensure_ascii=False)
    combo = f"{token}{sign_json}{nonce}{timestamp}{PUBLIC_KEY}"
    return hashlib.md5(bytes(ord(c) & 0xFF for c in combo)).hexdigest().lower()


def main() -> int:
    har = json.loads(HAR.read_text(encoding="utf-8"))
    ok = fail = skip = 0
    failures: list[tuple] = []
    for e in har["log"]["entries"]:
        url = e["request"]["url"]
        if "bandainamcoshanghai.com/api/" not in url:
            continue
        real = header(e, "signature")
        token = header(e, "api-access-token")
        nonce = header(e, "nonce")
        ts = header(e, "timestamp")
        method = e["request"]["method"]
        if not (real and ts):
            skip += 1
            continue

        params = None
        if method == "GET":
            qs = parse_qs(urlparse(url).query)
            enc = qs.get("encryptionUrlParams", [None])[0]
            if enc:
                for c in (enc, unquote(enc), unquote(unquote(enc))):
                    try:
                        params = aes_decrypt(c)
                        break
                    except Exception:
                        pass
            else:
                params = {}
        else:
            text = e["request"].get("postData", {}).get("text", "")
            if not text or text == "{}":
                params = {}
            else:
                try:
                    body = json.loads(text)
                    enc = body.get("encryptionBodyParams")
                    params = aes_decrypt(enc) if enc else body
                except Exception as ex:
                    skip += 1
                    continue
        if params is None:
            skip += 1
            continue

        mine = derive(params, token, nonce, ts)
        if mine == real:
            ok += 1
        else:
            fail += 1
            short = url.split("bandainamcoshanghai.com")[-1][:80]
            failures.append((method, short, real, mine, params))

    print(f"\n{ok} 通过 / {fail} 失败 / {skip} 跳过 / 共 {ok+fail+skip}")
    for m, u, real, mine, p in failures[:10]:
        print(f"\n[FAIL] {m} {u}")
        print(f"  real={real}  mine={mine}")
        print(f"  params[:200]={json.dumps(p, ensure_ascii=False)[:200]}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
