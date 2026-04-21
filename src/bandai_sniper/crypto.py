"""
Bandai Namco Shanghai 小程序加密/签名实现

源头：解包 wx1cb4557915b2b7cd/129/__APP__.wxapkg 得到。
密钥：硬编码在 app-service.js → module `EEE384F5E0022CCF8885ECF2CC2FACB7.js`
加密函数：app-service.js 中 `aesEncrypt` / `apiSign`
"""
from __future__ import annotations
import hashlib
import json
import random
import time
import uuid
from base64 import b64decode, b64encode
from typing import Any

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

# 注意：JS 里 `CryptoJS.enc.Utf8.parse("5p/9OgW9F5cJc0fOs0TXYA==")` 是把字符串当
# UTF-8 字面量解析（不 base64 解码）。所以 AES key 的字节就是这 24 个 ASCII 字符。
SECRET_KEY: bytes = b"5p/9OgW9F5cJc0fOs0TXYA=="
PUBLIC_KEY: str = "EGs7AgSG7k3aj6dGnLnbPL3125OjI2Bq"

assert len(SECRET_KEY) == 24, f"AES-192 需要 24 字节 key, got {len(SECRET_KEY)}"


def aes_encrypt(plaintext: str) -> str:
    """AES-192-ECB + PKCS7, 输出 base64 字符串"""
    cipher = AES.new(SECRET_KEY, AES.MODE_ECB)
    padded = pad(plaintext.encode("utf-8"), AES.block_size)
    return b64encode(cipher.encrypt(padded)).decode("ascii")


def aes_decrypt(ciphertext_b64: str) -> Any:
    """AES-192-ECB + PKCS7 解密，结果按 JSON 解析"""
    cipher = AES.new(SECRET_KEY, AES.MODE_ECB)
    raw = b64decode(ciphertext_b64)
    return json.loads(unpad(cipher.decrypt(raw), AES.block_size).decode("utf-8"))


def _sort_and_coerce(data: Any, keep_nested_objects: bool) -> Any:
    """
    还原 app-service.js 中的 `o(e, r, t)` 函数。

    - 对象按 key 字典序排序
    - 如果是数组：
        * keep_nested_objects=True（加密路径）→ 返回深拷贝的原数组
        * keep_nested_objects=False（签名路径）→ 包成 {"str": JSON.stringify(arr)}
    - 最后用 JSON.stringify 的 replacer：
        * null / undefined → 丢弃
        * 嵌套对象：keep_nested_objects=True 原样，False 变成 JSON 字符串
        * 其余 → String(v)
    """
    if isinstance(data, list):
        if keep_nested_objects:
            return json.loads(json.dumps(data))
        return {"str": json.dumps(data, separators=(",", ":"), ensure_ascii=False)}

    if isinstance(data, dict):
        sorted_items = sorted(data.items(), key=lambda kv: kv[0])
        result: dict = {}
        for k, v in sorted_items:
            if v is None:
                continue
            if isinstance(v, (dict, list)):
                if keep_nested_objects:
                    result[k] = _sort_and_coerce(v, keep_nested_objects=True)
                else:
                    result[k] = json.dumps(
                        _sort_and_coerce(v, keep_nested_objects=True),
                        separators=(",", ":"),
                        ensure_ascii=False,
                    )
            elif isinstance(v, bool):
                result[k] = "true" if v else "false"
            else:
                result[k] = str(v)
        return result

    return data


def build_signed_request(
    params: dict | list | None,
    user_token: str,
    *,
    time_offset_ms: int = 0,
    method: str = "POST",
    encryption_enable: bool = True,
) -> dict:
    """
    返回一个 dict: {
        "headers": {...},
        "url_suffix": "?encryptionUrlParams=..." 或 "",
        "body": "{...json...}" 或 "",
    }
    可直接用于 httpx 请求。

    time_offset_ms: 服务器时钟与本地时钟的差（ms）。JS 里通过 base/getTimestamp 拉取后
                    存进 `this.timeout`。先填 0，后面压测发现 timestamp 被拒再实现。
    encryption_enable: 线上永远是 True。留参数只是对齐源码。
    """
    if params is None:
        params = {}

    timestamp = str(int(time.time() * 1000) + time_offset_ms)
    nonce = random.randint(0, 999_999)

    sign_form = _sort_and_coerce(params, keep_nested_objects=False)
    encrypt_form = _sort_and_coerce(params, keep_nested_objects=True)

    sign_json = json.dumps(sign_form, separators=(",", ":"), ensure_ascii=False)
    encrypt_json = json.dumps(encrypt_form, separators=(",", ":"), ensure_ascii=False)

    signature = hashlib.md5(
        f"{user_token}{sign_json}{nonce}{timestamp}{PUBLIC_KEY}".encode("utf-8")
    ).hexdigest().lower()

    trace_id = f"{uuid.uuid4()}_{timestamp}"

    ct = aes_encrypt(encrypt_json) if encryption_enable else encrypt_json

    headers = {
        "api-access-token": user_token or "",
        "timestamp": timestamp,
        "nonce": str(nonce),
        "signature": signature,
        "trace_id": trace_id,
        "Content-Type": "application/json",
    }

    url_suffix = ""
    body = ""
    is_get = method.upper() == "GET"
    if encryption_enable:
        empty = encrypt_json == "{}"
        if is_get:
            if not empty:
                from urllib.parse import quote
                # 注意：JS 源码用的是 encodeURIComponent（单次编码）。
                url_suffix = f"?encryptionUrlParams={quote(ct, safe='')}"
        else:
            if empty:
                body = "{}"
            else:
                body = json.dumps({"encryptionBodyParams": ct}, separators=(",", ":"))
    else:
        body = encrypt_json if not is_get else ""

    return {"headers": headers, "url_suffix": url_suffix, "body": body}


if __name__ == "__main__":
    # 快速自检：用一个捕获的响应密文做往返解密验证
    sample_ct = "APVSZZC5KMsWvhOIVB48vPLXgJ7/3SSmTazrP+lGiQCn24EpeiVFDxXRg9eMHwtQ"
    try:
        out = aes_decrypt(sample_ct)
        print(f"解密成功（截断）: {str(out)[:200]}")
    except Exception as e:
        print(f"解密失败: {e}")

    req = build_signed_request({"spuId": "P001"}, user_token="dummy_token", method="POST")
    print(json.dumps(req, ensure_ascii=False, indent=2)[:500])
