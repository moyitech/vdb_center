import os
from openai import AsyncOpenAI
from src.conf.env import settings
from tenacity import retry, stop_after_attempt, wait_exponential

"""
阿里文档：https://bailian.console.aliyun.com/cn-beijing/?tab=doc#/doc/?type=model&url=2842587
"""

client = AsyncOpenAI(
    # 若没有配置环境变量，请用阿里云百炼API Key将下行替换为：api_key="sk-xxx",
    # 新加坡和北京地域的API Key不同。获取API Key：https://help.aliyun.com/zh/model-studio/get-api-key
    api_key=settings.DASHSCOPE_API_KEY,  
    # 以下是北京地域base-url，如果使用新加坡地域的模型，需要将base_url替换为：https://dashscope-intl.aliyuncs.com/compatible-mode/v1
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)


@retry(stop=stop_after_attempt(20), wait=wait_exponential(multiplier=1, min=1, max=10))
async def get_text_embedding(input_text: list[str]) -> list[list[float]]:
    completion = await client.embeddings.create(
        model="text-embedding-v4",
        input=input_text,
        dimensions=1024
    )
    return [item.embedding for item in completion.data]


# @retry(stop=stop_after_attempt(20), wait=wait_exponential(multiplier=1, min=1, max=10))
# async def get_text_embedding(input_text: list[str]) -> list[list[float]]:
#     """
#     mock
#     """
#     # completion = await client.embeddings.create(
#     #     model="text-embedding-v4",
#     #     input=input_text,
#     #     dimensions=1024
#     # )
#     return [[0.1] * 1024 for _ in input_text]



if __name__ == "__main__":
    async def main():
        embedding = await get_text_embedding(["hello", "world"])
        print(embedding[0][:10])
    import asyncio
    asyncio.run(main())
