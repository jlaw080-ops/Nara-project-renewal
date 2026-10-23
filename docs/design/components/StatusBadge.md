# StatusBadge

진행현황을 글자 + 색 배지로 보여 준다. 표에서 한눈에 훑을 수 있게 하는 개선의 핵심.

| 값 | 클래스 | 색 | 뜻 |
|---|---|---|---|
| 착공 전(설계 단계) | `.badge--before` | primary-soft / primary-hover | 지금 영업·검토 대상 — 가장 눈에 띄게 |
| 시공 중 | `.badge--building` | warning-soft / warning | |
| 준공 완료 | `.badge--done` | success-soft / success | |
| 미확인 | `.badge--unknown` | neutral-soft / fg-secondary | |
| 판정 전 | `.badge--none` | 테두리만, muted | 아직 판정하지 않음 |

- 색만으로 구분하지 않는다: 항상 글자가 함께 있다.
- 사람이 정한 값은 배지 옆에 작은 "수동" 표시(`.by-human`) — 원본의 "(사람)"을 대신한다.
- "검토 필요"(실행부서)도 `.badge--none` 모양을 쓴다.
