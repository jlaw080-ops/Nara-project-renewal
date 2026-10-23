# DataTable

패널 안의 표: 위에 결과 줄(건수·조건·내보내기), 고른 행이 있으면 일괄 작업 줄, 그 아래 표.

- 머리글 `surface-sunken`, 스크롤해도 위에 붙어 있다(sticky). 정렬 열은 진한 글자 + ▲▼, `aria-sort`.
- 행 높이 `row-height` 44px, 글자 `table` 13px. hover 때 `canvas`, 고른 행은 `primary-soft`.
- 사업명은 굵은 링크, 아래 공고명은 `.sub`(muted). 날짜는 줄바꿈 없음, 금액은 오른쪽 정렬.
- 진행현황은 StatusBadge, 빈 값은 "—".
- 숨기기 같은 일괄 작업은 행을 골랐을 때만 나오는 `.bulkbar`에 둔다 — 원본은 항상 보였다.
- 결과 없음: `.empty` 한 줄 안내 "조건에 맞는 사업이 없습니다".
