# BandaiRedComet · 万代南宫梦抢购脚本

> 项目代号源自机动战士高达中的「红色彗星」—— 象征"比别人快 3 倍"。

## 文档索引

| 编号 | 文档 | 读者 |
|---|---|---|
| 1 | [CK 分析与方案建议](./1_CK分析与方案建议.md) | 所有人 |
| 2 | [PRD 产品需求文档](./2_PRD.md) | 运维者 |
| 3 | [抓包指南](./3_抓包指南.md) | 运维者 |
| 4 | 功能介绍（待出） | 使用者 |
| 5 | 使用指南（待出） | 使用者 |

## 目录结构

```
BandaiRedComet_20260421/
├── 1_CK分析与方案建议.md
├── 2_PRD.md
├── 3_抓包指南.md
├── README.md                   ← 本文件
├── src/                        ← Python 脚手架
│   ├── requirements.txt
│   ├── config.example.yaml
│   └── bandai_sniper/
│       ├── __main__.py         CLI 入口
│       ├── config.py           pydantic schema
│       ├── client.py           httpx 封装 + CK 注入 + 日志
│       ├── api.py              万代接口（含 TODO(抓包) 占位）
│       ├── timer.py            NTP 校时 + 精确倒计时
│       ├── sniper.py           编排：precheck → countdown → fire
│       └── notify.py           Bark / Server酱 / 飞书
├── captures/                   ← 抓包 HAR 放这里
├── logs/                       ← 运行日志
└── 万代上号/                    ← 外部工具（抓 Token 的 EXE）
```

## 当前进度

- [x] M0 · CK 分析
- [x] M1 · PRD / 抓包指南 / 代码脚手架
- [ ] **M2 · 抓包**（⚠️ 阻塞下一步，等 `captures/bandai_capture.sanitized.har`）
- [ ] M3 · 补完 `api.py` 后端到端跑通
- [ ] M4 · 写功能介绍 + 使用指南

## Quick Start（阶段性）

```bash
cd src
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml
# 编辑 config.yaml 填 CK 等字段

# 仅做 NTP 校时测试
python -m bandai_sniper ntp

# 预检（会调一个 whoami 接口，抓包前会 404，正常）
python -m bandai_sniper check

# 真正抢单（等抓包完成、api.py 补完后再跑）
python -m bandai_sniper run
```
