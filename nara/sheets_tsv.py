"""구글시트 TSV 내보내기를 읽는다.

셀 안에 줄바꿈이 있으면 한 행이 두 줄로 나온다. 필드 수가 헤더보다 적은 줄은
다음 줄과 합쳐 원래 행을 되살린다. 이 처리를 빠뜨리면 이후 모든 행이 밀린다.
"""

import csv
import io
from dataclasses import dataclass


@dataclass(frozen=True)
class TsvStats:
    physical_lines: int  # 헤더를 뺀 물리 줄 수
    restored_rows: int  # 병합 후 행 수
    merges: int  # 병합에 흡수된 줄 수
    truncations: int  # 헤더보다 길어 잘린 행 수


def read_tsv_with_stats(text: str) -> tuple[list[str], list[list[str]], TsvStats]:
    raw = list(csv.reader(io.StringIO(text), delimiter="\t"))
    if not raw:
        return [], [], TsvStats(physical_lines=0, restored_rows=0, merges=0, truncations=0)

    header = raw[0]
    width = len(header)
    physical_lines = len(raw) - 1
    rows: list[list[str]] = []
    truncations = 0

    i = 1
    while i < len(raw):
        row = raw[i]
        while len(row) < width and i + 1 < len(raw):
            nxt = raw[i + 1]
            if not nxt:
                # 셀 안의 빈 줄(문단 구분). 이어붙일 내용이 없으니 삼키고 넘어간다.
                # 이걸 안 막으면 nxt[0]에서 IndexError가 나 이관 전체가 죽는다.
                i += 1
                continue
            row = row[:-1] + [f"{row[-1]} {nxt[0].strip()}".strip()] + nxt[1:]
            i += 1
        if len(row) > width:
            truncations += 1
        # 헤더 길이에 정확히 맞춘다. 모자라면 채우고, 넘치면 자른다 — 넘친 칸은
        # 헤더에 대응하는 열이 없어 어차피 읽히지 않는다.
        rows.append((row + [""] * (width - len(row)))[:width])
        i += 1

    stats = TsvStats(
        physical_lines=physical_lines,
        restored_rows=len(rows),
        merges=physical_lines - len(rows),
        truncations=truncations,
    )
    return header, rows, stats


def read_tsv(text: str) -> tuple[list[str], list[list[str]]]:
    header, rows, _ = read_tsv_with_stats(text)
    return header, rows
