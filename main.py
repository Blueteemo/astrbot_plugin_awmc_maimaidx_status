import asyncio
import copy
import time
from time import monotonic
from datetime import datetime, timezone
from typing import Optional

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import AstrBotConfig, logger


class AwmcMaimaiStatusPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.base_url = config.get("base_url", "https://mai.chongxi.us").rstrip("/")
        # Migrate only known old defaults; preserve explicitly configured proxies.
        if self.base_url in {"https://miku.milkawa.xyz", "https://status.awmc.cc"}:
            self.base_url = "https://mai.chongxi.us"
        self.output_mode = config.get("output_mode", "text")
        self.screenshot_url = config.get("screenshot_url", "https://mai.chongxi.us")
        if self.screenshot_url.rstrip("/") in {
            "https://status.awmc.cc/status/maimai-lite",
            "https://status.awmc.cc/status/maimai",
        }:
            self.screenshot_url = "https://mai.chongxi.us"

        # 截图缓存
        self._last_screenshot_url: Optional[str] = None
        self._last_screenshot_time: float = 0
        self._cache_minutes = 5  # 截图缓存5分钟
        self._screenshot_cached_at = 0.0
        self._screenshot_task: Optional[asyncio.Task] = None
        self._status_cache: Optional[dict] = None
        self._status_cached_at = 0.0
        self._status_fetched_at = 0.0
        self._status_cache_seconds = 30
        self._status_task: Optional[asyncio.Task] = None

    @staticmethod
    def status_label(state: object) -> str:
        if not isinstance(state, str):
            return "⬜未知"
        return {
            "normal": "🟩正常", "ok": "🟩正常",
            "recovering": "🟨恢复中", "degraded": "🟨性能下降",
            "outage": "🟥宕机", "down": "🟥宕机",
            "maintenance": "🟦维护中", "nodata": "⬜暂无数据",
        }.get(state, "⬜未知")

    @staticmethod
    def _consume_task_exception(task: asyncio.Task) -> None:
        # Retrieve errors even when all waiting commands have been cancelled.
        if not task.cancelled():
            task.exception()

    async def fetch_status(self) -> dict:
        if self._status_cache is not None and (
            monotonic() - self._status_cached_at < self._status_cache_seconds
        ):
            return copy.deepcopy(self._status_cache)
        # Concurrent callers share success or failure, without caching failures.
        if self._status_task is None or self._status_task.done():
            self._status_task = asyncio.create_task(self._refresh_status())
            self._status_task.add_done_callback(self._consume_task_exception)
        return copy.deepcopy(await asyncio.shield(self._status_task))

    async def _refresh_status(self) -> dict:
        data = await self._request_status()
        self._status_cache = copy.deepcopy(data)
        self._status_cached_at = monotonic()
        self._status_fetched_at = time.time()
        return data

    async def _request_status(self) -> dict:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.base_url}/api/bot", timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
        if not isinstance(data, dict) or not isinstance(data.get("services"), list):
            raise ValueError("isMaiDown 响应缺少 services 列表")
        return data

    @staticmethod
    def display_text(value: object, default: str = "") -> str:
        return value.strip() if isinstance(value, str) and value.strip() else default

    @staticmethod
    def format_timestamp(timestamp: float) -> str:
        return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    def format_status_blocks(self, data: dict) -> list:
        # verdict is authoritative; the legacy status can say normal while recovering.
        verdict = data.get("verdict", "nodata")
        blocks = [f"舞萌DX 服务器状态\n总体状态：{self.status_label(verdict)}"]
        timestamp = self.display_text(data.get("timestamp"))
        if timestamp:
            blocks[0] += f"\n数据时间：{timestamp}"
        services = data.get("services", [])
        service_lines = ["【服务状态】"]
        for service in services if isinstance(services, list) else []:
            if not isinstance(service, dict):
                continue
            name = self.display_text(service.get("name")) or self.display_text(service.get("key"), "未知服务")
            service_lines.append(
                f"{name}："
                f"{self.status_label(service.get('state'))}"
            )
            latency = service.get("latency")
            if isinstance(latency, (int, float)) and not isinstance(latency, bool) and 0 <= latency < float('inf'):
                service_lines.append(f"  当前延迟：{latency} ms")
            if isinstance(service.get("duration_text"), str) and service["duration_text"]:
                service_lines.append(f"  {service['duration_text']}")
        if len(service_lines) == 1:
            service_lines.append("暂无服务数据")
        blocks.append("\n".join(service_lines))
        reports = data.get("reports")
        if isinstance(reports, dict):
            counts = [reports.get("anomaly_count"), reports.get("normal_count")]
            if all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in counts):
                blocks.append(f"【近1小时玩家上报】\n异常 {counts[0]} 条，正常 {counts[1]} 条（不等同于服务宕机次数）")
        broadcast = data.get("broadcast")
        if isinstance(broadcast, dict) and isinstance(broadcast.get("msg"), str) and broadcast["msg"].strip():
            blocks.append("【公告】\n" + broadcast["msg"].strip())
        blocks.append("数据来源于 isMaiDown by Chongxi\nhttps://mai.chongxi.us")
        return blocks

    async def build_status_blocks(self) -> list:
        blocks = self.format_status_blocks(await self.fetch_status())
        blocks[0] += (
            f"\n数据获取：{self.format_timestamp(self._status_fetched_at)}"
            f"（{self._status_cache_seconds}秒内复用）"
        )
        return blocks

    async def get_screenshot_url(self) -> Optional[str]:
        """获取状态页截图URL，带缓存"""
        if self._last_screenshot_url and (
            monotonic() - self._screenshot_cached_at < self._cache_minutes * 60
        ):
            logger.info("使用缓存的截图")
            return self._last_screenshot_url
        if self._screenshot_task is None or self._screenshot_task.done():
            self._screenshot_task = asyncio.create_task(self._capture_or_render_image())
            self._screenshot_task.add_done_callback(self._consume_task_exception)
        return await asyncio.shield(self._screenshot_task)

    async def _capture_or_render_image(self) -> Optional[str]:
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
                try:
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
                    response = await page.goto(self.screenshot_url, wait_until="networkidle", timeout=30000)
                    if response is not None and response.status >= 400:
                        raise RuntimeError(f"状态页 HTTP {response.status}")

                    # 等待字体加载
                    await page.wait_for_timeout(3000)

                    # 截图
                    screenshot_bytes = await page.screenshot(full_page=True, type="png")

                finally:
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
            self._last_screenshot_time = time.time()
            self._screenshot_cached_at = monotonic()

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
                    self._last_screenshot_time = time.time()
                    self._screenshot_cached_at = monotonic()
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
                    yield event.plain_result(
                        f"图片生成：{self.format_timestamp(self._last_screenshot_time)}"
                        f"（最多缓存{self._cache_minutes}分钟）\n"
                        "数据来源于 isMaiDown by Chongxi · https://mai.chongxi.us"
                    )
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
            yield event.plain_result("舞萌DX 状态查询失败，请稍后重试或联系管理员检查 isMaiDown 服务。")


@register("astrbot_plugin_awmc_maimaidx_status", "Blueteemo", "舞萌DX 服务器状态查询", "1.1.0")
def register_plugin(context: Context, config: AstrBotConfig):
    return AwmcMaimaiStatusPlugin(context, config)
