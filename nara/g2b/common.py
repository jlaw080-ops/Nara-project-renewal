"""나라장터 OpenAPI 공통 처리.

인증 실패와 트래픽 초과는 HTTP 200에 XML 본문으로 온다. JSON 파싱 전에 반드시 걸러야 한다.
"""

import re

import httpx


class G2BError(RuntimeError):
    """API가 오류를 돌려줬을 때."""


def text(value) -> str:
    return "" if value is None else str(value).strip()


def to_int(value) -> int | None:
    s = text(value).replace(",", "")
    if not s:
        return None
    try:
        n = int(float(s))
    except ValueError:
        return None
    return n if n > 0 else None


def normalise_items(field) -> list[dict]:
    """items가 리스트일 때도 {'item': ...}일 때도 리스트로 맞춘다."""
    items = field or []
    if isinstance(items, dict):
        items = items.get("item", [])
    if isinstance(items, dict):
        items = [items]
    return list(items)


def explain_xml(body: str) -> str:
    for pattern in (r"<returnAuthMsg>([^<]*)<", r"<errMsg>([^<]*)<", r"<resultMsg>([^<]*)<"):
        if m := re.search(pattern, body):
            return m.group(1).strip()
    return body[:200]


def check_response(response: httpx.Response) -> dict:
    """오류면 G2BError를 올리고, 정상이면 response.body 딕셔너리를 돌려준다."""
    body_text = response.text.lstrip("﻿").strip()
    if response.status_code != 200:
        raise G2BError(f"HTTP {response.status_code}: {body_text[:200]}")
    if body_text.startswith("<"):
        raise G2BError(explain_xml(body_text))

    payload = response.json()
    envelope = payload.get("response")
    if not isinstance(envelope, dict):
        raise G2BError(f"응답 봉투에 response가 없다: {body_text[:200]}")
    header = envelope.get("header")
    if not isinstance(header, dict):
        raise G2BError(f"응답 봉투에 header가 없다: {body_text[:200]}")
    code = text(header.get("resultCode"))
    if code and code not in {"00", "0"}:
        raise G2BError(f"resultCode={code} {text(header.get('resultMsg'))}")
    return envelope.get("body") or {}
