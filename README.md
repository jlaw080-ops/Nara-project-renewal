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
`http://<이 PC IP>:8000` 주소를 알려 준다. 사내망 안에서는 http라 비밀번호가 암호화되지 않으니
다른 곳에서 쓰는 비밀번호는 쓰지 않는다. 이 PC가 켜져 있어야 한다.

서버 설치는 [deploy/setup.md](deploy/setup.md)에 있다. 서버에서는 `nara run slot 09|12|15`가
하루 세 번 수집하고 `nara backup`이 매일 백업한다.

## 개발

```bash
uv run pytest --cov=nara
uv run ruff check .
```
