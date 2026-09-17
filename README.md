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
uv run nara migrate tsv <파일> --tab 전북특별자치도      # 기존 시트 이관
uv run nara doctor                                      # 데이터 점검
```

## 개발

```bash
uv run pytest --cov=nara
uv run ruff check .
```
