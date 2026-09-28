# Nara

나라장터 설계용역 공고를 모아 낙찰업체·진행현황·실행부서를 조사하는 로컬 도구.

설계 문서: `docs/superpowers/specs/2026-09-17-nara-collector-design.md`

## 설치

```bash
uv sync
cp .env.example .env   # G2B_API_KEY를 채운다
```

## 쓰는 법

```bash
uv run nara collect --days 3                          # 최근 3일 수집
uv run nara backfill --days 365                        # 과거 1년 소급 (중단해도 이어짐)
uv run nara enrich award --tier focus                   # 낙찰업체 조회
uv run nara enrich status                               # 진행현황 판정 (구글 뉴스, 키 불필요)
uv run nara migrate tsv <파일> --tab 전북특별자치도      # 기존 시트 이관
uv run nara doctor                                      # 데이터 점검
uv run nara serve                                       # 조회·입력 화면 → http://127.0.0.1:8000
```

화면에서 고친 값은 `edit_log`에 남는다. 시트를 다시 이관하면 지난 이관 뒤 시트에서
실제로 바뀐 칸만 반영하고, 그 칸이 웹 입력을 덮으면 목록으로 알려준다. 사람이 정한
진행현황은 `enrich status`가 건너뛴다. 상세 화면의 "자동 판정에 다시 맡기기"로 푼다.

## 개발

```bash
uv run pytest --cov=nara
uv run ruff check .
```
