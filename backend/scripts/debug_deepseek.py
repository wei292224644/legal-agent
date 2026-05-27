"""Debug: test Deepseek API directly to isolate the role issue."""
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from openai import AsyncOpenAI

client = AsyncOpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_BASE_URL"),
)


async def main():
    # Test 1: system role
    print("Test 1: system role...")
    r = await client.chat.completions.create(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        messages=[
            {"role": "system", "content": "You are helpful. Reply in JSON."},
            {"role": "user", "content": 'Say hello as JSON: {"greeting": "hi"}'},
        ],
    )
    print(f"  OK: {r.choices[0].message.content}")

    # Test 2: developer role (should fail on deepseek)
    print("Test 2: developer role...")
    try:
        r = await client.chat.completions.create(
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            messages=[
                {"role": "developer", "content": "You are helpful."},
                {"role": "user", "content": "Say hi"},
            ],
        )
        print(f"  OK: {r.choices[0].message.content}")
    except Exception as e:
        print(f"  FAIL (expected): {e}")

    # Test 3: json_object response_format
    print("Test 3: json_object response_format...")
    r = await client.chat.completions.create(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        messages=[
            {"role": "system", "content": "You are helpful. Output JSON."},
            {"role": "user", "content": 'Say hello as JSON: {"greeting": "hi"}'},
        ],
        response_format={"type": "json_object"},
    )
    print(f"  OK: {r.choices[0].message.content}")


asyncio.run(main())
