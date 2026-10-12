"""Start the application: python -m pdf_aio [FILE ...]"""

import argparse
from pathlib import Path

from pdf_aio.gui.app import run


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pdf_aio",
        description="PDF 페이지를 이 컴퓨터 안에서 병합, 분할, 정렬, 회전, 변환합니다. "
                    "지정한 파일은 시작할 때 열립니다.",
    )
    parser.add_argument("files", nargs="*", type=Path, metavar="FILE",
                        help="PDF나 이미지 파일, 또는 그런 파일이 든 폴더")
    run(parser.parse_args().files)


if __name__ == "__main__":
    main()
