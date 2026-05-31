"""E2E Playwright 测试脚本：验证深度分析 confirm 后前端立即进入 running 状态。"""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import httpx
from playwright.async_api import async_playwright
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

sys_path_inserted = False
import sys
from pathlib import Path

if not sys_path_inserted:
    sys.path.insert(0, str(Path(__file__).parent / "src"))
    sys_path_inserted = True

from repositories.suggestions import SuggestionRepository

API_BASE = "http://localhost:8000"
FRONTEND_URL = "http://localhost:5173"
DATABASE_URL = "postgresql+psycopg://legal:legal@localhost:5432/legal_agent"


async def create_session() -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{API_BASE}/api/sessions")
        resp.raise_for_status()
        return resp.json()["session_id"]


async def seed_pending_suggestion(session_id: str, request_id: str) -> None:
    engine = create_async_engine(DATABASE_URL)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        repo = SuggestionRepository(s)
        await repo.upsert_pending(
            uuid.UUID(session_id),
            utt_id="test-utt-001",
            request_id=request_id,
            preview_topic="测试分析主题",
            preview_rationale="检测到可分析意图，建议生成深度分析",
        )
    await engine.dispose()


async def run_test() -> None:
    print("1. 创建会话...")
    session_id = await create_session()
    print(f"   会话 ID: {session_id}")

    request_id = "req_test_001"
    print("2. 插入 pending suggestion...")
    await seed_pending_suggestion(session_id, request_id)

    print("3. 启动 Playwright...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 800})

        print(f"4. 打开前端页面 /session/{session_id}...")
        await page.goto(f"{FRONTEND_URL}/session/{session_id}")
        await page.wait_for_load_state("networkidle")

        # 等待 WebSocket 连接和 history 加载
        print("5. 等待页面加载 suggestion 卡片...")
        await page.wait_for_selector("text=生成深度分析", timeout=15000)

        print("6. 截图（点击前）...")
        await page.screenshot(path="/Users/wwj/Desktop/myself/legal-agent/test_before_click.png")

        print("7. 点击'生成深度分析'按钮...")
        confirm_btn = page.locator("button:has-text('生成深度分析')")
        await confirm_btn.click()

        # 等待 running 状态出现（应该立即出现，因为是本地乐观更新）
        print("8. 验证 running 状态是否立即出现...")
        try:
            await page.wait_for_selector("text=分析中", timeout=2000)
            print("   ✅ 立即出现 '分析中…' 状态")
        except Exception:
            print("   ❌ 没有在 2 秒内看到 '分析中…' 状态")

        print("9. 截图（点击后）...")
        await page.screenshot(path="/Users/wwj/Desktop/myself/legal-agent/test_after_click.png")

        # 检查 suggestion 卡片是否还存在（没有被意外移除）
        card_count = await page.locator("text=测试分析主题").count()
        if card_count > 0:
            print("   ✅ 卡片仍然存在，没有被意外移除")
        else:
            print("   ❌ 卡片消失了")

        await browser.close()

    print("测试完成。截图保存于:")
    print("  - test_before_click.png")
    print("  - test_after_click.png")


if __name__ == "__main__":
    asyncio.run(run_test())
