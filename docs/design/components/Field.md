# Field

라벨 위 · 입력칸 아래 묶음(`.field`). 라벨 `label` 13px 굵게, 칸 `control-md` 40px, 모서리 `radius-md`.

- 칸 테두리 `field-line`, hover 때 진해지고 포커스는 파란 2px 링.
- 도움말은 칸 아래 `.field__help`(muted 12px), 오류는 `.field__error`(danger 굵게) + 칸에 `aria-invalid="true"` → 빨간 테두리.
- 금액·면적 칸은 `.input--num`: 오른쪽 정렬, 숫자 폭 고정.
- 선택 항목은 라벨에 "(선택)".
