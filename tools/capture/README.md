# 抓包工具箱

> 这三件工具组合起来 = "抓 + 自检 + 脱敏"一条龙

| 文件 | 作用 | 平台 |
|---|---|---|
| `start_capture.ps1` | 自动装 mitmproxy，以 local 模式按进程名抓微信流量 | Windows（管理员）|
| `bandai_filter.py` | mitmproxy addon，只保留万代域名流量 | 自动加载 |
| `inspect_har.py` | 打印 HAR 里抓到了什么，自检是否齐全 | 任意 |
| `sanitize_har.py` | 脱敏 CK / 手机号 / 订单号 | 任意 |

## 快速流程

```
[Windows PowerShell（管理员）]
  ↓ 双击 start_capture.ps1
[微信 PC，在小程序里点 7 步]
  ↓ Ctrl+C 停止
[任意 shell]
  ↓ python inspect_har.py bandai_capture.har
  ↓ python sanitize_har.py bandai_capture.har
→ 把 bandai_capture.sanitized.har 扔到 captures/ 目录
```

## 细节见 [`3_抓包指南.md`](../../3_抓包指南.md)。
