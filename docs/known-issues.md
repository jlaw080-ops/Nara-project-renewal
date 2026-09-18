# 알려진 미결 항목 (계획 1에서 이월)

계획 1(수집 기반·시트 이관) 실행 중 리뷰가 찾았으나 고치지 않고 넘긴 항목이다.
각각 "지금 고칠 만큼 무겁지 않다"는 판단이었지 "문제가 없다"는 뜻이 아니다.
계획 2·3을 시작할 때 이 목록을 먼저 읽는다.

판정 근거는 [계획 1 판정기록](2026.09.18_계획1_판정기록.md)에 있다.

## 이월 사유가 기록된 큰 항목

- **담당부서 가드** — `dept_check` INSERT가 담당부서가 있을 때만 걸린다.
  담당부서는 비었는데 전화번호·부서장만 있는 행이 생기면 그 정보가 유실된다.
  실데이터에는 그런 행이 0건이라 이월했다 (R29).
- **낙찰 조회 적체 아사** — 낙찰이 영영 없는 건이 쌓이면 최근 공고가 뒤로 밀린다.
  스펙이 "결과가 없으면 그대로 두고 다음 회차에 다시 본다"로 명시해 쿼리를
  바꾸지 않았고, 대신 `doctor`가 보이게 한다 (R15).
- **`config.toml`이 시트 `설정` 탭보다 3개 앞서 있다** — 덩굴제거·숲가꾸기·산불예방.
  시트에 반영하면 해소된다 (R30).

## 계획 3으로 넘어간 설계 사항

- 기관 관리 화면은 `org.tier`를 직접 UPDATE해야 한다 — `upsert_org`는 재분류하지 않는다.
- `GOOGLE_SERVICE_ACCOUNT_JSON`을 위한 `Secrets` 필드가 필요하다.

## 개별 minor 항목

- minor (deferred): nara/cli.py:5,10 — Typer(help=...) 문자열과 콜백 docstring이
- minor (deferred): dates.py 월/일 범위 검증 없음 — '20261399'가 '2026-13-99'가 된다.
- minor (deferred): dates.py:8 비문자열 입력이 오면 AttributeError. 실제 호출부는
- minor (deferred): _read_env가 인라인 주석(`KEY=value # note`)을 안 벗긴다.
- minor (deferred): pick = lambda ... # noqa: E731 — 작은 def가 나았다.
- minor (deferred): bool(collect.get("skip_cancelled", True)) 캐스팅 불필요.
- minor (deferred): 필수＋제외 동시 포함 케이스에 명시적 테스트가 없다(동작은 확인됨).
- minor (deferred): task-5-report.md가 "인덱스 8개"라 했으나 실제 6개. 코드는 정상.
- minor (deferred): test_foreign_keys_are_enforced가 PRAGMA 값만 보고 실제 FK
- minor (deferred): idempotency 테스트가 단가 5행 유지를 명시 단언하지 않는다.
- minor (deferred): connect()가 journal_mode=WAL 결과행을 확인하지 않는다.
- minor (deferred): test_iter_notices_honours_max_pages가 실제로는 총건수 도달로
- minor (deferred): to_int("12.7")이 12로 조용히 잘린다.
- minor (deferred): BOM 제거 분기에 테스트가 없다.
- minor (deferred): 다른 org_id로 재호출해 UPDATE가 실제로 바꾸는지 고정하는
- minor (deferred): run_log의 "partial"(failed>0) 경로 무테스트. 브리프 누락.
- minor (deferred): store.py 독스트링 "SQL은 이 파일에만 둔다"가 부정확 —
- minor (deferred): 건별 커밋이라 Task 8/9의 대량 수집에서 처리량을 재고할 여지.
- minor (deferred): skip_cancelled=False 분기와 빈 bid_no 분기에 테스트가 없다.
- minor (deferred): 수집 중 G2BError가 한 줄 메시지가 아니라 파이썬 트레이스백으로
- minor (deferred): backfill이 덮는 범위는 [floor, 오늘) 이라 실행 당일은 빠진다.
- minor (deferred): 중간 G2BError 시 커서 내구성을 직접 검증하는 테스트 없음
- minor (deferred): 커서가 now보다 미래일 때 반환값이 그 미래 날짜를 그대로 보고.
- minor (deferred): 재개 시 added 카운트가 부분 완료 청크만큼 중복 계산될 수 있다
- minor (deferred): --tier에 검증 없음(오타 시 빈 집합, 조용함).
- minor (deferred): 두 날짜 필드가 다 없으면 award_date가 ""로 들어간다.
- minor (deferred): award INSERT에 ON CONFLICT 없음. 한 회차 안에서는 도달 불가,
- minor (deferred): 3연속 short line 테스트 없음(손 추적으로는 정상).
- minor (deferred): estimate_cost가 round-half-even. 이 자릿수에선 도달 불가.

## 계획 2 (진행현황 판정)에서 이월

- **`nara doctor`가 cp949 콘솔에서 죽는다.** 출력에 쓰인 `—`를 Windows 기본
  코드페이지가 인코딩하지 못해 UnicodeEncodeError가 난다. Git Bash에서는
  나지 않는다. 우회: `PYTHONIOENCODING=utf-8 uv run nara doctor`.
  `nara/cli.py` 출력 전반에 걸친 문제라 진행현황 작업의 범위 밖으로 두었다.
- **뉴스 판정 경로는 실데이터로 검증되지 않았다.** 네이버·Claude 키가 없어
  규칙 경로와 "건너뛰었다" 경로만 확인됐다. 키를 넣은 첫 회차는 결과를
  사람이 직접 훑어야 한다.
- **`read_signals`는 낱말 대조다.** "착공"이라는 낱말이 없는 착공 기사는
  읽지 못한다. 실전에서 얼마나 맞는지는 돌려보기 전에는 알 수 없다.
- **`should_record`가 막은 이유가 어디에도 안 남는다.** 유일한 호출부가
  사유를 버린다(`ok, _ = should_record(...)`). 근거 URL을 가진 뉴스 판정이
  저장된 판정과 충돌해 버려져도 "변화 없음"으로만 집계된다. 특히 단계
  후퇴 가드는 근거 있는 반대 의견을 조용히 버린다.
- **뉴스 검색 실패 집계가 그 뒤의 예외에 먹힌다.** 검색은 401인데
  `judge_project`가 이어서 터지면 `search_failed`가 0으로 남는다
  (`counters.failed`에는 잡힌다). 부분 실패와 예산 초과 뒤 실패는 정확하다.
- **LLM 클라이언트 캐시가 테스트 실패 시 남는다.** `_reset_clients()`가
  픽스처가 아니라 본문 끝 한 줄이라, 중간에 실패한 테스트의 가짜
  클라이언트가 모듈 캐시에 남는다. 캐시된 클라이언트는 닫히지 않는다.
- **두 날짜 중 하나만 있는 사업은 개찰일 앵커를 영영 안 본다.** 실데이터
  해당 5건은 전부 개찰일이 비어 있어 현재 영향 0건.
