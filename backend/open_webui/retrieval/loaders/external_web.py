import requests
import logging
from typing import Iterator, List, Union
import time
import asyncio
import aiohttp

from langchain_core.document_loaders import BaseLoader
from langchain_core.documents import Document
from open_webui.env import SRC_LOG_LEVELS

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["RAG"])


class ExternalWebLoader(BaseLoader):
    def __init__(
        self,
        web_paths: Union[str, List[str]],
        external_url: str,
        external_api_key: str,
        continue_on_failure: bool = True,
        timeout: int = 8,
        retries: int = 2,
        cooldown: int = 1,
        backoff: float = 1.5,
        **kwargs,
    ) -> None:
        self.external_url = external_url
        self.external_api_key = external_api_key
        self.urls = web_paths if isinstance(web_paths, list) else [web_paths]
        self.continue_on_failure = continue_on_failure
        self.timeout = timeout
        self.retries = retries
        self.cooldown = cooldown
        self.backoff = backoff

    def lazy_load(self) -> Iterator[Document]:
        batch_size = 20
        for i in range(0, len(self.urls), batch_size):
            urls = self.urls[i : i + batch_size]
            for j in range(self.retries):
                try:
                    response = requests.post(
                        self.external_url,
                        headers={
                            "Authorization": f"Bearer {self.external_api_key}",
                        },
                        json={
                            "urls": urls,
                        },
                        timeout=self.timeout,
                    )
                    response.raise_for_status()
                    results = response.json()
                    for result in results:
                        yield Document(
                            page_content=result.get("page_content", ""),
                            metadata=result.get("metadata", {}),
                        )
                    break  # Success
                except Exception as e:
                    log.warning(
                        f"Error loading from external web loader on attempt {j + 1}/{self.retries}: {e}"
                    )
                    if j < self.retries - 1:
                        time.sleep(self.cooldown * (self.backoff**j))
                    elif self.continue_on_failure:
                        log.error(
                            f"Error extracting content from batch {urls}: {e}"
                        )
                    else:
                        raise e

    async def alazy_load(self) -> Iterator[Document]:
        batch_size = 20
        for i in range(0, len(self.urls), batch_size):
            urls = self.urls[i : i + batch_size]
            for j in range(self.retries):
                try:
                    async with aiohttp.ClientSession(
                        timeout=aiohttp.ClientTimeout(total=self.timeout)
                    ) as session:
                        async with session.post(
                            self.external_url,
                            headers={
                                "Authorization": f"Bearer {self.external_api_key}",
                            },
                            json={
                                "urls": urls,
                            },
                        ) as response:
                            response.raise_for_status()
                            results = await response.json()
                            for result in results:
                                yield Document(
                                    page_content=result.get("page_content", ""),
                                    metadata=result.get("metadata", {}),
                                )
                            break  # Success
                except (aiohttp.ClientConnectionError, asyncio.TimeoutError) as e:
                    log.warning(
                        f"Error loading from external web loader on attempt {j + 1}/{self.retries}: {e}"
                    )
                    if j < self.retries - 1:
                        await asyncio.sleep(self.cooldown * (self.backoff**j))
                    elif self.continue_on_failure:
                        log.error(
                            f"Error extracting content from batch {urls}: {e}"
                        )
                    else:
                        raise e