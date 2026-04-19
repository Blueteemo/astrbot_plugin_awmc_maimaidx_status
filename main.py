import time
from typing import Any, Optional
from datetime import datetime
from dataclasses import dataclass

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import AstrBotConfig, logger


@dataclass
class HeartbeatEntry:
    time: int
    status: int
    msg: Optional[str] = None
    ping: Optional[int] = None


class AwmcMaimaiStatusPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.base_url = config.get("base_url", "https://miku.milkawa.xyz").rstrip("/")
        self.continuous_down = config.get("continuous_down", 3)
        self.recent_minutes = config.get("recent_minutes", 15)
        self.output_mode = config.get("output_mode", "text")
        self.screenshot_url = config.get("screenshot_url", "https://status.awmc.cc/status/maimai-lite")
        
        # 截图缓存
        self._last_screenshot_url: Optional[str] = None
        self._last_screenshot_time: float = 0
        self._cache_minutes = 5  # 截图缓存5分钟

    def parse_heartbeat_time(self, t: Any) -> int:
        if isinstance(t, (int, float)):
            return int(t)
        s = str(t).strip().replace(" ", "T")
        if not s.endswith("Z"):
            s += "Z"
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return int(dt.timestamp() * 1000)
        except:
            return 0

    def normalize_heartbeat_list(self, raw_list: Optional[list]) -> list:
        if not raw_list or not isinstance(raw_list, list):
            return []
        result = []
        for e in raw_list:
            entry = HeartbeatEntry(
                time=self.parse_heartbeat_time(e.get("time", 0)),
                status=e.get("status", 0),
                msg=e.get("msg"),
                ping=e.get("ping")
            )
            result.append(entry)
        return result

    def strip_html(self, html: str) -> str:
        import re
        text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        text = text.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">")
        text = text.replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
        return text.strip()

    def get_recent_heartbeats(self, entries: list, recent_ms: int) -> list:
        cutoff = int(time.time() * 1000) - recent_ms
        return [e for e in entries if e.time >= cutoff]

    def format_status(self, monitor: dict, entries: Optional[list], uptime_24_ratio: Optional[float]) -> list:
        lines = []
        entries = entries or []
        last = entries[-1] if entries else None
        recent_ms = self.recent_minutes * 60 * 1000
        recent = self.get_recent_heartbeats(entries, recent_ms)
        uptime_24h = uptime_24_ratio * 100 if uptime_24_ratio is not None else None

        status_emoji = "⬜"
        status_text = "未知"

        if not entries or not last:
            status_emoji = "⬜"
            status_text = "未知"
        else:
            n = self.continuous_down
            last_n = entries[-n:]
            is_offline = len(last_n) >= n and all(e.status == 0 for e in last_n)

            if is_offline:
                status_emoji = "🟥"
                status_text = "离线"
            elif last.status == 0:
                status_emoji = "🟨"
                status_text = "不稳定"
            elif last.status == 2:
                status_emoji = "🟨"
                status_text = "不稳定"
            elif last.status == 3:
                status_emoji = "🟦"
                status_text = "维护中"
            else:
                status_emoji = "🟩"
                status_text = "在线"

        lines.append(f"  {monitor.get('name', 'Unknown')}")
        lines.append(f"    状态：{status_emoji}{status_text}")

        if uptime_24h is not None:
            lines.append(f"    24小时可用率：{round(uptime_24h)}%")
        else:
            lines.append("    24小时可用率：暂无数据")

        if recent:
            recent_total = len(recent)
            recent_down = sum(1 for e in recent if e.status == 0)
            recent_down_ratio = recent_down / recent_total

            if recent_down_ratio == 0:
                recent_summary = f"近{self.recent_minutes}分钟全部正常"
            elif recent_down_ratio < 0.3:
                recent_summary = f"近{self.recent_minutes}分钟偶发波动"
            elif recent_down_ratio < 0.8:
                recent_summary = f"近{self.recent_minutes}分钟较多异常"
            else:
                recent_summary = f"近{self.recent_minutes}分钟持续异常"

            lines.append(f"    {recent_summary}")
            recent_pings = [e.ping for e in recent if e.status != 0 and e.ping and e.ping > 0]
            if recent_pings:
                avg_ping = round(sum(recent_pings) / len(recent_pings))
                lines.append(f"    近{self.recent_minutes}分钟平均 Ping：{avg_ping} ms")
        else:
            lines.append(f"    近{self.recent_minutes}分钟：暂无心跳数据")

        if last and last.status != 0 and last.ping and last.ping > 0:
            lines.append(f"    当前 Ping：{last.ping} ms")

        return lines

    async def fetch_status(self) -> tuple:
        import aiohttp
        status_page_url = f"{self.base_url}/api/status-page/maimai"
        heartbeat_url = f"{self.base_url}/api/status-page/heartbeat/maimai"

        async with aiohttp.ClientSession() as session:
            async with session.get(status_page_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                page_json = await resp.json()
            async with session.get(heartbeat_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                heartbeat_json = await resp.json()

        return page_json, heartbeat_json

    async def build_status_blocks(self) -> list:
        """获取并格式化所有状态数据，返回分组列表"""
        page_json, heartbeat_json = await self.fetch_status()

        groups = page_json.get("publicGroupList", [])
        heartbeat_map = heartbeat_json.get("heartbeatList", {})
        title = page_json.get("config", {}).get("title", "maimaiDX Server Status Regen")

        group_blocks = [title]

        incidents = page_json.get("incidents", [])
        active_incidents = [i for i in incidents if i.get("active") is not False]
        if active_incidents:
            incident_lines = ["【公告】"]
            for inc in active_incidents:
                incident_lines.append(inc.get("title", ""))
                if inc.get("content"):
                    incident_lines.append(self.strip_html(inc["content"]))
            group_blocks.append("\n".join(incident_lines))

        maintenance_list = page_json.get("maintenanceList", [])
        active_maintenance = [m for m in maintenance_list if m.get("status") == "under-maintenance" or m.get("active") is True]
        if active_maintenance:
            maint_lines = ["【维护】"]
            for m in active_maintenance:
                maint_lines.append(m.get("title", ""))
                if m.get("description"):
                    maint_lines.append(self.strip_html(m["description"]))
                dr = m.get("dateRange", [])
                if len(dr) == 2:
                    maint_lines.append(f"时间：{dr[0]} ～ {dr[1]}")
            group_blocks.append("\n".join(maint_lines))

        uptime_list = heartbeat_json.get("uptimeList", {})
        for group in sorted(groups, key=lambda x: x.get("weight", 0)):
            block_lines = [group.get("name", "Unknown")]
            for monitor in group.get("monitorList", []):
                key = str(monitor.get("id"))
                raw_list = heartbeat_map.get(key, [])
                list_entries = self.normalize_heartbeat_list(raw_list)
                ratio24 = uptime_list.get(f"{monitor.get('id')}_24")
                ratio = ratio24 if isinstance(ratio24, (int, float)) and ratio24 == ratio24 else None
                block_lines.extend(self.format_status(monitor, list_entries, ratio))
            group_blocks.append("\n".join(block_lines))

        return group_blocks

    async def get_screenshot_url(self) -> Optional[str]:
        """获取状态页截图URL，带缓存"""
        # 检查缓存
        now = time.time()
        if self._last_screenshot_url and (now - self._last_screenshot_time) < self._cache_minutes * 60:
            logger.info("使用缓存的截图")
            return self._last_screenshot_url

        try:
            # 使用 playwright 直接截图外部网页
            from playwright.async_api import async_playwright
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        '--font-render-hinting=none',
                        '--disable-font-subpixel-positioning',
                    ]
                )
                context = await browser.new_context(
                    locale='zh-CN',
                )
                page = await context.new_page()
                
                # 注入中文字体 CSS（使用 Google Fonts Noto Sans SC）
                await page.add_init_script('''
                    // 等待 DOM 加载后注入字体
                    document.addEventListener('DOMContentLoaded', function() {
                        const link = document.createElement('link');
                        link.href = 'https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700&display=swap';
                        link.rel = 'stylesheet';
                        document.head.appendChild(link);
                        
                        // 设置全局字体
                        const style = document.createElement('style');
                        style.textContent = `
                            * {
                                font-family: 'Noto Sans SC', 'Microsoft YaHei', 'SimHei', 'PingFang SC', sans-serif !important;
                            }
                        `;
                        document.head.appendChild(style);
                    });
                ''')
                
                # 设置视口大小
                await page.set_viewport_size({"width": 1280, "height": 800})
                
                # 访问页面
                await page.goto(self.screenshot_url, wait_until="networkidle", timeout=30000)
                
                # 等待字体加载
                await page.wait_for_timeout(3000)
                
                # 截图
                screenshot_bytes = await page.screenshot(full_page=True, type="png")
                
                await browser.close()
            
            # 保存到插件数据目录
            import os
            data_dir = os.path.join("data", "plugin_data", "astrbot_plugin_awmc_maimaidx_status")
            os.makedirs(data_dir, exist_ok=True)
            screenshot_path = os.path.join(data_dir, "screenshot.png")
            
            with open(screenshot_path, "wb") as f:
                f.write(screenshot_bytes)
            
            # 更新缓存
            self._last_screenshot_url = screenshot_path
            self._last_screenshot_time = now
            
            return screenshot_path
            
        except Exception as e:
            logger.error(f"Playwright 截图失败: {e}")
            
            # 回退：使用 text_to_image
            try:
                group_blocks = await self.build_status_blocks()
                full_text = "\n\n".join(group_blocks)
                url = await self.text_to_image(full_text)
                if url:
                    self._last_screenshot_url = url
                    self._last_screenshot_time = now
                    return url
            except Exception as e2:
                logger.error(f"text_to_image 也失败: {e2}")
            return None

    @filter.command("mais")
    async def maidx_status(self, event: AstrMessageEvent, mode: str = ""):
        '''查询舞萌DX服务器状态
用法:
  /mais        - 文本模式查询状态
  /mais forward - 合并转发模式（仅QQ支持）
  /mais image  - 截图模式
'''
        # 处理模式参数
        use_forward = (mode == "forward") or (self.output_mode == "forward" and mode != "text" and mode != "image")
        use_image = (mode == "image") or (self.output_mode == "image" and mode != "text" and mode != "forward")

        try:
            # 图片模式
            if use_image:
                yield event.plain_result("正在获取截图，请稍候...")
                screenshot_url = await self.get_screenshot_url()
                if screenshot_url:
                    yield event.image_result(screenshot_url)
                else:
                    yield event.plain_result("截图失败，已切换到文本模式...")
                    # 失败时回退到文本
                    group_blocks = await self.build_status_blocks()
                    yield event.plain_result("\n\n".join(group_blocks))
                return

            # 获取文本数据
            group_blocks = await self.build_status_blocks()

            if use_forward and len(group_blocks) > 1:
                # 合并转发模式（仅 OneBot v11 支持）
                # 使用 Nodes 组件包装多个 Node
                from astrbot.api.message_components import Nodes, Node, Plain
                
                # 获取机器人信息
                self_id = event.get_self_id() or "10000"
                self_name = "舞萌DX状态"
                
                # 创建所有 Node
                forward_nodes = []
                for block in group_blocks:
                    node = Node(
                        uin=int(self_id) if self_id.isdigit() else 10000,
                        name=self_name,
                        content=[Plain(text=block)]
                    )
                    forward_nodes.append(node)
                
                # 用 Nodes 包装（注意是复数 Nodes，不是 Forward）
                nodes_msg = Nodes(nodes=forward_nodes)
                yield event.chain_result([nodes_msg])
            else:
                # 纯文本模式
                full_text = "\n\n".join(group_blocks)
                yield event.plain_result(full_text)

        except Exception as e:
            logger.error(f"舞萌DX 状态查询失败: {e}")
            yield event.plain_result("舞萌DX 状态查询失败，请稍后重试或联系管理员检查 Status 服务。")


@register("astrbot_plugin_awmc_maimaidx_status", "Blueteemo", "舞萌DX 服务器状态查询", "1.6.0")
def register_plugin(context: Context, config: AstrBotConfig):
    return AwmcMaimaiStatusPlugin(context, config)
