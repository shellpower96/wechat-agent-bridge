# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/) 与 [SemVer](https://semver.org/)。

## [1.2.0] - 2026-09-05
### Added
- `LICENSE`（MIT）
- `CHANGELOG.md`
- GitHub Actions CI：自动做 Python 语法检查 + shell 语法检查 + JSON 校验 + 文件清单断言
### Changed
- 从 GitHub 侧固化发布流程（gh / release 资产）

## [1.1.0] - 2026-09-05
### Added
- `docs/INSTALL.md`：零卡点安装手册（前置环境矩阵 / 分步命令 / 卡点清单）
- 内嵌 `scripts/inject_load_dylib.py` 与 `scripts/FridaGadget.config`（消除外部文件依赖）
### Changed
- `scripts/rebuild_wechat.sh` 自包含：自动下载并校验 269109 dmg + FridaGadget 17.8.0；
  去除 Sparkle 自更新；纯 ad-hoc 签名
- `README.md` 改版：前置环境 + 安装引导指向 INSTALL.md

## [1.0.0] - 2026-09-02
### Added
- `bridge.py`：agent 无关核心（白名单 / HumanLoop 状态机 / OneBot 收发 / REST 管理端点）
- `mcp_server.py`：MCP server（stdio JSON-RPC，反向管理微信客服）
- `providers/`：hermes / claude / openai_compat 适配器
- `scripts/`：start / stop / doctor / rebuild_wechat
- `docs/`：ARCHITECTURE / RUNBOOK / MIGRATION
- `skills/`：Hermes / Claude skill 封装
