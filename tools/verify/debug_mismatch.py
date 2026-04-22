"""对失败的条目：反推 JS 实际生成的 encrypt JSON（解密出来），对比 Python 端生成的。"""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from bandai_sniper.crypto import (  # noqa: E402
    PUBLIC_KEY, SECRET_KEY, _sort_and_coerce, _js_json_dumps_raw,
    aes_decrypt, aes_encrypt,
)
from Crypto.Cipher import AES  # noqa: E402
from Crypto.Util.Padding import unpad  # noqa: E402
from base64 import b64decode  # noqa: E402

HAR = Path(sys.argv[1])


def header(e: dict, name: str) -> str:
    for h in e["request"]["headers"]:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def derive(sign_form, token, nonce, ts) -> tuple[str, str]:
    sj = json.dumps(sign_form, separators=(",", ":"), ensure_ascii=False)
    sig = hashlib.md5(f"{token}{sj}{nonce}{ts}{PUBLIC_KEY}".encode()).hexdigest().lower()
    return sj, sig


def main() -> int:
    har = json.loads(HAR.read_text(encoding="utf-8"))
    for e in har["log"]["entries"]:
        url = e["request"]["url"]
        if "confirmOrder" not in url and "createOrder" not in url:
            continue
        if e["request"]["method"] != "POST":
            continue

        real = header(e, "signature")
        token = header(e, "api-access-token")
        nonce = header(e, "nonce")
        ts = header(e, "timestamp")

        text = e["request"].get("postData", {}).get("text", "")
        body = json.loads(text)
        enc = body.get("encryptionBodyParams")
        real_encrypt_json_bytes = unpad(
            AES.new(SECRET_KEY, AES.MODE_ECB).decrypt(b64decode(enc)),
            AES.block_size,
        )
        real_encrypt_json = real_encrypt_json_bytes.decode("utf-8")
        params = json.loads(real_encrypt_json)

        # Python 端 sign form
        sign_form_py = _sort_and_coerce(params, sign_mode=True)
        encrypt_form_py = _sort_and_coerce(params, sign_mode=False)
        py_sign_json, py_sig = derive(sign_form_py, token, nonce, ts)
        py_encrypt_json = json.dumps(encrypt_form_py, separators=(",", ":"), ensure_ascii=False)

        if py_sig == real:
            continue  # 已通过

        print(f"\n══ {url.split('bandainamcoshanghai.com')[-1][:60]} ══")
        print(f"real sig : {real}")
        print(f"mine sig : {py_sig}")
        print(f"real encrypt len={len(real_encrypt_json)}, mine encrypt len={len(py_encrypt_json)}, sign len={len(py_sign_json)}")
        print(f"real == py_encrypt? {real_encrypt_json == py_encrypt_json}")
        print(f"py_sign == py_encrypt? {py_sign_json == py_encrypt_json}")

        # 签名是 md5(token + sign_json + nonce + ts + public_key) 小写
        # sign_json 一定和 real 对不上（否则签名也对）。找差异。
        # 我们没法直接看 JS 的 sign_json，但可以试所有常见变种，看哪个能产出 real sig。
        attempts = []
        # A) 和 encrypt JSON 完全一样
        attempts.append(("sign==encrypt(py)", py_encrypt_json))
        # B) Python 的 sign
        attempts.append(("sign(py)", py_sign_json))
        # C) real encrypt JSON 原样当 sign
        attempts.append(("sign=real_encrypt", real_encrypt_json))
        for name, sj in attempts:
            sig = hashlib.md5(f"{token}{sj}{nonce}{ts}{PUBLIC_KEY}".encode()).hexdigest().lower()
            mark = "✓" if sig == real else " "
            print(f" {mark} {name:24s} sig={sig}")
        break
    return 0


if __name__ == "__main__":
    sys.exit(main())
