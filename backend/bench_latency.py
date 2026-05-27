import asyncio, os, time
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

client = AsyncOpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
)

FACT_PROMPT = """从对话中提取法律事实，只输出 JSON key-value。不要引用法条，不要给建议。
格式示例：{"facts": [{"key": "合同", "value": "未签订"}]}

对话：
<<<DIALOGUE>>>"""

FULL_PROMPT = """你是一位中国律师的AI助手。根据以下对话，提取事实、引用法条、评估风险。

对话：
<<<DIALOGUE>>>"""

DIALOGUE = """律师: 请问您遇到什么法律问题了？
客户: 我去年11月入职的，公司没跟我签劳动合同。
律师: 现在还在职吗？
客户: 在的，已经干了半年了，每个月工资照发。
律师: 还有其他情况吗？
客户: 每天都要加班到晚上9点，从来不给加班费。"""


async def test(name, prompt, max_tok):
    t0 = time.perf_counter()
    resp = await client.chat.completions.create(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        messages=[{"role": "user", "content": prompt.replace("<<<DIALOGUE>>>", DIALOGUE)}],
        temperature=0.1,
        max_tokens=max_tok,
        extra_body={"thinking": {"type": "disabled"}},
    )
    elapsed = (time.perf_counter() - t0) * 1000
    tok = resp.usage
    print(f"  {name}: {elapsed:.0f}ms (p={tok.prompt_tokens} c={tok.completion_tokens})")
    content = resp.choices[0].message.content
    if content:
        print(f"    -> {content[:200].replace(chr(10), ' ')}")
    return elapsed


async def main():
    print("=== fact_extract (轻量, max_tokens=500) ===")
    f_times = [await test("fact", FACT_PROMPT, 500) for _ in range(3)]

    print("\n=== full analyze (当前, max_tokens=2000) ===")
    a_times = [await test("full", FULL_PROMPT, 2000) for _ in range(3)]

    print(f"\n=== 汇总 ===")
    print(f"fact_extract 平均: {sum(f_times)/len(f_times):.0f}ms  (各次: {[f'{t:.0f}' for t in f_times]})")
    print(f"full analyze 平均: {sum(a_times)/len(a_times):.0f}ms  (各次: {[f'{t:.0f}' for t in a_times]})")


if __name__ == "__main__":
    asyncio.run(main())
