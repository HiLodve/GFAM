# GFAM Wiki

**GFAM（少女全自动 / Girl Fully Automatic）** 是一个面向《少女前线》（Girls' Frontline）的个人自动化项目。

## 项目概述

GFAM 通过内置的 gflzirc 库与游戏服务器通信，自动化执行各类日常任务：关卡打捞、资源获取、制造、训练、妖精管理等。项目支持 Windows 本地运行和 GitHub Actions 云端运行两种模式。

当前版本：**v1.2**

## 核心特性

- **GUI 图形化启动器**：基于 Tkinter 的完整图形界面，PyInstaller 打包为单文件 exe
- **9 大功能模块**：EPA 打捞、13-4 练级/资源、A-10 资源、训练资料、零元购、零元购 PR、一键打捞、跟随制造、灰域彩蛋
- **跟随模块制造系统**：后台制造守护进程，可与打捞/资源模块并行运行
- **跨进程协调**：全局 API 锁 + 拆解锁 + Index 缓存，安全支持多进程并发
- **运行统计弹窗**：各模块结束后自动生成 JSON 摘要并在 GUI 中弹出统计窗口
- **GitHub Actions 支持**：通过 workflow_dispatch 在云端无人值守运行

## Wiki 页面

| 页面 | 内容 |
|------|------|
| [系统架构](Architecture) | 进程模型、分层架构、数据流、跨进程协调机制 |
| [功能模块](Modules) | 每个模块的功能、游戏机制、CONFIG 参数、API 交互 |
| [配置系统](Configuration) | 环境变量、设置文件、数据字典、运行时缓存 |
| [构建与部署](Build-Deploy) | GUI 打包、便携包、GitHub Actions 配置 |
| [开发指南](Development) | 目录结构、编码约定、模块接入方式 |

## 技术栈

| 组件 | 技术 |
|------|------|
| 主菜单 | Node.js（main.js 交互式 CLI） |
| 功能模块 | Python 3.11+（modules/*.py） |
| GUI | Python Tkinter（tools/gfam_gui_launcher.py） |
| 通信库 | gflzirc（RC4 变体加密 + HTTP） |
| 代理 | GFLProxy（MITM 流量拦截） |
| 打包 | PyInstaller（单文件 exe） |
| 云端 | GitHub Actions（ubuntu-latest runner） |

## 代码规模

| 类别 | 文件数 | 行数 |
|------|--------|------|
| 功能模块（modules/） | 18 | ~33,500 |
| GUI 工具（tools/） | 3 | ~4,150 |
| 通信库（gflzirc） | 5 | ~620 |
| GHA 入口 | 2 | ~1,250 |
| 启动脚本 | 6 | ~680 |
| **合计** | **34** | **~40,200** |

## 许可证

MIT License (2026 GFAM Contributors)

gflzirc 库来自 [MaaGF1/ZIRC](https://github.com/MaaGF1/ZIRC)，MIT License。
