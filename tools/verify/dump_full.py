"""扒指定接口的完整请求/响应（不截断），用于对照 api.py 入参。"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from bandai_sniper.crypto import aes_decrypt  # noqa: E402

HAR_PATH = Path(sys.argv[1])
KEYWORDS = sys.argv[2:]  # 匹配 URL 包含其中任一即打印


def main() -> int:
    har = json.loads(HAR_PATH.read_text(encoding="utf-8"))
    shown = 0
    for entry in har["log"]["entries"]:
        url = entry["request"]["url"]
        if "bandainamcoshanghai.com/api/" not in url:
            continue
        if KEYWORDS and not any(k in url for k in KEYWORDS):
            continue
        method = entry["request"]["method"]
        parsed = urlparse(url)

        # 请求
        req = None
        if method == "GET":
            qs = parse_qs(parsed.query)
            enc = qs.get("encryptionUrlParams", [None])[0]
            if enc:
                for c in (enc, unquote(enc), unquote(unquote(enc))):
                    try:
                        req = aes_decrypt(c)
                        break
                    except Exception:
                        pass
            else:
                req = {k: v[0] for k, v in qs.items()}
        else:
            text = entry["request"].get("postData", {}).get("text", "")
            if text and text != "{}":
                try:
                    body = json.loads(text)
                    enc = body.get("encryptionBodyParams")
                    req = aes_decrypt(enc) if enc else body
                except Exception as e:
                    req = f"<err: {e}>"
            else:
                req = {}

        # 响应
        rt = entry.get("response", {}).get("content", {}).get("text", "")
        resp = None
        if rt:
            try:
                resp = aes_decrypt(rt.strip())
            except Exception:
                try:
                    resp = json.loads(rt)
                except Exception as e:
                    resp = f"<err: {e}>"

        print(f"\n{'='*70}")
        print(f"  {method} {parsed.path}")
        print(f"{'='*70}")
        print(f"REQ  : {json.dumps(req, ensure_ascii=False, indent=2)}")
        print(f"RESP : {json.dumps(resp, ensure_ascii=False, indent=2)}")
        shown += 1

    print(f"\n\n共 {shown} 条匹配。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
