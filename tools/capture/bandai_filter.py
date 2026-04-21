"""mitmproxy addon: 只保留万代域名的流量，减小 HAR 体积。

用法（见 start_capture.ps1）:
    mitmdump --mode local:WeChat,WeChatAppEx -s bandai_filter.py --set hardump=bandai_capture.har
"""

from mitmproxy import http

TARGET_HOST_SUFFIX = ".bandainamcoshanghai.com"


def request(flow: http.HTTPFlow) -> None:
    host = flow.request.host or ""
    if not host.endswith(TARGET_HOST_SUFFIX):
        # 标记为不感兴趣的流量，让 hardump 跳过
        flow.metadata["drop"] = True


def response(flow: http.HTTPFlow) -> None:
    if flow.metadata.get("drop"):
        # hardump 不支持 skip，只能靠 kill：把它从流量队列里删掉
        flow.kill()
