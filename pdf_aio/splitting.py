"""Ways to divide the workspace pages into groups, one group per output file.

Groups are lists of zero based workspace positions. The range syntax the user
types is one based, because that is how page numbers appear everywhere else
in the interface and in every PDF viewer.
"""

import re

from pdf_aio.workspace import PageRef, runs

_TOKEN = re.compile(r"^(\d*)\s*-\s*(\d*)$|^(\d+)$")


class RangeSyntaxError(ValueError):
    """The page range text cannot be read, or names pages that do not exist."""


def parse_ranges(text: str, page_count: int) -> list[list[int]]:
    """Read text such as "1-3, 5, 8-" into one group per comma separated part.

    "A-" runs to the last page, "-B" starts at the first, and "B-A" with B
    greater than A lists the pages in descending order.
    """
    groups: list[list[int]] = []
    for token in re.split(r"[,;]", text):
        token = token.strip()
        if not token:
            continue
        match = _TOKEN.match(token)
        if match is None:
            raise RangeSyntaxError(f'"{token}": 페이지 번호나 3-7 같은 범위로 읽을 수 없습니다')
        if match.group(3) is not None:
            first = last = int(match.group(3))
        else:
            first = int(match.group(1)) if match.group(1) else 1
            last = int(match.group(2)) if match.group(2) else page_count
        for number in (first, last):
            if not 1 <= number <= page_count:
                raise RangeSyntaxError(
                    f'"{token}": {number}페이지를 가리키지만 전체는 {page_count}페이지입니다'
                )
        step = 1 if last >= first else -1
        groups.append([n - 1 for n in range(first, last + step, step)])
    if not groups:
        raise RangeSyntaxError("페이지나 범위를 하나 이상 입력하세요. 예: 1-3, 5")
    return groups


def every(page_count: int, size: int) -> list[list[int]]:
    """Consecutive groups of `size` pages; the last group may be shorter."""
    if size < 1:
        raise ValueError(f"나눌 페이지 수는 1 이상이어야 합니다 (입력: {size})")
    return [list(range(i, min(i + size, page_count))) for i in range(0, page_count, size)]


def by_source(pages: tuple[PageRef, ...]) -> list[list[int]]:
    """One group per run of pages that came from the same file."""
    return [list(run.indices) for run in runs(pages)]
