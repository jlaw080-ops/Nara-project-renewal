# AppBar

화면 맨 위의 짙은 남색(`brand-navy`) 바: 앱 이름, 주 메뉴, 오른쪽에 외부 링크·사용자·로그아웃.

- 원본의 오른쪽 위 작은 링크 줄을 대신한다. 지금 어느 화면인지 현재 메뉴 아래 흰 막대(`stroke-active-tab`)로 보인다 — `aria-current="page"`.
- 메뉴 순서는 일하는 순서: 사업 조회 → 설치계획 → 단가 관리 → 설정.
- 로그아웃은 버튼이 아니라 링크 모양(POST 폼 안의 `.btn--quiet`도 가능). 비밀번호 바꾸기는 사용자 이름을 누르면 나오는 메뉴로 옮긴다.
- 높이 `appbar-height` 56px, 글자 `on-navy` / `on-navy-muted`.
