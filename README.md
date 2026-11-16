# astrbot_plugin_awmc_maimaidx_status

> 舞萌DX 服务器状态查询 — 基于 isMaiDown 公开 API

![AstrBot](https://img.shields.io/badge/%F0%9F%A4%96-AstrBot%20Plugin-7289DA) ![Version](https://img.shields.io/badge/version-1.1.0-3B82F6) ![Python](https://img.shields.io/badge/python-3.12+-blue.svg) ![License](https://img.shields.io/badge/license-MIT-FF6B6B)

查询 [舞萌DX](https://maimai.wahlap.com/) 各服务器的实时状态，数据来源于 [isMaiDown](https://mai.chongxi.us) by Chongxi。

## 功能

- 服务状态：正常 / 性能下降 / 恢复中 / 宕机 / 维护中 / 无数据
- 各服务当前延迟与持续/恢复时间
- 近 1 小时玩家上报数量（不等同于服务宕机次数）
- 服务公告
- 三种输出模式：纯文本 / 合并转发 / 状态页截图

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
| `base_url` | isMaiDown API 根地址 | `https://mai.chongxi.us` |
| `output_mode` | 默认输出模式：`text` / `forward` / `image` | `text` |
| `screenshot_url` | 截图模式的页面地址 | `https://mai.chongxi.us` |

### 截图模式说明

文本及合并转发共用 30 秒短缓存，并显示数据获取时间；上游返回数据时间时会另行显示。失败请求不作为成功缓存，也不回退为过期状态。

`image` 模式使用 [Playwright](https://playwright.dev/) 对状态页进行浏览器截图。图片最多缓存 5 分钟，发送时注明图片生成时间和来源。网页截图以不可变内存快照缓存，不重复写入共享截图文件；自定义页面标注实际截图地址，文字转图回退仍标注 API 数据来源。并发查询会复用同一请求/图片，避免重复访问。需要额外安装依赖：

```bash
pip install playwright
playwright install chromium
```

## 安装

1. 在 AstrBot 管理后台 → 插件管理 → 安装插件 → 上传 ZIP
2. 下载[最新版本 zip](https://github.com/Blueteemo/astrbot_plugin_awmc_maimaidx_status/releases)并上传
3. 重启 AstrBot

## 致谢

本插件移植自 [koishi-plugin-awmc-maimaidx-status](https://github.com/Michaelwucoc/koishi-plugin-awmc-maimaidx-status)，原作者 **[@Michaelwucoc](https://github.com/Michaelwucoc)**。

历史版本使用 AWMC 社区的 Uptime Kuma 数据，感谢其提供的服务。当前数据来源于 [isMaiDown](https://mai.chongxi.us) by Chongxi。

## 从 1.0.x 升级

保留插件标识、仓库名称及 `/mais` 命令，不需要另装插件。已保存的旧默认 API 地址（`miku.milkawa.xyz`、`status.awmc.cc`）及 AWMC 默认截图地址会在运行时切换至 isMaiDown；不改写配置文件。空值、空白及非字符串地址使用默认地址。自定义代理地址会保留，但需要改为支持 `/api/bot` 的新接口，旧 Uptime Kuma 协议不再支持。

新接口不提供旧版的心跳序列和 24 小时可用率，因此不再显示对应统计，`continuous_down`、`recent_minutes` 旧配置不再生效。总状态以 `verdict` 为准；未知状态不会按正常处理。接口说明见 [isMaiDown API 文档](https://mai.chongxi.us/docs/api-reference/status)。

## 本地检查

```bash
python -m unittest discover -s tests -v
python -m compileall -q main.py
```

单元测试使用 AstrBot 接口桩，不代替真实 AstrBot/QQ 环境的文本、合并转发和截图验收。
