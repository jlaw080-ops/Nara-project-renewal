"""구글시트 TSV 내보내기를 읽는다.

셀 안에 줄바꿈이 있으면 한 행이 두 줄로 나온다. 필드 수가 헤더보다 적은 줄은
다음 줄과 합쳐 원래 행을 되살린다. 이 처리를 빠뜨리면 이후 모든 행이 밀린다.
"""

import csv
import io


def read_tsv(text: str) -> tuple[list[str], list[list[str]]]:
    raw = list(csv.reader(io.StringIO(text), delimiter="\t"))
    if not raw:
        return [], []

    header = raw[0]
    width = len(header)
    rows: list[list[str]] = []

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
        # 헤더 길이에 정확히 맞춘다. 모자라면 채우고, 넘치면 자른다 — 넘친 칸은
        # 헤더에 대응하는 열이 없어 어차피 읽히지 않는다.
        rows.append((row + [""] * (width - len(row)))[:width])
        i += 1

    return header, rows
