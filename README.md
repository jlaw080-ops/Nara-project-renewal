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
uv run nara serve                                       # 조회·입력 화면 → http://127.0.0.1:8120
```

화면에서 고친 값은 `edit_log`에 남는다. 시트를 다시 이관하면 지난 이관 뒤 시트에서
실제로 바뀐 칸만 반영하고, 그 칸이 웹 입력을 덮으면 목록으로 알려준다. 사람이 정한
진행현황은 `enrich status`가 건너뛴다. 상세 화면의 "자동 판정에 다시 맡기기"로 푼다.

진행현황 자동 판정 기준:

| 사업 | 기준 | 판정 |
|---|---|---|
| 설치계획서가 연결된 사업 | 준공예정일까지 6개월 넘게 남음 | 시공 중 |
| | 준공예정일 앞뒤 6개월 안 | 날짜로 정하지 않음(공고·뉴스로 판정) |
| | 준공예정일에서 6개월 넘게 지남 | 준공 완료 |
| 나라장터 설계용역 공고 사업 | 개찰 전후와 관계없이 | 착공 전(설계 단계), 착공·준공 보도가 있으면 그에 따름 |

설치계획서 날짜 판정은 뉴스·시트 이관 판정보다 앞서지만 사람이 정한 판정은 덮지 않고,
판정은 착공 전 → 시공 중 → 준공 완료 방향으로만 바뀐다.

### 실행부서 찾기

`uv run nara enrich dept`가 공고 첨부(공고문·과업지시서)를 받아 읽고 실행부서를 찾는다.
후보가 하나로 좁혀지면 확정하고, 애매하면 Claude가 고른 근거 문장을 원문과 대조해 맞을
때만 확정한다. 나머지는 목록에서 "실행부서 검토 필요"로 모아 사람이 고른다. 받은 첨부는
DB 옆 `attachments` 폴더에 둔다. 예약 슬롯이 관심기관은 09·15시, 비관심기관은 평일 12시에 돌린다.
Claude API 키가 없거나 답을 못 받은 건은 사유에 "Claude 확인 전"이 붙고, 키를 넣으면 다음
회차에 받아 둔 첨부로 다시 묻는다. 키를 처음 넣은 날에는 `uv run nara enrich dept --limit 5`로
"답을 못 받은 건"이 0인지 먼저 본다.

### 로그인과 서버

화면은 로그인해야 열린다. `.env`에 `NARA_SECRET_KEY`(무작위 긴 글자)를 넣고
`uv run nara user add <이메일> --name <이름>`으로 계정을 만든다. 임시 비밀번호는 한 번만
보이고, 첫 로그인에서 바꾼다.

사내망의 다른 PC에서 써 보게 하려면 `uv run nara serve --lan`으로 띄우고, 화면에 나온
`http://<이 PC IP>:8120` 주소를 알려 준다. 사내망 안에서는 http라 비밀번호가 암호화되지 않으니
다른 곳에서 쓰는 비밀번호는 쓰지 않는다. 이 PC가 켜져 있어야 한다.

### 이 PC에서 로그인과 함께 켜기

작업 스케줄러의 `\nara\web` 작업이 Windows 로그인 때 창 없이 `nara serve`를 띄운다. 출력은
`data\logs\web.log`에 쌓이고, 꺼지면 1분 뒤 다시 켜진다. 바탕화면의 "나라 앱" 아이콘으로 연다.

```powershell
# 지금 끄기 — 작업만 멈추면 서버 프로세스가 남으므로 8120 포트를 쓰는 프로세스도 끈다
Stop-ScheduledTask -TaskPath '\nara\' -TaskName web; Get-NetTCPConnection -LocalPort 8120 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
Start-ScheduledTask -TaskPath '\nara\' -TaskName web    # 다시 켜기
Disable-ScheduledTask -TaskPath '\nara\' -TaskName web  # 자동 실행 해제 (끄기와 함께)
```

작업은 등록만 저장소 밖(이 PC의 작업 스케줄러)에 있다. 다른 PC에 새로 둘 때는 `slot-09` 작업처럼
`conhost.exe --headless cmd.exe /d /c "... uv run nara serve >> data\logs\web.log 2>&1"`을
"로그온할 때" 트리거, 실행 시간 제한 없음, 실패 시 1분 뒤 재시작으로 등록한다.

서버가 켜져 있으면 `.venv`가 잠겨 `uv sync`가 실패한다. 의존성이 바뀐 코드를 받을 때는 먼저
끄고, `uv sync` 뒤 다시 켠다.

서버 설치는 [deploy/setup.md](deploy/setup.md)에 있다. 서버에서는 `nara run slot 09|12|15`가
하루 세 번 수집하고 `nara backup`이 매일 백업한다.

## 개발

```bash
uv run pytest --cov=nara
uv run ruff check .
```
