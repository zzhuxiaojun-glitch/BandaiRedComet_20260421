"""对 HAR 文件做脱敏：去掉 CK、手机号、订单号、openid 等敏感信息。

用法:
    python sanitize_har.py bandai_capture.har
    → 生成 bandai_capture.sanitized.har
"""

import json
import re
import sys
from pathlib import Path


PATTERNS = [
    # 手机号
    (re.compile(r"\b1[3-9]\d{9}\b"), "REDACTED_PHONE"),
    # 身份证
    (re.compile(r"\b\d{17}[\dXx]\b"), "REDACTED_IDCARD"),
    # openid（微信）
    (re.compile(r'"openId"\s*:\s*"[^"]+"', re.I), '"openId":"REDACTED_OPENID"'),
    (re.compile(r'"openid"\s*:\s*"[^"]+"'), '"openid":"REDACTED_OPENID"'),
    # unionid
    (re.compile(r'"unionId"\s*:\s*"[^"]+"', re.I), '"unionId":"REDACTED_UNIONID"'),
    # 微信支付 prepay_id
    (re.compile(r'"prepay[_]?id"\s*:\s*"[^"]+"', re.I), '"prepayId":"REDACTED_PREPAY"'),
    (re.compile(r'"paySign"\s*:\s*"[^"]+"'), '"paySign":"REDACTED_SIGN"'),
    (re.compile(r'"nonceStr"\s*:\s*"[^"]+"'), '"nonceStr":"REDACTED_NONCE"'),
]

SENSITIVE_HEADERS = {"api-access-token", "authorization", "cookie", "x-token"}


def scrub_text(text: str) -> str:
    if not text:
        return text
    for pat, repl in PATTERNS:
        text = pat.sub(repl, text)
    return text


def scrub_headers(headers: list[dict]) -> list[dict]:
    for h in headers:
        if h.get("name", "").lower() in SENSITIVE_HEADERS:
            v = h.get("value", "")
            h["value"] = f"REDACTED_{h['name'].upper().replace('-', '_')}_len{len(v)}"
    return headers


def sanitize(har_path: Path) -> Path:
    out_path = har_path.with_suffix(".sanitized.har")
    with har_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    count = 0
    for entry in data.get("log", {}).get("entries", []):
        req = entry.get("request", {})
        if "headers" in req:
            scrub_headers(req["headers"])
        if req.get("postData", {}).get("text"):
            req["postData"]["text"] = scrub_text(req["postData"]["text"])
        if "queryString" in req:
            for q in req["queryString"]:
                if q.get("name", "").lower() in {"token", "access_token", "openid"}:
                    q["value"] = f"REDACTED_{q['name'].upper()}"

        resp = entry.get("response", {})
        if "headers" in resp:
            scrub_headers(resp["headers"])
        if resp.get("content", {}).get("text"):
            resp["content"]["text"] = scrub_text(resp["content"]["text"])

        count += 1

    with out_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return out_path


def main() -> int:
    if len(sys.argv) != 2:
        print("用法: python sanitize_har.py <input.har>")
        return 1
    src = Path(sys.argv[1])
    if not src.exists():
        print(f"找不到文件: {src}")
        return 1
    out = sanitize(src)
    print(f"✅ 已生成脱敏文件: {out}")
    print(f"   大小: {out.stat().st_size / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
