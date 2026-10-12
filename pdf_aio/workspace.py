"""The workspace: an ordered list of page references and its edit history.

A workspace never touches PDF data. Each entry names one page of a source
document held by the library, plus the rotation the user added on top of the
page's own. Every edit replaces the whole tuple, so undo is a stack of the
previous tuples and costs nothing beyond the references themselves.
"""

from collections.abc import Iterable
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class PageRef:
    """One page of the output, as a pointer into a source document."""

    source: int  # library id of the source document
    index: int  # zero based page number inside that source
    rotation: int = 0  # clockwise degrees added to the page's own /Rotate


@dataclass(frozen=True)
class Run:
    """A maximal stretch of consecutive workspace pages from one source.

    Right after files are added, each run is exactly one file, which is why
    the file view shows runs: moving a run moves the whole file. Once pages of
    two files are interleaved, a file simply appears as several runs.
    """

    source: int
    start: int  # workspace index of the first page
    stop: int  # workspace index one past the last page

    @property
    def indices(self) -> range:
        return range(self.start, self.stop)


def runs(pages: tuple[PageRef, ...]) -> list[Run]:
    result: list[Run] = []
    start = 0
    for i in range(1, len(pages) + 1):
        if i == len(pages) or pages[i].source != pages[start].source:
            result.append(Run(pages[start].source, start, i))
            start = i
    return result


class Workspace:
    """Ordered page references with undo and redo.

    Methods that take `indices` accept any iterable of workspace positions;
    duplicates and order do not matter. Methods that change the order return
    the positions the affected pages occupy afterwards, so the caller can keep
    them selected.
    """

    def __init__(self) -> None:
        self._pages: tuple[PageRef, ...] = ()
        self._undo: list[tuple[PageRef, ...]] = []
        self._redo: list[tuple[PageRef, ...]] = []

    @property
    def pages(self) -> tuple[PageRef, ...]:
        return self._pages

    def __len__(self) -> int:
        return len(self._pages)

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def _commit(self, pages: tuple[PageRef, ...]) -> None:
        if pages == self._pages:
            return
        self._undo.append(self._pages)
        self._redo.clear()
        self._pages = pages

    def _checked(self, indices: Iterable[int]) -> list[int]:
        chosen = sorted(set(indices))
        for i in chosen:
            if not 0 <= i < len(self._pages):
                raise IndexError(f"page position {i} is outside 0..{len(self._pages) - 1}")
        return chosen

    def insert(self, at: int, refs: Iterable[PageRef]) -> range:
        if not 0 <= at <= len(self._pages):
            raise IndexError(f"insert position {at} is outside 0..{len(self._pages)}")
        new = tuple(refs)
        self._commit(self._pages[:at] + new + self._pages[at:])
        return range(at, at + len(new))

    def append(self, refs: Iterable[PageRef]) -> range:
        return self.insert(len(self._pages), refs)

    def remove(self, indices: Iterable[int]) -> None:
        drop = set(self._checked(indices))
        self._commit(tuple(p for i, p in enumerate(self._pages) if i not in drop))

    def clear(self) -> None:
        self._commit(())

    def move(self, indices: Iterable[int], target: int) -> range:
        """Move pages so they sit together, in their current order, at `target`.

        `target` is a gap position counted in the current list: 0 is before
        the first page, len(self) is after the last.
        """
        chosen = self._checked(indices)
        if not 0 <= target <= len(self._pages):
            raise IndexError(f"move target {target} is outside 0..{len(self._pages)}")
        moving = [self._pages[i] for i in chosen]
        skip = set(chosen)
        keep = [p for i, p in enumerate(self._pages) if i not in skip]
        at = target - sum(1 for i in chosen if i < target)
        self._commit(tuple(keep[:at] + moving + keep[at:]))
        return range(at, at + len(moving))

    def rotate(self, indices: Iterable[int], degrees: int) -> None:
        if degrees % 90:
            raise ValueError(f"rotation must be a multiple of 90 degrees, got {degrees}")
        chosen = set(self._checked(indices))
        self._commit(tuple(
            replace(p, rotation=(p.rotation + degrees) % 360) if i in chosen else p
            for i, p in enumerate(self._pages)
        ))

    def duplicate(self, indices: Iterable[int]) -> range:
        """Insert copies of the pages, as one block, after the last of them."""
        chosen = self._checked(indices)
        if not chosen:
            return range(0)
        return self.insert(chosen[-1] + 1, [self._pages[i] for i in chosen])

    def reverse(self, indices: Iterable[int]) -> None:
        """Reverse the order of the pages among the positions they occupy."""
        chosen = self._checked(indices)
        pages = list(self._pages)
        for slot, page in zip(chosen, reversed([pages[i] for i in chosen]), strict=True):
            pages[slot] = page
        self._commit(tuple(pages))

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._pages)
        self._pages = self._undo.pop()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._pages)
        self._pages = self._redo.pop()
        return True
