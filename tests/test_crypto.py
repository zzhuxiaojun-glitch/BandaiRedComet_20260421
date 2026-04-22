"""crypto.py 的边界单元测试。

关键目标：锁住那几个非显而易见的 JS ↔ Python 行为差异，防止以后
Python 版本 / json 实现 / pydantic 改动把签名算法悄悄打坏。
"""
from __future__ import annotations
import json

from bandai_sniper.crypto import (
    PUBLIC_KEY,
    SECRET_KEY,
    _coerce_leaves,
    _js_json_dumps_raw,
    _sort_and_coerce,
    aes_decrypt,
    aes_encrypt,
    build_signed_request,
)


# ═══════════════════════════════════════════════════════════════
# AES 加解密 —— key 不是 base64 这件事
# ═══════════════════════════════════════════════════════════════

def test_aes_key_is_24_byte_ascii_literal_not_base64():
    """secretKey 末尾 `==` 看着像 base64 但 JS 里是 Utf8.parse 字面量。
    必须是 24 字节 ASCII（AES-192）。"""
    assert SECRET_KEY == b"5p/9OgW9F5cJc0fOs0TXYA=="
    assert len(SECRET_KEY) == 24


def test_aes_roundtrip_utf8():
    plain = json.dumps({"spuId": "6521", "name": "里歇尔"}, ensure_ascii=False)
    ct = aes_encrypt(plain)
    back = aes_decrypt(ct)
    assert back == {"spuId": "6521", "name": "里歇尔"}


# ═══════════════════════════════════════════════════════════════
# _coerce_leaves —— JSON.stringify(u, replacer) 的 primitive→string 行为
# ═══════════════════════════════════════════════════════════════

def test_coerce_leaves_drops_none():
    assert _coerce_leaves({"a": 1, "b": None, "c": "x"}) == {"a": "1", "c": "x"}


def test_coerce_leaves_bool_lowercase():
    """JS `"" + true === "true"`，不是 `"True"`。"""
    assert _coerce_leaves({"flag": True}) == {"flag": "true"}
    assert _coerce_leaves({"flag": False}) == {"flag": "false"}


def test_coerce_leaves_nested_dict_preserved_primitives_stringified():
    """嵌套 dict 保留结构，只转叶子。"""
    inp = {"skuList": [{"skuId": 9266, "num": 1}]}
    out = _coerce_leaves(inp)
    assert out == {"skuList": [{"skuId": "9266", "num": "1"}]}


def test_coerce_leaves_drops_null_in_nested_list():
    inp = {"items": [1, None, 2]}
    assert _coerce_leaves(inp) == {"items": ["1", "2"]}


# ═══════════════════════════════════════════════════════════════
# _js_json_dumps_raw —— JS JSON.stringify 不带 replacer，数字原样
# ═══════════════════════════════════════════════════════════════

def test_js_json_dumps_raw_integer_float_as_int():
    """JS 里 142.0 和 142 无区别，JSON.stringify(142.0) === "142"。"""
    assert _js_json_dumps_raw([142.0]) == "[142]"
    assert _js_json_dumps_raw([142]) == "[142]"
    assert _js_json_dumps_raw({"x": 142.0}) == '{"x":142}'


def test_js_json_dumps_raw_fractional_float_preserved():
    # 非整数 float 保持
    out = _js_json_dumps_raw([20.5])
    assert out == "[20.5]"


def test_js_json_dumps_raw_no_spaces():
    assert _js_json_dumps_raw({"a": 1, "b": 2}) == '{"a":1,"b":2}'


# ═══════════════════════════════════════════════════════════════
# _sort_and_coerce —— JS `o(e, r, t)` 全逻辑
# ═══════════════════════════════════════════════════════════════

def test_sort_top_level_dict_keys_lexicographic():
    out = _sort_and_coerce({"b": "2", "a": "1", "c": "3"}, sign_mode=True)
    # Python 3.7+ dict 保留插入顺序，用 list(keys) 可验证
    assert list(out.keys()) == ["a", "b", "c"]


def test_sign_mode_top_array_wrapped_with_raw_json():
    """sign 路径的 inner JSON 不走 replacer → 数字保留原样。"""
    out = _sort_and_coerce([6, 10], sign_mode=True)
    # JSON.stringify([6,10]) === "[6,10]"
    assert out == {"str": "[6,10]"}


def test_encrypt_mode_top_array_uses_coerce_leaves():
    """encrypt 路径走 replacer → primitive 转字符串。"""
    out = _sort_and_coerce([6, 10], sign_mode=False)
    assert out == ["6", "10"]


def test_nested_array_preserved_in_both_modes():
    """嵌套 Array 在 sign 和 encrypt 都保留原结构，只有叶子转字符串。"""
    inp = {"skuList": [{"id": 1, "num": 2}]}
    a = _sort_and_coerce(inp, sign_mode=True)
    b = _sort_and_coerce(inp, sign_mode=False)
    assert a == {"skuList": [{"id": "1", "num": "2"}]}
    assert a == b  # 对 dict 入参，sign 和 encrypt 输出应一致


# ═══════════════════════════════════════════════════════════════
# md5 —— JS 的 UTF-16 截断 bug 必须在 Python 端复现
# ═══════════════════════════════════════════════════════════════

def test_md5_ascii_params_match_utf8():
    """纯 ASCII 的签名应该和 UTF-8 encode 的 md5 一样（历史兼容）。"""
    import hashlib
    req = build_signed_request(
        {"level": "2"}, user_token="dummy", method="GET",
    )
    sig = req["headers"]["signature"]
    # 对应的 combo 我们能手算出来
    combo = (
        f"dummy{{\"level\":\"2\"}}{req['headers']['nonce']}"
        f"{req['headers']['timestamp']}{PUBLIC_KEY}"
    )
    # 纯 ASCII 时两种 md5 等价
    expected = hashlib.md5(combo.encode("utf-8")).hexdigest().lower()
    assert sig == expected


def test_md5_chinese_chars_truncated_not_utf8():
    """含中文参数时，Python UTF-8 encode 和 JS charCodeAt&0xFF 结果不同。
    build_signed_request 必须走 charCodeAt 版本。"""
    import hashlib
    req = build_signed_request(
        {"city": "上海"}, user_token="dummy", method="GET",
    )
    sig = req["headers"]["signature"]

    # "上" = U+4E0A → charCodeAt&0xFF = 0x0A
    # "海" = U+6D77 → charCodeAt&0xFF = 0x77
    # 构造 JS 风格的字节序列
    sign_json = '{"city":"上海"}'
    combo = (
        f"dummy{sign_json}{req['headers']['nonce']}"
        f"{req['headers']['timestamp']}{PUBLIC_KEY}"
    )
    js_style = hashlib.md5(bytes(ord(c) & 0xFF for c in combo)).hexdigest().lower()
    utf8_style = hashlib.md5(combo.encode("utf-8")).hexdigest().lower()

    assert sig == js_style
    assert sig != utf8_style  # 确认两种方式结果不同，没搞错
    # 防回归：万一 Python 哪天改了默认 encode 也别让签名悄悄切回 utf8


# ═══════════════════════════════════════════════════════════════
# build_signed_request —— 集成 smoke
# ═══════════════════════════════════════════════════════════════

def test_build_signed_request_get_empty_params_no_url_suffix():
    req = build_signed_request({}, user_token="tok", method="GET")
    assert req["url_suffix"] == ""
    assert req["body"] == ""


def test_build_signed_request_get_with_params_has_encryption_url():
    req = build_signed_request({"id": "6521"}, user_token="tok", method="GET")
    assert req["url_suffix"].startswith("?encryptionUrlParams=")


def test_build_signed_request_post_empty_body():
    req = build_signed_request({}, user_token="tok", method="POST")
    assert req["body"] == "{}"


def test_build_signed_request_post_with_body_wraps():
    req = build_signed_request({"x": "1"}, user_token="tok", method="POST")
    body = json.loads(req["body"])
    assert "encryptionBodyParams" in body
    # 密文能解回来
    back = aes_decrypt(body["encryptionBodyParams"])
    assert back == {"x": "1"}


def test_build_signed_request_has_all_required_headers():
    req = build_signed_request({}, user_token="tok", method="GET")
    h = req["headers"]
    for name in ("api-access-token", "timestamp", "nonce", "signature", "trace_id"):
        assert name in h
    assert len(h["signature"]) == 32  # md5 hex
    assert h["signature"].islower()
