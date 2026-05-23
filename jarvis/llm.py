"""Claude API 래퍼 - 도구 호출(tool use) 지원.

대화 히스토리를 유지하며, Claude가 도구 호출을 요청하면 등록된 핸들러를
실행하고 결과를 다시 모델에 넘긴다. 한 턴이 끝나면 최종 텍스트 응답을 반환.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from anthropic import Anthropic

from jarvis.config import JarvisConfig


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], str]

    def to_anthropic(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


@dataclass
class ConversationState:
    messages: list[dict[str, Any]] = field(default_factory=list)

    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_assistant(self, content: list[dict[str, Any]]) -> None:
        self.messages.append({"role": "assistant", "content": content})

    def add_tool_results(self, results: list[dict[str, Any]]) -> None:
        self.messages.append({"role": "user", "content": results})


class ClaudeAgent:
    def __init__(self, config: JarvisConfig, tools: list[Tool]):
        if not config.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY 환경 변수가 설정되어 있지 않습니다.")
        self.client = Anthropic(api_key=config.anthropic_api_key)
        self.config = config
        self.tools = {tool.name: tool for tool in tools}
        self.state = ConversationState()

    def reset(self) -> None:
        self.state = ConversationState()

    def chat(self, user_text: str, on_tool_call: Callable[[str, dict], None] | None = None) -> str:
        """한 턴의 대화를 처리한다. 도구 호출이 있으면 루프 안에서 실행."""

        self.state.add_user(user_text)
        max_iterations = 6

        for _ in range(max_iterations):
            response = self.client.messages.create(
                model=self.config.claude_model,
                max_tokens=1024,
                system=self.config.system_prompt,
                tools=[t.to_anthropic() for t in self.tools.values()] or None,
                messages=self.state.messages,
            )
            assistant_content = [block.model_dump() for block in response.content]
            self.state.add_assistant(assistant_content)

            if response.stop_reason != "tool_use":
                return _extract_text(assistant_content)

            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                if on_tool_call is not None:
                    try:
                        on_tool_call(block.name, dict(block.input))
                    except Exception:
                        pass
                result_text = self._run_tool(block.name, dict(block.input))
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                    }
                )
            self.state.add_tool_results(tool_results)

        return "도구 호출이 너무 많이 반복돼서 멈췄어요. 다시 말씀해 주세요."

    def _run_tool(self, name: str, args: dict[str, Any]) -> str:
        tool = self.tools.get(name)
        if tool is None:
            return json.dumps({"error": f"알 수 없는 도구: {name}"}, ensure_ascii=False)
        try:
            return tool.handler(args)
        except Exception as exc:
            return json.dumps({"error": str(exc)}, ensure_ascii=False)


def _extract_text(content_blocks: list[dict[str, Any]]) -> str:
    parts = []
    for block in content_blocks:
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(p for p in parts if p).strip()
