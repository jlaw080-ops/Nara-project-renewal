"""나라장터 공고 첨부를 받는다. 브라우저 없이 다운로드 주소로 직접 받는다.

공고 API 원본에 파일 이름과 주소가 있으면 그것을 쓴다. 없으면(시트에서 옮긴 옛
공고) 공고번호와 순번으로 주소를 만들어 차례로 받아 보고, 파일이 아닌 응답이
오면 멈춘다. 2026-09-29 실측: 없는 순번은 422와 JSON 오류를 돌려준다.
"""

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import unquote

import httpx

from nara.doctext import kind_of

DOWNLOAD_URL = (
    "https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/downloadFile.do"
    "?bidPbancNo={bid_no}&bidPbancOrd={bid_ord}&fileType=&fileSeq={seq}&prcmBsneSeCd=05"
)
MAX_FILES = 10
NO_SUCH_FILE = 422  # 없는 순번에 나라장터가 주는 상태(2026-09-29 실측)
MAX_BYTES = 30 * 1024 * 1024
TIMEOUT_SECONDS = 30.0
PAUSE_SECONDS = 0.5  # 나라장터에 부담을 주지 않도록 요청 사이에 쉰다
MAX_DOCS = 2
READABLE = ("hwpx", "pdf", "hwp")  # 같은 문서가 여러 형식이면 이 순서로 하나만
_GROUPS = (re.compile(r"공고"), re.compile(r"과업|지침|제안"))
_NAME_LIMIT = 100
_FILENAME_STAR = re.compile(r"filename\*\s*=\s*[Uu][Tt][Ff]-8''([^;]+)")
_FILENAME = re.compile(r'filename\s*=\s*"?([^";]+)"?')


class AttachError(Exception):
    """파일이 아닌 응답(오류 안내 JSON·HTML)이거나 너무 큰 파일."""


@dataclass(frozen=True)
class RemoteFile:
    seq: int
    name: str
    url: str
    kind: str = ""  # 받아 본 뒤에 안 형식. 모르면 확장자로 가린다


@dataclass(frozen=True)
class Download:
    seq: int
    name: str
    content: bytes
    kind: str


def files_from_raw(raw_json: str | None) -> list[RemoteFile]:
    if not raw_json:
        return []
    try:
        raw = json.loads(raw_json)
    except ValueError:
        return []
    files = []
    for i in range(1, MAX_FILES + 1):
        name = (raw.get(f"ntceSpecFileNm{i}") or "").strip()
        url = (raw.get(f"ntceSpecDocUrl{i}") or "").strip()
        if name and url:
            files.append(RemoteFile(i, name, url))
    return files


def probe_url(bid_no: str, bid_ord: str | None, seq: int) -> str:
    return DOWNLOAD_URL.format(bid_no=bid_no, bid_ord=bid_ord or "000", seq=seq)


def safe_name(raw: str) -> str:
    """서버가 보낸 이름에서 경로·제어 문자를 걷어 낸다. 폴더 밖으로 나가지 못하게 한다."""
    name = raw.replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r'[\x00-\x1f<>:"|?*]', "_", name).strip(" .")
    return name[:_NAME_LIMIT] or "첨부"


def _ext(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _stem(name: str) -> str:
    return name.rsplit(".", 1)[0] if "." in name else name


def _kind(f: RemoteFile) -> str:
    return f.kind or _ext(f.name)


def choose(files: list[RemoteFile]) -> list[RemoteFile]:
    """공고 → 과업·지침·제안 순으로 최대 두 문서. 같은 문서가 여러 형식이면 하나만."""
    readable = [f for f in files if _kind(f) in READABLE]
    picked: list[RemoteFile] = []
    for pattern in _GROUPS:
        group = [f for f in readable if pattern.search(f.name) and f not in picked]
        if not group:
            continue
        stem = _stem(group[0].name)
        same = [f for f in group if _stem(f.name) == stem]
        picked.append(min(same, key=lambda f: READABLE.index(_kind(f))))
        if len(picked) == MAX_DOCS:
            break
    return picked


def _header_name(disposition: str) -> str:
    match = _FILENAME_STAR.search(disposition) or _FILENAME.search(disposition)
    return unquote(match.group(1).strip()) if match else ""


def fetch(client: httpx.Client, url: str) -> tuple[str, bytes, str]:
    """(서버가 알려 준 이름, 내용, 형식). 파일이 아니면 AttachError."""
    with client.stream("GET", url, timeout=TIMEOUT_SECONDS, follow_redirects=True) as response:
        if response.status_code != 200:
            raise AttachError(f"HTTP {response.status_code}")
        chunks, size = [], 0
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > MAX_BYTES:
                raise AttachError("30MB를 넘는 파일")
            chunks.append(chunk)
        disposition = response.headers.get("content-disposition", "")
    content = b"".join(chunks)
    kind = kind_of(content)
    if kind is None:
        raise AttachError("PDF·HWPX·HWP 파일이 아님")
    return _header_name(disposition), content, kind


def peek(client: httpx.Client, url: str) -> str | None:
    """첨부면 서버가 알려 준 이름, 없는 순번(422)이면 None. 본문은 읽지 않는다.

    그 밖의 응답(점검 안내 페이지·5xx)은 AttachError다 — 파일이 없다는 뜻이 아니다.
    """
    with client.stream("GET", url, timeout=TIMEOUT_SECONDS, follow_redirects=True) as response:
        disposition = response.headers.get("content-disposition", "")
        if response.status_code == 200 and "attachment" in disposition.lower():
            return _header_name(disposition) or None
        if response.status_code == NO_SUCH_FILE:
            return None
        raise AttachError(f"첨부가 아닌 응답: HTTP {response.status_code}")


def _fetch_chosen(
    client: httpx.Client, files: list[RemoteFile], sleep: Callable[[float], None]
) -> list[Download]:
    """고른 문서를 받는다. 첫 문서(공고문)를 못 받으면 실패다. 둘째는 보조라
    못 받아도 첫 문서만으로 읽는다 — 그림 많은 과업지시서가 상한을 넘는 일이 흔하다."""
    downloads = []
    for i, f in enumerate(files):
        sleep(PAUSE_SECONDS)
        try:
            _, content, kind = fetch(client, f.url)
        except AttachError, httpx.HTTPError:
            if i == 0:
                raise
            continue
        downloads.append(Download(f.seq, f.name, content, kind))
    return downloads


def gather(
    client: httpx.Client,
    bid_no: str,
    bid_ord: str | None,
    raw_json: str | None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Download]:
    """고른 문서를 받아 돌려준다. 받을 문서가 없으면 빈 목록.

    공고문을 못 받으면 AttachError·httpx.HTTPError를 그대로 올린다.
    """
    listed = files_from_raw(raw_json)
    if listed:
        chosen = [RemoteFile(f.seq, safe_name(f.name), f.url) for f in choose(listed)]
        return _fetch_chosen(client, chosen, sleep)

    # 원본이 없으면 순번을 훑어 이름만 읽는다(응답 머리). 도면처럼 큰 파일을 이름 때문에
    # 내려받지 않는다. 없는 순번(422)이 오면 거기까지가 그 공고의 파일이다. 첫 순번이
    # 오류면 실패로 올린다 — '첨부 없음'으로 적으면 다시 보지 않는다.
    probed: list[RemoteFile] = []
    for seq in range(1, MAX_FILES + 1):
        sleep(PAUSE_SECONDS)
        url = probe_url(bid_no, bid_ord, seq)
        try:
            name = peek(client, url)
        except AttachError:
            if seq == 1:
                raise
            break
        if name is None:
            break
        probed.append(RemoteFile(seq, safe_name(name), url))
    return _fetch_chosen(client, choose(probed), sleep)
