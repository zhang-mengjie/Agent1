import asyncio
import time
# from collections.abc import AsyncGenerator

semaphore = asyncio.Semaphore(2)

async def test(index: int) -> int:
    async with semaphore:
        print(f"开始生成第 {index} 个 embedding")
        await asyncio.sleep(index % 2)
        print(f"第 {index} 个 embedding 完成")
        return index * 2

async def main():
    start = time.perf_counter()
    tasks = [test(i) for i in range(10)]
    results = await asyncio.gather(*tasks)
    end = time.perf_counter()
    print(results)
    print(f"总耗时：{end - start:.2f} 秒")

asyncio.run(main())