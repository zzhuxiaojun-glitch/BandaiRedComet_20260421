"""
从 HAR 里把每个加密接口的 URL / 方法 / 请求明文 / 响应明文全扒出来，
一行一个，方便填 api.py。
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from bandai_sniper.crypto import aes_decrypt  # noqa: E402

HAR_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
    "/mnt/c/2025.10.16_move/IVIS_new/IT相关/【自开发_代码&发布版win仓库】"
    "/BandaiRedComet_win/capture/bandai_capture.har"
)


def main() -> int:
    har = json.loads(HAR_PATH.read_text(encoding="utf-8"))
    entries = har["log"]["entries"]

    seen_paths: dict[tuple[str, str], dict] = {}

    for entry in entries:
        url = entry["request"]["url"]
        if "bandainamcoshanghai.com/api/" not in url:
            continue
        method = entry["request"]["method"]
        parsed = urlparse(url)
        path = parsed.path
        key = (method, path)

        # 已经记录过同路径同方法就跳过（去重）
        if key in seen_paths:
            continue

        # ── 入参
        req_params = None
        if method == "GET":
            qs = parse_qs(parsed.query)
            enc = qs.get("encryptionUrlParams", [None])[0]
            if enc:
                # HAR 里可能已经被浏览器/工具叠一层 URL 编码（%25 → %）
                last_err = None
                for candidate in (enc, unquote(enc), unquote(unquote(enc))):
                    try:
                        req_params = aes_decrypt(candidate)
                        break
                    except Exception as e:
                        last_err = e
                else:
                    req_params = f"<decrypt err: {last_err}>"
            else:
                req_params = dict((k, v[0] if len(v) == 1 else v) for k, v in qs.items())
        else:
            post = entry["request"].get("postData", {})
            text = post.get("text", "")
            if text and text != "{}":
                try:
                    body = json.loads(text)
                    enc = body.get("encryptionBodyParams")
                    req_params = aes_decrypt(enc) if enc else body
                except Exception as e:
                    req_params = f"<parse err: {e}>"
            else:
                req_params = {}

        # ── 响应：实测整个响应体就是 base64 AES 密文（不是 JSON 外壳）
        resp_text = entry.get("response", {}).get("content", {}).get("text", "")
        resp_decoded = None
        if resp_text:
            try:
                resp_decoded = aes_decrypt(resp_text.strip())
            except Exception:
                try:
                    resp_decoded = json.loads(resp_text)
                except Exception as e:
                    resp_decoded = f"<resp decrypt err: {e}>"

        seen_paths[key] = {"req": req_params, "resp": resp_decoded}

    # 打印汇总
    for (method, path), info in sorted(seen_paths.items(), key=lambda x: (x[0][1], x[0][0])):
        print(f"\n── {method} {path}")
        req_str = json.dumps(info["req"], ensure_ascii=False)[:200]
        print(f"   REQ : {req_str}")
        resp = info["resp"]
        if isinstance(resp, dict):
            resp_str = json.dumps(resp, ensure_ascii=False)[:300]
            print(f"   RESP: {resp_str}")
        else:
            print(f"   RESP: {resp}")

    print(f"\n共 {len(seen_paths)} 个不同接口")
    return 0


if __name__ == "__main__":
    sys.exit(main())
