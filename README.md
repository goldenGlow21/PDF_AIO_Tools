# PDF_AIO_Tools

All in one tools for PDF works: a small Windows application that merges,
splits, reorders, rotates and converts PDF pages on the local machine. It does
what the merge, split and organize pages of online PDF services do, without
uploading anything.

## Run it

Download or build `PDF-AIO-Tools.exe` and double click it. It is a single
file of about 30 MB and needs no installation and no Python. PDF and image
files can be dropped onto the window, or onto the exe icon to open them at
start.

From source, with Python 3.11 or later:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pdf_aio
```

## What it does

The interface is in Korean; the labels below give the English meaning first
and the label on screen in brackets.

All work happens in one workspace: a grid of every page from every file that
was added, in output order. Each source file has its own color under its
thumbnails.

| Task | How |
|---|---|
| Merge PDFs and images | Drop or add files, arrange them, **Save as PDF** [`PDF로 저장`] |
| Change file order | **View by file** [`파일별`] shows one tile per file; drag tiles |
| Reorder pages | Drag pages; select several with Ctrl, Shift or a rectangle |
| Rotate, delete, duplicate | Toolbar, right click menu or keyboard |
| Insert blank pages | **Blank page** [`빈 페이지`] adds one after the selection, sized like the page before it |
| Extract pages | Select them, **Save selected pages only** [`선택한 페이지만 저장`] |
| Split | **Split into files** [`여러 파일로 분할`]: every N pages, by ranges such as `1-3, 4, 5-`, or where the source file changes |
| Images to PDF | Add PNG, JPEG, TIFF, BMP, GIF, JPEG 2000 or PNM files; each image becomes an A4 page |
| PDF to images | **Export as images** [`이미지로 내보내기`] to PNG or JPEG at a chosen dpi |
| Unlock | Open a protected PDF with its password, then save it without one |

Options applied to every saved PDF are in the right hand panel:

- **Page numbers** [`페이지 번호`] at one of six positions, with a format such as `{n} / {total}` and a start number
- **Watermark** [`워터마크`] text, any language including Korean, with size, opacity and angle
- **Compress images** [`이미지 압축`] by downsampling to a maximum dpi and re-encoding as JPEG
- **Password** [`암호`] protection with AES-256

**Preview with options** [`옵션 적용 미리보기`] shows a page exactly as it will be saved.
Undo and redo cover every change to the workspace.

Files dropped between two pages are inserted at that spot. Added files are
sorted by name the way Explorer sorts them, so `scan2` comes before `scan10`.

## Keyboard and mouse

| Key | Action |
|---|---|
| Ctrl+O | Add files |
| Ctrl+S | Save all pages as one PDF |
| Ctrl+Shift+S | Save selected pages as a PDF |
| Ctrl+A | Select all |
| Delete | Delete selected pages |
| Ctrl+D | Duplicate selected pages |
| Ctrl+L, Ctrl+R | Rotate left, right |
| Ctrl+Z, Ctrl+Y | Undo, redo |
| Enter, double click | Preview |
| Ctrl+wheel, Ctrl+plus, Ctrl+minus | Thumbnail size |
| Escape | Cancel a drag in progress |

## Limits

- Bookmarks (the outline) of the source files are not carried into saved files.
  Links between pages survive when those pages stay together.
- No OCR and no conversion to or from Office formats.
- WebP images are not supported, because MuPDF cannot decode them.

## Build the executable

```powershell
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m PyInstaller --noconfirm pdf_aio_tools.spec
```

The result is `dist\PDF-AIO-Tools.exe`. Windows SmartScreen may warn about it
the first time, because the file is not code signed.

## Test and lint

```powershell
.venv\Scripts\python -m unittest discover -s tests -t .
.venv\Scripts\ruff check pdf_aio tests
```

## Layout

```
pdf_aio/
  workspace.py   ordered page references with undo; no PDF access
  splitting.py   page range parsing and split groupings
  library.py     opening PDFs and images into in-memory source documents
  export.py      writing PDFs and images, page numbers, watermark, compression
  gui/           tkinter interface: main window, page grid, dialogs, preview,
                 thumbnail rendering, and Explorer file drop
  assets/        application icon
tests/           unit tests; sample files are generated on the fly
```

## Dependencies and license

The interface uses tkinter from the Python standard library. All PDF work is
done by [PyMuPDF](https://pymupdf.readthedocs.io), which is licensed under the
GNU AGPL 3.0. Distributing the built executable therefore means offering its
source code under AGPL compatible terms; this repository serves that purpose
if it is published under such a license.
