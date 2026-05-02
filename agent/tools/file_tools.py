from __future__ import annotations

"""文件工具：限制 Agent 只能读写项目工作区内的文件。"""

import shutil
import subprocess
import tempfile
import re
from pathlib import Path

from langchain_core.tools import tool


TEXT_ENCODINGS = (
    "utf-8",
    "utf-8-sig",
    "gb18030",
    "gbk",
    "cp936",
    "big5",
    "shift_jis",
    "latin-1",
)

LEGACY_OFFICE_SUFFIXES = {".doc", ".ppt", ".xls"}
MODERN_OFFICE_SUFFIXES = {".docx", ".pptx", ".xlsx"}
OLE_TEXT_STREAM_HINTS = ("WordDocument", "PowerPoint Document", "Current User")


def _resolve_inside_workspace(workspace: Path, user_path: str) -> Path:
    """把用户路径解析到工作区内；越界访问会被拒绝。"""
    candidate = Path(user_path)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    resolved = candidate.resolve()
    if workspace not in resolved.parents and resolved != workspace:
        raise ValueError(f"Path escapes workspace: {user_path}")
    return resolved


def _resolve_output_path(workspace: Path, user_path: str) -> Path:
    """解析生成文件路径，并强制要求写入 output 目录。"""
    target = _resolve_inside_workspace(workspace, user_path)
    output_dir = (workspace / "output").resolve()
    if output_dir not in target.parents and target != output_dir:
        raise ValueError(f"Generated files must be written under the output directory: {user_path}")
    return target


def _truncate_text(text: str, max_chars: int) -> str:
    """限制工具返回长度，避免大文件占满上下文。"""
    if len(text) > max_chars:
        return text[:max_chars] + f"\n... truncated, total chars={len(text)}"
    return text


def _read_text_with_fallback(path: Path) -> tuple[str, str]:
    """按常见编码尝试读取文本，兼容 Windows 常见 GBK/GB18030 文件。"""
    data = path.read_bytes()
    last_error: UnicodeDecodeError | None = None
    for encoding in TEXT_ENCODINGS:
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error:
        raise last_error
    return "", "utf-8"


def _resolve_libreoffice_executable(libreoffice_path: Path | None) -> str | None:
    """优先使用 .env 指定的 LibreOffice 文件或目录，否则从 PATH 查找。"""
    if libreoffice_path:
        if libreoffice_path.is_file():
            return str(libreoffice_path)
        if libreoffice_path.is_dir():
            search_dirs = [
                libreoffice_path,
                libreoffice_path / "program",
                libreoffice_path / "Contents" / "MacOS",
            ]
            candidates = (
                "soffice.exe",
                "libreoffice.exe",
                "soffice",
                "libreoffice",
            )
            for directory in search_dirs:
                for name in candidates:
                    executable = directory / name
                    if executable.is_file():
                        return str(executable)
            raise RuntimeError(
                "LIBREOFFICE_PATH points to a directory, but no LibreOffice executable "
                f"was found in it or its program subdirectory: {libreoffice_path}"
            )
        raise RuntimeError(f"LIBREOFFICE_PATH does not exist: {libreoffice_path}")
    return shutil.which("libreoffice") or shutil.which("soffice")


def _convert_office_to_text_with_libreoffice(path: Path, libreoffice_path: Path | None) -> str:
    """优先用 LibreOffice headless 把老式 Office 文件转换为可读取文本。"""
    soffice = _resolve_libreoffice_executable(libreoffice_path)
    if not soffice:
        raise RuntimeError(
            "Reading .doc/.ppt/.xls requires LibreOffice. "
            "Set LIBREOFFICE_PATH in .env or run: python -m agent.command.install_libreoffice"
        )
    with tempfile.TemporaryDirectory(prefix="agent_office_") as temp_dir:
        conversion_errors = []
        for target_format in ("txt", "csv"):
            completed = subprocess.run(
                [soffice, "--headless", "--convert-to", target_format, "--outdir", temp_dir, str(path)],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=120,
                check=False,
            )
            if completed.returncode != 0:
                conversion_errors.append(completed.stderr.strip() or completed.stdout.strip())
                continue
            converted_files = sorted(Path(temp_dir).glob(f"*.{target_format}"))
            if converted_files:
                text, _encoding = _read_text_with_fallback(converted_files[0])
                return text

        error_text = "; ".join(error for error in conversion_errors if error)
        raise RuntimeError(error_text or "LibreOffice did not produce a readable text file")


def _dependency_request_message(module_name: str, package_name: str, reason: str) -> str:
    """返回给 Agent 的缺包提示，要求它记录依赖申请而不是直接安装。"""
    return (
        "DEPENDENCY_INSTALL_REQUEST\n"
        f"missing_module: {module_name}\n"
        f"suggested_package: {package_name}\n"
        f"reason: {reason}\n"
        "Call request_dependency_install with module_name and package_name, then ask the user to approve it."
    )


def _extract_printable_strings(data: bytes) -> list[str]:
    """从 OLE 二进制流中粗略提取可见字符串，作为无 LibreOffice 时的低保真兜底。"""
    chunks: list[str] = []
    for raw in re.findall(rb"(?:[\x20-\x7e]\x00){4,}", data):
        try:
            chunks.append(raw.decode("utf-16le", errors="ignore"))
        except UnicodeDecodeError:
            pass
    for raw in re.findall(rb"[\x20-\x7e]{6,}", data):
        try:
            chunks.append(raw.decode("latin-1", errors="ignore"))
        except UnicodeDecodeError:
            pass

    normalized: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        text = re.sub(r"\s+", " ", chunk).strip()
        if len(text) < 4 or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _read_ole_text_fallback(path: Path) -> str:
    """用 olefile 对 .doc/.ppt 做粗略文本提取；不保证顺序、格式或完整性。"""
    try:
        import olefile
    except ImportError as exc:
        raise RuntimeError(
            _dependency_request_message(
                "olefile",
                "olefile",
                "Python fallback for .doc/.ppt requires olefile when LibreOffice is unavailable.",
            )
        ) from exc

    chunks: list[str] = []
    with olefile.OleFileIO(str(path)) as ole:
        stream_names = ole.listdir(streams=True, storages=False)
        prioritized = [
            parts
            for parts in stream_names
            if any(hint in "/".join(parts) for hint in OLE_TEXT_STREAM_HINTS)
        ]
        remaining = [parts for parts in stream_names if parts not in prioritized]
        for parts in [*prioritized, *remaining]:
            try:
                data = ole.openstream(parts).read()
            except Exception:
                continue
            chunks.extend(_extract_printable_strings(data))

    if not chunks:
        raise RuntimeError(
            "olefile fallback did not extract readable text. Install/configure LibreOffice."
        )
    return (
        "[fallback=olefile coarse text extraction; formatting/order may be incomplete]\n"
        + "\n".join(chunks)
    )


def _read_xls_fallback(path: Path, max_rows: int = 120) -> str:
    """用 xlrd 读取老式 .xls，作为无 LibreOffice 时的表格兜底。"""
    try:
        import xlrd
    except ImportError as exc:
        raise RuntimeError(
            _dependency_request_message(
                "xlrd",
                "xlrd",
                "Python fallback for .xls requires xlrd when LibreOffice is unavailable.",
            )
        ) from exc

    workbook = xlrd.open_workbook(str(path))
    blocks = ["[fallback=xlrd; formulas/formatting may be incomplete]"]
    for sheet in workbook.sheets():
        blocks.append(f"--- Sheet: {sheet.name} | rows={sheet.nrows} | columns={sheet.ncols} ---")
        row_limit = min(sheet.nrows, max_rows)
        for row_index in range(row_limit):
            values = [str(sheet.cell_value(row_index, col_index)) for col_index in range(sheet.ncols)]
            blocks.append(",".join(values))
        if sheet.nrows > row_limit:
            blocks.append(f"... truncated rows, total rows={sheet.nrows}")
    return "\n".join(blocks).strip()


def _read_legacy_office_with_fallback(path: Path, libreoffice_path: Path | None) -> str:
    """优先 LibreOffice；未安装时按格式尝试 Python 低保真 fallback。"""
    try:
        return _convert_office_to_text_with_libreoffice(path, libreoffice_path)
    except RuntimeError as exc:
        message = str(exc)
        libreoffice_unavailable = (
            "requires LibreOffice" in message
            or "LIBREOFFICE_PATH" in message
            or "does not exist" in message
            or "no LibreOffice executable" in message
        )
        if not libreoffice_unavailable:
            raise

    suffix = path.suffix.lower()
    if suffix == ".xls":
        return _read_xls_fallback(path)
    if suffix in {".doc", ".ppt"}:
        return _read_ole_text_fallback(path)
    raise RuntimeError(f"Unsupported legacy Office file type: {path.name}")


def _read_docx_text(path: Path) -> str:
    """读取 .docx 段落和表格文本。"""
    try:
        from docx import Document
    except ImportError as exc:
        raise RuntimeError(_dependency_request_message("docx", "python-docx", ".docx reading requires python-docx.")) from exc

    document = Document(str(path))
    parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
    for table_index, table in enumerate(document.tables, start=1):
        parts.append(f"--- Table {table_index} ---")
        for row in table.rows:
            parts.append(",".join(cell.text.strip() for cell in row.cells))
    return "\n".join(parts).strip()


def _read_pptx_text(path: Path) -> str:
    """读取 .pptx 幻灯片中的文本框内容。"""
    try:
        from pptx import Presentation
    except ImportError as exc:
        raise RuntimeError(_dependency_request_message("pptx", "python-pptx", ".pptx reading requires python-pptx.")) from exc

    presentation = Presentation(str(path))
    parts: list[str] = []
    for slide_index, slide in enumerate(presentation.slides, start=1):
        slide_parts: list[str] = []
        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text.strip():
                slide_parts.append(shape.text.strip())
        if slide_parts:
            parts.append(f"--- Slide {slide_index} ---")
            parts.extend(slide_parts)
    return "\n".join(parts).strip()


def _read_xlsx_text(path: Path, max_rows: int = 120) -> str:
    """读取 .xlsx 工作表数据预览。"""
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise RuntimeError(_dependency_request_message("openpyxl", "openpyxl", ".xlsx reading requires openpyxl.")) from exc

    workbook = load_workbook(str(path), read_only=True, data_only=True)
    blocks: list[str] = []
    for worksheet in workbook.worksheets:
        blocks.append(f"--- Sheet: {worksheet.title} | rows={worksheet.max_row} | columns={worksheet.max_column} ---")
        for row_index, row in enumerate(worksheet.iter_rows(values_only=True), start=1):
            if row_index > max_rows:
                blocks.append(f"... truncated rows, total rows={worksheet.max_row}")
                break
            blocks.append(",".join("" if value is None else str(value) for value in row))
    workbook.close()
    return "\n".join(blocks).strip()


def _read_modern_office_text(path: Path) -> str:
    """按扩展名读取现代 Office Open XML 文件。"""
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return _read_docx_text(path)
    if suffix == ".pptx":
        return _read_pptx_text(path)
    if suffix == ".xlsx":
        return _read_xlsx_text(path)
    raise RuntimeError(f"Unsupported modern Office file type: {path.name}")


def build_file_tools(workspace: Path, libreoffice_path: Path | None = None):
    """构造目录列表、文本读取、PDF/老式 Office 读取和文本写入工具。"""
    workspace = workspace.resolve()

    @tool
    def list_directory(path: str = ".") -> str:
        """List files and directories under a workspace-relative path. Use "." for the project root, not "/"."""
        target = _resolve_inside_workspace(workspace, path)
        if not target.exists():
            return f"Path does not exist: {path}"
        if not target.is_dir():
            return f"Not a directory: {path}"
        entries = []
        for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            kind = "dir" if item.is_dir() else "file"
            entries.append(f"{kind}\t{item.relative_to(workspace)}")
        return "\n".join(entries) or "(empty)"

    @tool
    def read_text_file(path: str, max_chars: int = 12000) -> str:
        """Read a text file from the workspace. Tries UTF-8, GB18030, GBK, Big5 and other common encodings."""
        target = _resolve_inside_workspace(workspace, path)
        if not target.exists():
            return f"File does not exist: {path}"
        if not target.is_file():
            return f"Not a file: {path}"
        suffix = target.suffix.lower()
        if suffix == ".pdf":
            return "PDF files are binary. Use read_pdf_text for .pdf files."
        if suffix in LEGACY_OFFICE_SUFFIXES:
            return "Legacy Office files are binary. Use read_legacy_office_text for .doc/.ppt/.xls files."
        if suffix in MODERN_OFFICE_SUFFIXES:
            return "Modern Office files are zipped XML packages. Use read_modern_office_text for .docx/.pptx/.xlsx files."
        try:
            text, encoding = _read_text_with_fallback(target)
        except UnicodeDecodeError as exc:
            return f"File could not be decoded with common text encodings: {path}. Error: {exc}"
        return f"[encoding={encoding}]\n" + _truncate_text(text, max_chars)

    @tool
    def read_pdf_text(path: str, max_chars: int = 50000) -> str:
        """Extract text from a PDF file in the workspace. Use this for .pdf papers and reports."""
        target = _resolve_inside_workspace(workspace, path)
        if not target.exists():
            return f"File does not exist: {path}"
        if not target.is_file():
            return f"Not a file: {path}"
        if target.suffix.lower() != ".pdf":
            return f"Not a PDF file: {path}"
        try:
            from pypdf import PdfReader
        except ImportError:
            return "PDF reading requires pypdf. Install it with: deps-install pypdf or python -m pip install pypdf"

        try:
            reader = PdfReader(str(target))
            parts = []
            for page_index, page in enumerate(reader.pages, start=1):
                page_text = page.extract_text() or ""
                if page_text.strip():
                    parts.append(f"\n\n--- Page {page_index} ---\n{page_text.strip()}")
            text = "".join(parts).strip()
        except Exception as exc:
            return f"Failed to read PDF: {path}. Error: {exc}"

        if not text:
            return f"No extractable text found in PDF: {path}"
        return _truncate_text(text, max_chars)

    @tool
    def read_legacy_office_text(path: str, max_chars: int = 50000) -> str:
        """Extract text from legacy Office files: .doc, .ppt and .xls."""
        target = _resolve_inside_workspace(workspace, path)
        if not target.exists():
            return f"File does not exist: {path}"
        if not target.is_file():
            return f"Not a file: {path}"
        suffix = target.suffix.lower()
        try:
            if suffix in LEGACY_OFFICE_SUFFIXES:
                text = _read_legacy_office_with_fallback(target, libreoffice_path)
            else:
                return f"Unsupported legacy Office file type: {path}. Supported: .doc, .ppt, .xls"
        except Exception as exc:
            return f"Failed to read legacy Office file: {path}. Error: {exc}"
        if not text.strip():
            return f"No extractable text found in file: {path}"
        return _truncate_text(text.strip(), max_chars)

    @tool
    def read_modern_office_text(path: str, max_chars: int = 50000) -> str:
        """Extract text from modern Office files: .docx, .pptx and .xlsx."""
        target = _resolve_inside_workspace(workspace, path)
        if not target.exists():
            return f"File does not exist: {path}"
        if not target.is_file():
            return f"Not a file: {path}"
        suffix = target.suffix.lower()
        try:
            if suffix in MODERN_OFFICE_SUFFIXES:
                text = _read_modern_office_text(target)
            else:
                return f"Unsupported modern Office file type: {path}. Supported: .docx, .pptx, .xlsx"
        except Exception as exc:
            return f"Failed to read modern Office file: {path}. Error: {exc}"
        if not text.strip():
            return f"No extractable text found in file: {path}"
        return _truncate_text(text.strip(), max_chars)

    @tool
    def write_text_file(path: str, content: str) -> str:
        """Write UTF-8 text content to the output directory. Generated files must be under output."""
        target = _resolve_output_path(workspace, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} chars to {target.relative_to(workspace)}"

    return [list_directory, read_text_file, read_pdf_text, read_legacy_office_text, read_modern_office_text, write_text_file]
