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


def _coerce_leaves(obj: Any) -> Any:
    """
    递归：Object/Array 结构保持，null 丢弃，其他叶子用 String(v) 规则转字符串。

    对应 JS replacer（其中 t=encryptionEnable=true 恒成立）：
        r instanceof Object ? t ? r : ... : "" + r
    所以 Object/Array 保持原样，primitive 转字符串；null/undefined 丢弃。
    """
    if obj is None:
        return None
    if isinstance(obj, dict):
        out: dict = {}
        for k, v in obj.items():
            coerced = _coerce_leaves(v)
            if coerced is None:
                continue
            out[k] = coerced
        return out
    if isinstance(obj, list):
        result = []
        for v in obj:
            coerced = _coerce_leaves(v)
            if coerced is None:
                continue
            result.append(coerced)
        return result
    if isinstance(obj, bool):
        return "true" if obj else "false"
    return str(obj)


def _js_number_default(obj: Any) -> Any:
    """json.dumps 的 default，把 Python 的整数值 float(142.0) 还原成 int(142)，
    以匹配 JS `JSON.stringify(142.0) === "142"` 的行为。
    （float 叶子被 _coerce_leaves 转字符串了不会走到这里；只处理嵌套 raw 数组的情况）"""
    if isinstance(obj, float) and obj.is_integer():
        return int(obj)
    raise TypeError(f"not json-serializable: {type(obj)}")


def _js_json_dumps_raw(obj: Any) -> str:
    """模拟 JS `JSON.stringify(obj)`（无 replacer）：
    - Python float 142.0 → "142"（JS 数字无 int/float 之分）
    - 其余按 JSON 标准序列化
    实现方式：递归把整数值 float 转成 int，再 json.dumps。
    """
    def norm(v):
        if isinstance(v, float) and v.is_integer():
            return int(v)
        if isinstance(v, dict):
            return {k: norm(x) for k, x in v.items()}
        if isinstance(v, list):
            return [norm(x) for x in v]
        return v
    return json.dumps(norm(obj), separators=(",", ":"), ensure_ascii=False)


def _sort_and_coerce(data: Any, *, sign_mode: bool) -> Any:
    """
    还原 app-service.js 中的 `o(e, r, t)`，t=encryptionEnable=true 恒真。

    JS 语义（关键）：
      - 顶层如果是 Array：
          sign (r=false) → u = {str: JSON.stringify(原数组)}  ← 不经过 replacer，数字原样
          encrypt (r=true) → u = JSON.parse(JSON.stringify(原数组))  ← 然后走 replacer primitive→str
      - 顶层是 Object：按字典序重建 key；sign / encrypt 行为一致
      - 然后 `JSON.stringify(u, replacer)` 把所有 primitive 叶子转字符串、null/undefined 丢弃
    """
    if isinstance(data, list):
        if sign_mode:
            # 关键：JSON.stringify(原数组) 不走 replacer，数字不转字符串
            return {"str": _js_json_dumps_raw(data)}
        # encrypt 路径：深拷贝后走 replacer 叶子转字符串
        return _coerce_leaves(data)

    if isinstance(data, dict):
        sorted_top = {k: data[k] for k in sorted(data.keys())}
        return _coerce_leaves(sorted_top)

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

    sign_form = _sort_and_coerce(params, sign_mode=True)
    encrypt_form = _sort_and_coerce(params, sign_mode=False)

    sign_json = json.dumps(sign_form, separators=(",", ":"), ensure_ascii=False)
    encrypt_json = json.dumps(encrypt_form, separators=(",", ":"), ensure_ascii=False)

    # 注意：小程序的 md5 实现是一个老式手搓版本（F86FDFF6...js），
    # 内部 `(255 & r.charCodeAt(n / 8))` 把 JS 字符串的每个 UTF-16 码点
    # 只取低 8 位当字节。ASCII 字符无差别，但中文字符会被**截断**到低字节。
    # 必须复现这个行为：对字符串的每个字符取 ord(c) & 0xFF。
    combo = f"{user_token}{sign_json}{nonce}{timestamp}{PUBLIC_KEY}"
    signature = hashlib.md5(
        bytes(ord(c) & 0xFF for c in combo)
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
