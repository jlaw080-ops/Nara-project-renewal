"""공고를 받아들일지 결정하는 순수 함수들."""

from nara.config import Settings


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(k and k in text for k in keywords)


def title_passes(title: str, settings: Settings) -> bool:
    """제목 필수 키워드를 하나라도 포함하고 제외 키워드를 하나도 포함하지 않으면 통과."""
    s = (title or "").strip()
    if not s:
        return False
    if settings.title_required and not _contains_any(s, settings.title_required):
        return False
    return not _contains_any(s, settings.title_excluded)


def org_passes(org: str, settings: Settings) -> bool:
    """수요기관 제외 키워드를 포함하지 않으면 통과. 포함 필터는 두지 않는다(전국 수집)."""
    s = (org or "").strip()
    if not s:
        return False
    return not _contains_any(s, settings.org_excluded)


def is_focus_org(org: str, settings: Settings) -> bool:
    """관심 기관 목록의 이름이 수요기관 문자열에 들어 있으면 관심 기관."""
    return _contains_any((org or "").strip(), settings.focus_orgs)
