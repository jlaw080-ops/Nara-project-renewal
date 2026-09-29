"""첨부 받기 — 다운로드 주소로 직접, 파일이 아니면 저장하지 않는다."""

import json

import httpx
import pytest

from nara.g2b import attach
from nara.g2b.attach import (
    AttachError,
    RemoteFile,
    choose,
    fetch,
    files_from_raw,
    gather,
    probe_url,
    safe_name,
)

HWPX = b"PK\x03\x04" + b"\x00" * 20
PDF = b"%PDF-1.4" + b"\x00" * 20
HWP = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 20


def _client(files: dict[int, tuple[int, dict, bytes]], seen: list | None = None):
    """fileSeq별 (상태, 머리, 본문). 없는 순번은 나라장터처럼 422와 JSON."""

    def handler(request: httpx.Request) -> httpx.Response:
        seq = int(request.url.params["fileSeq"])
        if seen is not None:
            seen.append(seq)
        status, headers, body = files.get(
            seq, (422, {"content-type": "application/json"}, b'{"ErrorMsg":"x"}')
        )
        return httpx.Response(status, headers=headers, content=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _disp(name: str) -> dict:
    from urllib.parse import quote

    return {"content-disposition": f"attachment;filename={quote(name)};"}


def _raw(*pairs: tuple[str, str]) -> str:
    raw = {}
    for i in range(1, 11):
        name, url = pairs[i - 1] if i <= len(pairs) else ("", "")
        raw[f"ntceSpecFileNm{i}"] = name
        raw[f"ntceSpecDocUrl{i}"] = url
    return json.dumps(raw, ensure_ascii=False)


def test_files_from_raw_reads_names_and_urls():
    raw = _raw(("공고문.hwpx", "https://g2b/1"), ("", ""), ("과업지시서.hwp", "https://g2b/3"))
    assert files_from_raw(raw) == [
        RemoteFile(1, "공고문.hwpx", "https://g2b/1"),
        RemoteFile(3, "과업지시서.hwp", "https://g2b/3"),
    ]
    assert files_from_raw(None) == []
    assert files_from_raw("not json") == []


def test_probe_url_uses_the_bid_number_and_order():
    url = probe_url("R26BK01", None, 2)
    assert "bidPbancNo=R26BK01" in url and "bidPbancOrd=000" in url and "fileSeq=2" in url


def test_choose_prefers_the_notice_then_the_task_and_one_format_each():
    files = [
        RemoteFile(1, "참가신청서.hwp", "u1"),
        RemoteFile(2, "공고문.hwp", "u2"),
        RemoteFile(3, "공고문.pdf", "u3"),
        RemoteFile(4, "공고문.hwpx", "u4"),
        RemoteFile(5, "과업지시서.pdf", "u5"),
        RemoteFile(6, "설계공모지침서.hwp", "u6"),
        RemoteFile(7, "도면.zip", "u7"),
    ]
    assert [f.seq for f in choose(files)] == [4, 5]


def test_choose_falls_back_to_task_documents_and_skips_unreadable_files():
    files = [RemoteFile(1, "제안요청서.hwp", "u1"), RemoteFile(2, "공고.xlsx", "u2")]
    assert [f.seq for f in choose(files)] == [1]
    assert choose([RemoteFile(1, "도면.zip", "u1")]) == []


def test_safe_name_keeps_files_inside_the_folder():
    """서버가 보낸 이름으로 폴더 밖에 쓰면 안 된다."""
    assert safe_name("../../evil.hwp") == "evil.hwp"
    assert safe_name("a\\b\\c.pdf") == "c.pdf"
    assert safe_name("공고\x00문:?.hwp") == "공고_문__.hwp"
    assert safe_name("..") == "첨부"
    assert len(safe_name("가" * 300 + ".pdf")) == 100


def test_fetch_reads_the_name_from_the_header():
    client = _client({1: (200, _disp("공고문(청사).hwpx"), HWPX)})
    name, content, kind = fetch(client, probe_url("B1", "000", 1))
    assert (name, kind) == ("공고문(청사).hwpx", "hwpx")
    star = _client(
        {1: (200, {"content-disposition": "attachment; filename*=UTF-8''%EA%B3%B5.pdf"}, PDF)}
    )
    assert fetch(star, probe_url("B1", "000", 1))[0] == "공.pdf"


def test_fetch_refuses_a_page_that_is_not_a_file():
    """나라장터가 200으로 안내 페이지를 줘도 파일로 저장하면 안 된다."""
    client = _client({1: (200, {"content-type": "text/html"}, b"<!DOCTYPE html>")})
    with pytest.raises(AttachError):
        fetch(client, probe_url("B1", "000", 1))


def test_fetch_refuses_a_file_over_the_size_limit(monkeypatch):
    monkeypatch.setattr(attach, "MAX_BYTES", 10)
    client = _client({1: (200, _disp("공고문.pdf"), PDF)})
    with pytest.raises(AttachError, match="30MB"):
        fetch(client, probe_url("B1", "000", 1))


def test_gather_uses_the_listed_files_when_the_raw_notice_has_them():
    seen: list[int] = []
    client = _client({2: (200, _disp("x"), PDF)}, seen)
    raw = _raw(
        ("참가신청서.hwp", probe_url("B1", "000", 1)), ("공고문.pdf", probe_url("B1", "000", 2))
    )
    got = gather(client, "B1", "000", raw, sleep=lambda s: None)
    assert [(d.seq, d.name, d.kind) for d in got] == [(2, "공고문.pdf", "pdf")]
    assert seen == [2]


def test_gather_reports_a_listed_file_that_does_not_download():
    client = _client({1: (200, {"content-type": "text/html"}, b"<html>")})
    raw = _raw(("공고문.pdf", probe_url("B1", "000", 1)))
    with pytest.raises(AttachError):
        gather(client, "B1", "000", raw, sleep=lambda s: None)


def test_gather_probes_numbers_until_the_first_non_file():
    """옛 공고는 원본이 없다. 순번을 차례로 받다가 파일이 아니면 멈춘다."""
    seen: list[int] = []
    client = _client(
        {
            1: (200, _disp("공고문.hwpx"), HWPX),
            2: (200, _disp("과업지시서.hwp"), HWP),
            3: (200, {"content-type": "text/html"}, b"<html>"),
            4: (200, _disp("공고문.pdf"), PDF),
        },
        seen,
    )
    got = gather(client, "B1", None, None, sleep=lambda s: None)
    assert [(d.seq, d.name) for d in got] == [(1, "공고문.hwpx"), (2, "과업지시서.hwp")]
    # 이름은 응답 머리로만 확인하고(1·2·3), 고른 파일만 내려받는다(1·2)
    assert seen == [1, 2, 3, 1, 2]


def test_gather_waits_between_requests():
    waits: list[float] = []
    client = _client({1: (200, _disp("공고문.pdf"), PDF)})
    gather(client, "B1", None, None, sleep=waits.append)
    assert waits and all(w == attach.PAUSE_SECONDS for w in waits)


def test_probing_does_not_download_files_it_will_not_keep(monkeypatch):
    """옛 공고는 이름을 알려고 순번을 훑는다. 도면처럼 큰 파일까지 받으면 안 된다."""
    monkeypatch.setattr(attach, "MAX_BYTES", 100)
    seen: list[int] = []
    client = _client(
        {
            1: (200, _disp("공고문.pdf"), PDF),
            2: (200, _disp("도면.pdf"), b"%PDF" + b"x" * 1000),
        },
        seen,
    )
    got = gather(client, "B1", None, None, sleep=lambda s: None)
    assert [d.name for d in got] == ["공고문.pdf"]
    assert seen == [1, 2, 3, 1]


def test_probing_stops_at_a_response_that_is_not_an_attachment():
    seen: list[int] = []
    client = _client(
        {
            1: (200, _disp("공고문.pdf"), PDF),
            2: (200, {"content-type": "text/html"}, b"<html>"),
            3: (200, _disp("과업지시서.pdf"), PDF),
        },
        seen,
    )
    got = gather(client, "B1", None, None, sleep=lambda s: None)
    assert [d.name for d in got] == ["공고문.pdf"]
    assert seen == [1, 2, 1]


def _two_listed() -> str:
    return _raw(
        ("공고문.hwpx", probe_url("B1", "000", 1)), ("과업지시서.pdf", probe_url("B1", "000", 2))
    )


def test_a_failed_second_document_does_not_drop_the_notice():
    """과업지시서가 상한을 넘거나 깨져도 공고문은 읽는다. 둘째 문서는 보조다."""
    client = _client(
        {1: (200, _disp("x"), HWPX), 2: (200, {"content-type": "text/html"}, b"<html>")}
    )
    got = gather(client, "B1", "000", _two_listed(), sleep=lambda s: None)
    assert [d.name for d in got] == ["공고문.hwpx"]


def test_a_failed_notice_document_is_still_a_failure():
    client = _client({1: (500, {}, b""), 2: (200, _disp("x"), PDF)})
    with pytest.raises(AttachError):
        gather(client, "B1", "000", _two_listed(), sleep=lambda s: None)


def test_an_error_on_the_first_probe_is_a_failure_not_an_empty_notice():
    """점검 안내·5xx를 '첨부 없음'으로 적으면 다시 보지 않는다. 없는 순번(422)만 끝이다."""
    for status, headers, body in [(503, {}, b""), (200, {"content-type": "text/html"}, b"<x>")]:
        with pytest.raises(AttachError):
            gather(_client({1: (status, headers, body)}), "B1", None, None, sleep=lambda s: None)
    assert gather(_client({}), "B1", None, None, sleep=lambda s: None) == []
