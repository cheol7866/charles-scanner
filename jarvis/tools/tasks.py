"""할 일(Tasks) 도구 - 로컬 JSON 파일에 저장하는 간단한 To-Do.

캘린더 일정과 별도로 "물 마시기", "은행 송금" 같은 빠른 메모를 다룬다.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from pathlib import Path
from typing import Any

from jarvis.config import JarvisConfig
from jarvis.llm import Tool


class TasksTool:
    def __init__(self, config: JarvisConfig):
        self.path = Path(config.tasks_db_path)
        if not self.path.exists():
            self.path.write_text("[]", encoding="utf-8")

    def _load(self) -> list[dict[str, Any]]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, items: list[dict[str, Any]]) -> None:
        self.path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, args: dict[str, Any]) -> str:
        items = self._load()
        item = {
            "id": uuid.uuid4().hex[:8],
            "title": args["title"],
            "due": args.get("due"),
            "done": False,
            "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        }
        items.append(item)
        self._save(items)
        return json.dumps({"added": item}, ensure_ascii=False)

    def list_open(self, args: dict[str, Any]) -> str:
        items = [i for i in self._load() if not i["done"]]
        return json.dumps({"tasks": items}, ensure_ascii=False)

    def complete(self, args: dict[str, Any]) -> str:
        target = args["id"]
        items = self._load()
        for i in items:
            if i["id"] == target:
                i["done"] = True
                self._save(items)
                return json.dumps({"completed": target}, ensure_ascii=False)
        return json.dumps({"error": f"id={target} 항목 없음"}, ensure_ascii=False)

    def as_tools(self) -> list[Tool]:
        return [
            Tool(
                name="tasks_add",
                description="새 할 일을 추가한다. 사용자가 '~을 잊지 말라고 알려줘' 또는 '할 일 추가' 라고 말할 때 사용.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "할 일 제목"},
                        "due": {"type": "string", "description": "마감일 (선택)"},
                    },
                    "required": ["title"],
                },
                handler=self.add,
            ),
            Tool(
                name="tasks_list",
                description="아직 끝내지 않은 할 일을 모두 가져온다.",
                input_schema={"type": "object", "properties": {}},
                handler=self.list_open,
            ),
            Tool(
                name="tasks_complete",
                description="할 일을 완료 처리한다.",
                input_schema={
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                    "required": ["id"],
                },
                handler=self.complete,
            ),
        ]
