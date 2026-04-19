# astrbot_plugin_awmc_maimaidx_status

> 舞萌DX 服务器状态查询 — 基于 Uptime Kuma 心跳数据

![Project](https://img.shields.io/badge/🤖-AstrBot%20Plugin-5865F2) ![Version](https://img.shields.io/badge/version-1.0.0-4CAF50) ![License](https://img.shields.io/badge/license-MIT-FF6B6B)

查询 [舞萌DX](https://maimai.wahlap.com/) 各服务器的实时状态，数据来源于 AWMC 社区维护的 [Uptime Kuma](https://github.com/louislam/uptime-kuma) 监控。

## 功能

- 🟩🟨🟥 多维度状态指示：在线 / 不稳定 / 离线 / 维护中
- 📊 24 小时可用率统计
- ⏱ 近期波动分析与平均 Ping
- 📰 自动展示服务公告与维护信息
- 🖼 三种输出模式：纯文本 / 合并转发 / 状态页截图

## 命令

| 命令 | 说明 |
|------|------|
| `/mais` | 纯文本模式查询状态（默认） |
| `/mais forward` | 合并转发模式（仅 QQ） |
| `/mais image` | 截图模式（需安装 Playwright） |

## 配置项

在 AstrBot 管理后台的插件配置页面中调整：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `base_url` | Status / Uptime Kuma 反代根地址 | `https://miku.milkawa.xyz` |
| `continuous_down` | 连续多少个心跳为 0 时判定为「离线」 | `3` |
| `recent_minutes` | 近期统计时间窗口（分钟） | `15` |
| `output_mode` | 默认输出模式：`text` / `forward` / `image` | `text` |
| `screenshot_url` | 截图模式的页面地址 | `https://status.awmc.cc/status/maimai-lite` |

### 截图模式说明

`image` 模式使用 [Playwright](https://playwright.dev/) 对状态页进行浏览器截图。需要额外安装依赖：

```bash
pip install playwright
playwright install chromium
```

## 安装

1. 在 AstrBot 管理后台 → 插件管理 → 安装插件 → 上传 ZIP
2. 上传 `astrbot_plugin_awmc_maimaidx_status_v1.0.0.zip`
3. 重启 AstrBot

## 致谢

本插件移植自 [koishi-plugin-awmc-maimaidx-status](https://github.com/Michaelwucoc/koishi-plugin-awmc-maimaidx-status)，原作者 **[@Michaelwucoc](https://github.com/Michaelwucoc)**。

状态数据由 AWMC 社区通过 [Uptime Kuma](https://github.com/louislam/uptime-kuma) 监控提供，状态页地址：[status.awmc.cc](https://status.awmc.cc)。
