"""웹 검색 도구 - 사용자가 정보를 물을 때 가벼운 검색을 수행.

API 키가 없으면 안내 메시지만 반환한다.
"""

from __future__ import annotations

import json
import os
from typing import Any

import requests

from jarvis.llm import Tool


def _search(args: dict[str, Any]) -> str:
    query = args["query"]
    api_key = os.environ.get("SERPAPI_KEY") or os.environ.get("BRAVE_API_KEY")
    if not api_key:
        return json.dumps(
            {
                "results": [],
                "note": "SERPAPI_KEY 또는 BRAVE_API_KEY 가 설정되지 않아 검색을 건너뜁니다.",
            },
            ensure_ascii=False,
        )

    if os.environ.get("BRAVE_API_KEY"):
        r = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
            params={"q": query, "count": 5},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        results = []
        for item in (data.get("web", {}) or {}).get("results", [])[:5]:
            results.append({"title": item.get("title"), "url": item.get("url"), "snippet": item.get("description")})
        return json.dumps({"results": results}, ensure_ascii=False)

    r = requests.get(
        "https://serpapi.com/search.json",
        params={"q": query, "api_key": api_key, "num": 5, "hl": "ko"},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    results = []
    for item in data.get("organic_results", [])[:5]:
        results.append({"title": item.get("title"), "url": item.get("link"), "snippet": item.get("snippet")})
    return json.dumps({"results": results}, ensure_ascii=False)


class WebTool:
    def as_tools(self) -> list[Tool]:
        return [
            Tool(
                name="web_search",
                description="실시간 정보가 필요할 때 웹을 검색한다. 날씨·뉴스·일반 사실 확인용.",
                input_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                handler=_search,
            )
        ]
