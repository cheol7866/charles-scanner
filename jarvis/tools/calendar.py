"""Google Calendar 도구 - 일정 조회·생성.

OAuth 토큰을 ~/.jarvis/calendar_token.json 에 캐싱한다.
처음 실행 시 ~/.jarvis/credentials.json (OAuth 클라이언트) 가 필요하다.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from typing import Any
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from jarvis.config import JarvisConfig
from jarvis.llm import Tool

SCOPES = ["https://www.googleapis.com/auth/calendar"]
KST = ZoneInfo("Asia/Seoul")


class CalendarTool:
    def __init__(self, config: JarvisConfig):
        self.config = config
        self._service = None

    def _get_service(self):
        if self._service is not None:
            return self._service
        token_path = self.config.google_calendar_token_path
        creds_path = self.config.google_calendar_credentials_path
        creds = None
        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(creds_path):
                    raise RuntimeError(
                        f"Google Calendar 자격 증명 파일이 없습니다: {creds_path}\n"
                        "Google Cloud Console에서 OAuth 클라이언트(Desktop)를 만들고 JSON을 저장하세요."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(token_path, "w") as f:
                f.write(creds.to_json())
        self._service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        return self._service

    def list_events(self, args: dict[str, Any]) -> str:
        days = int(args.get("days_ahead", 1))
        now = dt.datetime.now(tz=KST)
        end = now + dt.timedelta(days=days)
        service = self._get_service()
        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=now.isoformat(),
                timeMax=end.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=20,
            )
            .execute()
        )
        events = events_result.get("items", [])
        if not events:
            return json.dumps({"events": [], "message": "예정된 일정이 없습니다."}, ensure_ascii=False)
        out = []
        for e in events:
            start = e["start"].get("dateTime", e["start"].get("date"))
            out.append({"summary": e.get("summary", "(제목 없음)"), "start": start, "location": e.get("location", "")})
        return json.dumps({"events": out}, ensure_ascii=False)

    def create_event(self, args: dict[str, Any]) -> str:
        summary = args["summary"]
        start_iso = args["start"]
        end_iso = args.get("end")
        if not end_iso:
            start_dt = dt.datetime.fromisoformat(start_iso)
            end_iso = (start_dt + dt.timedelta(hours=1)).isoformat()
        body = {
            "summary": summary,
            "start": {"dateTime": start_iso, "timeZone": "Asia/Seoul"},
            "end": {"dateTime": end_iso, "timeZone": "Asia/Seoul"},
        }
        if args.get("location"):
            body["location"] = args["location"]
        if args.get("description"):
            body["description"] = args["description"]
        service = self._get_service()
        created = service.events().insert(calendarId="primary", body=body).execute()
        return json.dumps(
            {"created": True, "id": created.get("id"), "link": created.get("htmlLink")},
            ensure_ascii=False,
        )

    def as_tools(self) -> list[Tool]:
        return [
            Tool(
                name="calendar_list",
                description="앞으로 N일 동안의 일정을 조회한다. 사용자가 '오늘 일정', '내일 약속', '이번주 미팅' 등을 물을 때 호출.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "days_ahead": {"type": "integer", "description": "오늘부터 몇 일 후까지 조회할지. 기본 1."},
                    },
                },
                handler=self.list_events,
            ),
            Tool(
                name="calendar_create",
                description="새 일정을 생성한다. 시간은 ISO 8601 형식(예: 2026-05-24T15:00:00+09:00).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string", "description": "일정 제목"},
                        "start": {"type": "string", "description": "시작 시각 ISO 8601 (KST)"},
                        "end": {"type": "string", "description": "종료 시각 ISO 8601. 생략하면 1시간."},
                        "location": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["summary", "start"],
                },
                handler=self.create_event,
            ),
        ]
