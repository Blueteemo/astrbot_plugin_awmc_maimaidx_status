"""Standard-library tests; AstrBot API is stubbed, not an integration test."""
import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, mock_open, patch

for name in ('astrbot', 'astrbot.api', 'astrbot.api.event', 'astrbot.api.star'):
    sys.modules[name] = types.ModuleType(name)
sys.modules['astrbot.api.event'].filter = types.SimpleNamespace(command=lambda *a: lambda f:f)
sys.modules['astrbot.api.event'].AstrMessageEvent = object
class Star:
    def __init__(self, context): pass
sys.modules['astrbot.api.star'].Star = Star
sys.modules['astrbot.api.star'].Context = object
sys.modules['astrbot.api.star'].register = lambda *a: lambda f:f
sys.modules['astrbot.api'].AstrBotConfig = dict
sys.modules['astrbot.api'].logger = types.SimpleNamespace(error=lambda *a:None, info=lambda *a:None)
spec=importlib.util.spec_from_file_location('plugin', Path(__file__).parents[1]/'main.py')
plugin=importlib.util.module_from_spec(spec); spec.loader.exec_module(plugin)
class StatusTests(unittest.TestCase):
    def setUp(self): self.p=plugin.AwmcMaimaiStatusPlugin(None,{})
    def text(self, **data): return '\n'.join(self.p.format_status_blocks(data))
    def test_migrate_defaults(self):
        p=plugin.AwmcMaimaiStatusPlugin(None,{'base_url':'https://miku.milkawa.xyz/','screenshot_url':'https://status.awmc.cc/status/maimai-lite'})
        self.assertEqual(p.base_url,'https://mai.chongxi.us'); self.assertEqual(p.screenshot_url,p.base_url)
    def test_preserve_custom(self):
        p=plugin.AwmcMaimaiStatusPlugin(None,{'base_url':'https://example.org/','screenshot_url':'https://example.org/status'})
        self.assertEqual(p.base_url,'https://example.org'); self.assertEqual(p.screenshot_url,'https://example.org/status')
    def test_verdict_over_legacy(self):
        s=self.text(status='normal',verdict='recovering',services=[])
        self.assertIn('总体状态：🟨恢复中',s)
    def test_all_states(self):
        for state in ('normal','ok','recovering','degraded','outage','down','maintenance','nodata'):
            self.assertNotIn('未知',self.p.status_label(state))
    def test_unknown_is_not_normal(self): self.assertEqual(self.p.status_label('new'),'⬜未知')
    def test_no_services(self): self.assertIn('暂无服务数据',self.text(services=[]))
    def test_nullable_fields(self):
        s=self.text(services=[None,{'name':'NET','state':'nodata','latency':None}],broadcast=None,reports=None)
        self.assertNotIn('当前延迟',s)
    def test_zero_latency(self): self.assertIn('0 ms',self.text(services=[{'latency':0}]))
    def test_invalid_latency(self):
        for value in (-1,True,float('nan'),float('inf'),'5'):
            self.assertNotIn('当前延迟',self.text(services=[{'latency':value}]))
    def test_reports_not_outages(self):
        self.assertIn('不等同于服务宕机次数',self.text(reports={'anomaly_count':2,'normal_count':3}))
    def test_attribution_no_old_metrics(self):
        s=self.text(services=[])
        self.assertIn('数据来源于 isMaiDown by Chongxi',s)
        self.assertNotIn('可用率',s); self.assertNotIn('15分钟',s)
    def test_broadcast(self): self.assertIn('【公告】\n维护',self.text(broadcast={'msg':' 维护 '}))

class FetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_command_modes(self):
        class Event:
            def plain_result(self,text): return ('text',text)
            def image_result(self,path): return ('image',path)
            def chain_result(self,chain): return ('chain',chain)
            def get_self_id(self): return '12345'
        components=types.SimpleNamespace(
            Nodes=lambda **kw:kw, Node=lambda **kw:kw, Plain=lambda **kw:kw)
        with patch.dict(sys.modules,{'astrbot.api.message_components':components}):
            for default,mode,wanted in [('text','','text'),('text','forward','chain'),('image','text','text'),('forward','image','image')]:
                p=plugin.AwmcMaimaiStatusPlugin(None,{'output_mode':default})
                async def blocks(): return ['title','services','source']
                async def image(): return '/tmp/image.png'
                p.build_status_blocks=blocks; p.get_screenshot_url=image
                results=[r async for r in p.maidx_status(Event(),mode)]
                self.assertEqual(results[-1][0],wanted)
    async def test_image_failure_falls_back(self):
        class Event:
            def plain_result(self,text): return text
        p=plugin.AwmcMaimaiStatusPlugin(None,{})
        async def image(): return None
        async def blocks(): return ['text fallback']
        p.get_screenshot_url=image; p.build_status_blocks=blocks
        results=[r async for r in p.maidx_status(Event(),'image')]
        self.assertEqual(results[-1],'text fallback')
    async def test_http_and_schema(self):
        p=plugin.AwmcMaimaiStatusPlugin(None,{})
        for data, error in (({'services':[]},None), ({},ValueError),([],ValueError),({'services':None},ValueError)):
            p=plugin.AwmcMaimaiStatusPlugin(None,{})
            class Response:
                checked=False
                async def __aenter__(self): return self
                async def __aexit__(self,*a): pass
                def raise_for_status(self): self.checked=True
                async def json(self): return data
            response=Response()
            class Session:
                async def __aenter__(self): return self
                async def __aexit__(self,*a): pass
                def get(self,url,**kw):
                    assert url=='https://mai.chongxi.us/api/bot'
                    return response
            with patch.dict(sys.modules,{'aiohttp':types.SimpleNamespace(ClientSession=Session,ClientTimeout=lambda **kw:kw)}):
                if error:
                    with self.assertRaises(error): await p.fetch_status()
                else: self.assertEqual(await p.fetch_status(),data)
            self.assertTrue(response.checked)


class RobustnessTests(unittest.TestCase):
    def setUp(self): self.p = plugin.AwmcMaimaiStatusPlugin(None, {})
    def test_non_string_states(self):
        for state in (None, [], {}, 1, True):
            with self.subTest(state=state):
                self.assertEqual(self.p.status_label(state), "⬜未知")
                text = "\n".join(self.p.format_status_blocks({"verdict": state, "services": [{"state": state}]}))
                self.assertNotIn("🟩", text)
    def test_malformed_optional_fields(self):
        text = "\n".join(self.p.format_status_blocks({
            "verdict": "nodata", "timestamp": {}, "services": [None, [], {"name": {}, "key": [], "state": [], "duration_text": {}}],
            "reports": [], "broadcast": {"msg": []},
        }))
        self.assertIn("未知服务", text)
        self.assertNotIn("{}", text)
        self.assertNotIn("数据时间", text)
        self.assertNotIn("【公告】", text)
    def test_invalid_counts(self):
        for count in (-1, True, "3", 1.5, None):
            text = "\n".join(self.p.format_status_blocks({"reports": {"anomaly_count": count, "normal_count": 0}}))
            self.assertNotIn("玩家上报", text)
    def test_utc_timestamp(self):
        self.assertEqual(self.p.format_timestamp(0), "1970-01-01 00:00:00 UTC")

class CacheTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.p = plugin.AwmcMaimaiStatusPlugin(None, {})
        self.p._request_status = AsyncMock(return_value={"verdict": "normal", "services": [{"state": "ok"}]})
    async def test_hit_expiry_and_copy_isolation(self):
        with patch.object(plugin, "monotonic", return_value=100) as clock, patch.object(plugin.time, "time", return_value=1000):
            first = await self.p.fetch_status()
            first["services"][0]["state"] = "down"
            clock.return_value = 129.999
            second = await self.p.fetch_status()
            self.assertEqual(second["services"][0]["state"], "ok")
            self.assertEqual(self.p._request_status.await_count, 1)
            clock.return_value = 130
            await self.p.fetch_status()
            self.assertEqual(self.p._request_status.await_count, 2)
    async def test_concurrent_requests_coalesce(self):
        async def slow_request():
            await asyncio.sleep(0)
            return {"services": []}
        self.p._request_status.side_effect = slow_request
        await asyncio.gather(*(self.p.fetch_status() for _ in range(8)))
        self.assertEqual(self.p._request_status.await_count, 1)
    async def test_concurrent_failure_shared_then_retried(self):
        async def failing_request():
            await asyncio.sleep(0)
            raise TimeoutError("upstream")
        self.p._request_status.side_effect = failing_request
        results = await asyncio.gather(*(self.p.fetch_status() for _ in range(8)), return_exceptions=True)
        self.assertTrue(all(isinstance(r, TimeoutError) for r in results))
        self.assertEqual(self.p._request_status.await_count, 1)
        with self.assertRaises(TimeoutError): await self.p.fetch_status()
        self.assertEqual(self.p._request_status.await_count, 2)
    async def test_cancelled_waiter_does_not_cancel_shared_request(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def pending_request():
            started.set()
            await release.wait()
            return {"services": []}
        self.p._request_status.side_effect = pending_request
        first = asyncio.create_task(self.p.fetch_status())
        await started.wait()
        second = asyncio.create_task(self.p.fetch_status())
        await asyncio.sleep(0)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError): await first
        release.set()
        self.assertEqual(await second, {"services": []})
        self.assertEqual(self.p._request_status.await_count, 1)
    async def test_concurrent_image_failure_shared_then_retried(self):
        async def fail():
            await asyncio.sleep(0)
            return None
        self.p._capture_or_render_image = AsyncMock(side_effect=fail)
        self.assertEqual(await asyncio.gather(*(self.p.get_screenshot_url() for _ in range(4))), [None]*4)
        self.assertEqual(self.p._capture_or_render_image.await_count, 1)
        self.assertIsNone(await self.p.get_screenshot_url())
        self.assertEqual(self.p._capture_or_render_image.await_count, 2)
    async def test_failure_does_not_cache_or_return_expired_data(self):
        with patch.object(plugin, "monotonic", return_value=100) as clock:
            await self.p.fetch_status()
            clock.return_value = 131
            self.p._request_status.side_effect = TimeoutError("timeout")
            for _ in range(2):
                with self.assertRaises(TimeoutError): await self.p.fetch_status()
            self.assertEqual(self.p._status_cached_at, 100)
            self.assertEqual(self.p._request_status.await_count, 3)
    async def test_cache_time_visible_and_stable(self):
        with patch.object(plugin.time, "time", return_value=1000):
            first = await self.p.build_status_blocks()
        with patch.object(plugin.time, "time", return_value=1010):
            second = await self.p.build_status_blocks()
        self.assertEqual(first, second)
        self.assertIn("00:16:40 UTC（30秒内复用）", first[0])
    async def test_wall_clock_jump_does_not_expire_cache(self):
        with patch.object(plugin, "monotonic", return_value=100), patch.object(plugin.time, "time", side_effect=[1000, -100000]):
            await self.p.fetch_status()
            await self.p.fetch_status()
        self.assertEqual(self.p._request_status.await_count, 1)
    async def test_screenshot_cache_expiry_and_lock(self):
        async def capture():
            await asyncio.sleep(0)
            self.p._last_screenshot_url = "image.png"
            self.p._screenshot_cached_at = plugin.monotonic()
            self.p._last_screenshot_time = 1000
            return "image.png"
        self.p._capture_or_render_image = AsyncMock(side_effect=capture)
        with patch.object(plugin, "monotonic", return_value=100) as clock:
            await asyncio.gather(*(self.p.get_screenshot_url() for _ in range(4)))
            self.assertEqual(self.p._capture_or_render_image.await_count, 1)
            clock.return_value = 399
            await self.p.get_screenshot_url()
            self.assertEqual(self.p._capture_or_render_image.await_count, 1)
            clock.return_value = 400
            await self.p.get_screenshot_url()
            self.assertEqual(self.p._capture_or_render_image.await_count, 2)
    async def test_image_caption_contains_time_and_source(self):
        self.p._last_screenshot_time = 1000
        self.p.get_screenshot_url = AsyncMock(return_value="image.png")
        event = types.SimpleNamespace(plain_result=lambda t:("text",t),image_result=lambda p:("image",p))
        result = [r async for r in self.p.maidx_status(event, "image")]
        self.assertIn("00:16:40 UTC", result[-2][1])
        self.assertIn("最多缓存5分钟", result[-2][1])
        self.assertIn("isMaiDown by Chongxi", result[-2][1])
        self.assertEqual(result[-1], ("image", "image.png"))

class FailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_errors_and_bad_json(self):
        for where, error in (("status", RuntimeError("HTTP 429")), ("json", ValueError("not JSON")), ("enter", TimeoutError("timeout"))):
            p = plugin.AwmcMaimaiStatusPlugin(None, {})
            class Response:
                async def __aenter__(self):
                    if where == "enter": raise error
                    return self
                async def __aexit__(self, *args): pass
                def raise_for_status(self):
                    if where == "status": raise error
                async def json(self): raise error
            class Session:
                async def __aenter__(self): return self
                async def __aexit__(self, *args): pass
                def get(self, *args, **kwargs): return Response()
            with patch.dict(sys.modules, {"aiohttp": types.SimpleNamespace(ClientSession=Session, ClientTimeout=lambda **kw:kw)}):
                with self.assertRaises(type(error)): await p.fetch_status()
            self.assertIsNone(p._status_cache)
    async def test_query_failure_not_reported_as_game_outage(self):
        p = plugin.AwmcMaimaiStatusPlugin(None, {})
        p.build_status_blocks = AsyncMock(side_effect=TimeoutError())
        event = types.SimpleNamespace(plain_result=lambda t:t)
        result = [r async for r in p.maidx_status(event, "text")]
        self.assertIn("查询失败", result[-1])
        self.assertNotIn("宕机", result[-1])
    async def test_browser_closed_on_navigation_error_and_fallback(self):
        p = plugin.AwmcMaimaiStatusPlugin(None, {})
        page = types.SimpleNamespace(add_init_script=AsyncMock(),set_viewport_size=AsyncMock(),goto=AsyncMock(side_effect=TimeoutError("navigation")))
        browser = types.SimpleNamespace(new_context=AsyncMock(return_value=types.SimpleNamespace(new_page=AsyncMock(return_value=page))),close=AsyncMock())
        pw = types.SimpleNamespace(chromium=types.SimpleNamespace(launch=AsyncMock(return_value=browser)))
        class Manager:
            async def __aenter__(self): return pw
            async def __aexit__(self, *args): pass
        p.build_status_blocks = AsyncMock(return_value=["source and status"])
        p.text_to_image = AsyncMock(return_value="https://example.org/image.png")
        with patch.dict(sys.modules,{"playwright.async_api":types.SimpleNamespace(async_playwright=Manager)}):
            result = await p.get_screenshot_url()
        browser.close.assert_awaited_once()
        self.assertEqual(result, "https://example.org/image.png")
        self.assertGreater(p._last_screenshot_time, 0)
        self.assertEqual(await p.get_screenshot_url(), result)
        p.text_to_image.assert_awaited_once()

if __name__ == "__main__": unittest.main()
