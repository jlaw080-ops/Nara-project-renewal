"""2026-09-16 전북 조사에서 실제로 틀렸거나 헷갈렸던 건을 그대로 박아 둔다.

여기가 깨지면 그때의 사고가 되돌아온 것이다. 테스트를 고치지 말고 규칙을 고친다.
"""

from nara.verdict import BEFORE, BUILDING, DONE, UNKNOWN, Article, read_news


def test_wanju_multipurpose_gym_start_or_plan_is_not_decided_by_rules():
    """완주군 다목적체육관 — 시트 착공 2026.04.30, 보도 '2026.09 착공'.

    예정인지 실제인지 기사만으로 갈리지 않는다. 기계가 정하면 안 된다.
    """
    got = read_news(
        [
            Article(
                "완주군 다목적체육관 조성사업 2026년 9월 착공 목표",
                "",
                "https://news.example.com/wanju",
                "2026-08-10",
            )
        ],
        ("2026-04-30", "2028-12-31"),
    )
    assert got.needs_llm is True
    assert got.verdict == UNKNOWN


def test_jinan_senior_center_2006_article_does_not_decide_a_2026_project():
    """진안복합노인 복지센터 — 2006.05 개원 기사가 검색돼 들어왔다.

    시트는 착공 2007·준공 2008이다. 같은 이름의 다른(또는 옛) 시설이다.
    """
    got = read_news(
        [
            Article(
                "진안복합노인 복지센터 개원",
                "",
                "https://news.example.com/jinan",
                "2006-05-26",
            )
        ],
        ("2026-01-01", "2027-12-31"),
    )
    assert got.needs_llm is True
    assert got.verdict != DONE


def test_jinan_senior_center_is_still_guarded_when_only_the_opening_date_is_known():
    """같은 사고, 실데이터의 모양 그대로 — 사업 날짜 두 칸이 모두 비어 있다.

    실데이터 249건 중 196건이 착공일·준공일을 둘 다 갖고 있지 않다. 위
    테스트처럼 두 날짜를 넣어야만 통과하는 가드는 그 196건에서 통째로
    죽어 있다 — 2006년 개원 기사 한 건이 확신에 찬 '준공 완료'가 된다.
    공고 개찰일은 그 196건 중 152건이 갖고 있는 유일한 시간 기준점이다.
    """
    got = read_news(
        [
            Article(
                "진안복합노인 복지센터 개원",
                "",
                "https://news.example.com/jinan",
                "2006-05-26",
            )
        ],
        ("", ""),
        open_date="2026-03-02",
    )
    assert got.needs_llm is True
    assert got.verdict != DONE


def test_sunchang_gym_completion_and_start_articles_collide():
    """순창군 동계면 종합체육관 — 시트 착공 2025.07.17, 보도는 2020 착공·2025.06.25 준공."""
    got = read_news(
        [
            Article(
                "순창군 동계면 종합체육관 착공",
                "",
                "https://news.example.com/s1",
                "2020-01-15",
            ),
            Article(
                "순창군 동계면 종합체육관 준공식",
                "",
                "https://news.example.com/s2",
                "2025-06-25",
            ),
        ],
        ("2025-07-17", "2026-12-31"),
    )
    assert got.needs_llm is True


def test_demolition_is_not_construction_start():
    """철거를 착공으로 읽어 영업 대상에서 빼는 사고가 반복됐다.

    이주 → 철거 → 본공사 착공 순서다. 철거 중이면 오히려 접촉 최적기다.
    '철거'라는 낱말만 있으면 규칙이 바로 '착공 전'으로 읽는다.
    """
    got = read_news(
        [
            Article(
                "옛 청사 철거 시작",
                "멸실 신고를 마쳤다",
                "https://news.example.com/demo",
                "2026-07-01",
            )
        ],
        ("", ""),
    )
    assert got.verdict == BEFORE
    assert got.needs_llm is False


def test_demolition_with_a_start_word_is_not_read_as_construction():
    """'철거공사 착수'는 철거 신호와 착공 신호가 한 기사에 같이 잡힌다.

    낱말만으로는 '철거공사 착수'(철거가 시작됨)와 '철거 마치고 본공사
    착공'(본공사가 시작됨)을 가를 수 없다. 둘은 정반대 뜻인데 신호가
    똑같다. 그래서 규칙은 판정하지 않고 넘긴다.

    지켜야 할 것은 '착공 전'이라는 글자가 아니라 **'시공 중'으로 읽히지
    않는 것**이다. 영업 대상에서 빠지는 사고는 '시공 중' 판정에서 온다.
    미확인은 판정을 쌓지 않으므로 기존 상태가 그대로 남는다.
    """
    got = read_news(
        [
            Article(
                "옛 청사 철거공사 착수",
                "멸실 신고를 마쳤다",
                "https://news.example.com/demo",
                "2026-07-01",
            )
        ],
        ("", ""),
    )
    assert got.verdict != BUILDING
    assert got.needs_llm is True


def test_a_clear_groundbreaking_still_reads_as_construction():
    """강등 규칙이 과해져서 진짜 착공까지 놓치면 안 된다 — 반대 방향 확인."""
    got = read_news(
        [
            Article(
                "완주군 종합사회복지관 기공식 개최",
                "",
                "https://news.example.com/w2",
                "2026-08-28",
            )
        ],
        ("2027-10-07", ""),
    )
    assert got.verdict == BUILDING
    assert got.needs_llm is False
