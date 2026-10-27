"""Xuất thời khóa biểu đã lưu thành workbook Excel ``.xlsx``.

Workbook được tạo trực tiếp theo chuẩn Office Open XML bằng thư viện chuẩn
Python. Cách này giữ runtime thuần Python và tránh buộc tầng ứng dụng phụ thuộc
vào Microsoft Excel. Dữ liệu nguồn vẫn đi qua ``TimetableQueryService`` nên
CSV, Excel và API dùng cùng một hợp đồng lịch đã kiểm tra.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

from .timetable_export import LOCATION_TYPE_LABELS, PART_TYPE_LABELS
from .timetable_query import (
    TimetableQueryFilters,
    TimetableQueryService,
    TimetableScheduleRow,
)


_MAIN_HEADERS = (
    "Mã học kỳ",
    "Tên học kỳ",
    "Mã lớp học phần",
    "Tên lớp học phần",
    "Mã môn học",
    "Tên môn học",
    "Mã phần giảng dạy",
    "Hình thức",
    "Nhóm buổi cố định",
    "Thứ",
    "Tiết bắt đầu",
    "Tiết kết thúc",
    "Mã địa điểm",
    "Tên địa điểm",
    "Loại địa điểm",
    "Mã giảng viên",
    "Tên giảng viên",
    "Tuần hoạt động",
)

_COLUMN_WIDTHS = (
    15, 30, 18, 22, 15, 28, 21, 14, 19,
    13, 13, 13, 16, 24, 16, 17, 24, 24,
)


@dataclass(frozen=True, slots=True)
class TimetableExcelExportResult:
    """Thông tin workbook đã tạo thành công."""

    output_path: Path
    row_count: int


class TimetableExcelExportService:
    """Xuất lịch của một run hoàn thành thành workbook hai worksheet."""

    def __init__(self, query_service: TimetableQueryService) -> None:
        if not isinstance(query_service, TimetableQueryService):
            raise TypeError("query_service phải là TimetableQueryService.")
        self._query_service = query_service

    def export_run_xlsx(
        self,
        run_id: int,
        output_path: str | os.PathLike[str],
        filters: TimetableQueryFilters | None = None,
    ) -> TimetableExcelExportResult:
        """Đọc lịch, tạo workbook và thay thế tệp đích theo cách nguyên tử."""

        destination = _validate_xlsx_path(output_path)
        rows = self._query_service.get_run_schedule(run_id, filters)
        destination.parent.mkdir(parents=True, exist_ok=True)

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.stem}.",
            suffix=".tmp",
            dir=destination.parent,
        )
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        try:
            _write_xlsx_package(
                temporary_path,
                run_id=run_id,
                rows=rows,
                filters=filters or TimetableQueryFilters(),
                exported_at=datetime.now(timezone.utc),
            )
            os.replace(temporary_path, destination)
        finally:
            temporary_path.unlink(missing_ok=True)

        return TimetableExcelExportResult(destination.resolve(), len(rows))


def _validate_xlsx_path(output_path: str | os.PathLike[str]) -> Path:
    if not isinstance(output_path, (str, os.PathLike)):
        raise TypeError("output_path phải là chuỗi hoặc đối tượng đường dẫn.")
    path = Path(output_path)
    if path.suffix.lower() != ".xlsx":
        raise ValueError("output_path phải có phần mở rộng .xlsx.")
    return path


def _write_xlsx_package(
    path: Path,
    *,
    run_id: int,
    rows: tuple[TimetableScheduleRow, ...],
    filters: TimetableQueryFilters,
    exported_at: datetime,
) -> None:
    """Ghi gói OOXML tối thiểu nhưng đầy đủ cho Excel/LibreOffice."""

    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _content_types_xml())
        archive.writestr("_rels/.rels", _root_relationships_xml())
        archive.writestr("docProps/app.xml", _app_properties_xml())
        archive.writestr(
            "docProps/core.xml",
            _core_properties_xml(exported_at),
        )
        archive.writestr("xl/workbook.xml", _workbook_xml())
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            _workbook_relationships_xml(),
        )
        archive.writestr("xl/styles.xml", _styles_xml())
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            _schedule_sheet_xml(run_id, rows),
        )
        archive.writestr(
            "xl/worksheets/sheet2.xml",
            _information_sheet_xml(run_id, rows, filters, exported_at),
        )


def _schedule_sheet_xml(
    run_id: int,
    rows: tuple[TimetableScheduleRow, ...],
) -> bytes:
    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    ET.register_namespace("", namespace)
    worksheet = ET.Element(f"{{{namespace}}}worksheet")
    ET.SubElement(worksheet, f"{{{namespace}}}sheetViews")
    sheet_views = worksheet.find(f"{{{namespace}}}sheetViews")
    sheet_view = ET.SubElement(sheet_views, f"{{{namespace}}}sheetView", workbookViewId="0")
    ET.SubElement(
        sheet_view,
        f"{{{namespace}}}pane",
        ySplit="4",
        topLeftCell="A5",
        activePane="bottomLeft",
        state="frozen",
    )
    columns = ET.SubElement(worksheet, f"{{{namespace}}}cols")
    for index, width in enumerate(_COLUMN_WIDTHS, start=1):
        ET.SubElement(
            columns,
            f"{{{namespace}}}col",
            min=str(index),
            max=str(index),
            width=str(width),
            customWidth="1",
        )

    sheet_data = ET.SubElement(worksheet, f"{{{namespace}}}sheetData")
    title_row = ET.SubElement(sheet_data, f"{{{namespace}}}row", r="1", ht="26", customHeight="1")
    _append_text_cell(title_row, "A1", "THỜI KHÓA BIỂU", style=1)

    metadata_row = ET.SubElement(sheet_data, f"{{{namespace}}}row", r="2")
    _append_text_cell(metadata_row, "A2", "Run ID", style=4)
    _append_number_cell(metadata_row, "B2", run_id, style=3)
    _append_text_cell(metadata_row, "D2", "Học kỳ", style=4)
    term_text = rows[0].term_name if rows else "Không có dòng phù hợp bộ lọc"
    _append_text_cell(metadata_row, "E2", term_text, style=4)

    header_row = ET.SubElement(sheet_data, f"{{{namespace}}}row", r="4", ht="30", customHeight="1")
    for column_index, header in enumerate(_MAIN_HEADERS, start=1):
        _append_text_cell(header_row, _cell_reference(column_index, 4), header, style=2)

    for row_index, item in enumerate(rows, start=5):
        xml_row = ET.SubElement(sheet_data, f"{{{namespace}}}row", r=str(row_index))
        values: tuple[object, ...] = (
            item.term_code,
            item.term_name,
            item.section_code,
            item.section_name or "",
            item.course_code,
            item.course_name,
            item.part_code,
            PART_TYPE_LABELS.get(item.part_type, item.part_type),
            item.stability_group_no,
            item.weekday_name,
            item.start_period,
            item.end_period,
            item.location_code,
            item.location_name,
            LOCATION_TYPE_LABELS.get(item.location_type, item.location_type),
            item.lecturer_code,
            item.lecturer_name,
            ", ".join(map(str, item.active_week_numbers)),
        )
        for column_index, value in enumerate(values, start=1):
            reference = _cell_reference(column_index, row_index)
            if isinstance(value, int):
                _append_number_cell(xml_row, reference, value, style=3)
            else:
                _append_text_cell(xml_row, reference, str(value), style=4)

    last_row = max(4, 4 + len(rows))
    ET.SubElement(
        worksheet,
        f"{{{namespace}}}autoFilter",
        ref=f"A4:R{last_row}",
    )
    ET.SubElement(worksheet, f"{{{namespace}}}mergeCells", count="1")
    merge_cells = worksheet.find(f"{{{namespace}}}mergeCells")
    ET.SubElement(merge_cells, f"{{{namespace}}}mergeCell", ref="A1:R1")
    ET.SubElement(
        worksheet,
        f"{{{namespace}}}pageMargins",
        left="0.3",
        right="0.3",
        top="0.5",
        bottom="0.5",
        header="0.2",
        footer="0.2",
    )
    return ET.tostring(worksheet, encoding="utf-8", xml_declaration=True)


def _information_sheet_xml(
    run_id: int,
    rows: tuple[TimetableScheduleRow, ...],
    filters: TimetableQueryFilters,
    exported_at: datetime,
) -> bytes:
    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    ET.register_namespace("", namespace)
    worksheet = ET.Element(f"{{{namespace}}}worksheet")
    columns = ET.SubElement(worksheet, f"{{{namespace}}}cols")
    for index, width in enumerate((26, 50), start=1):
        ET.SubElement(
            columns,
            f"{{{namespace}}}col",
            min=str(index),
            max=str(index),
            width=str(width),
            customWidth="1",
        )
    sheet_data = ET.SubElement(worksheet, f"{{{namespace}}}sheetData")
    values = (
        ("THÔNG TIN XUẤT LỊCH", ""),
        ("Run ID", run_id),
        ("Số dòng", len(rows)),
        ("Thời điểm xuất UTC", exported_at.isoformat(timespec="seconds")),
        ("Mã học kỳ", filters.term_code or "Tất cả trong run"),
        ("Mã giảng viên", filters.lecturer_code or "Tất cả"),
        ("Mã lớp học phần", filters.section_code or "Tất cả"),
        ("Tuần", filters.week_number or "Tất cả"),
        ("Ghi chú", "Mỗi dòng biểu diễn một mẫu lịch lặp và các tuần hoạt động."),
    )
    for row_index, (label, value) in enumerate(values, start=1):
        xml_row = ET.SubElement(sheet_data, f"{{{namespace}}}row", r=str(row_index))
        style = 1 if row_index == 1 else 4
        _append_text_cell(xml_row, f"A{row_index}", label, style=style)
        if isinstance(value, int):
            _append_number_cell(xml_row, f"B{row_index}", value, style=3)
        else:
            _append_text_cell(xml_row, f"B{row_index}", str(value), style=4)
    merge_cells = ET.SubElement(worksheet, f"{{{namespace}}}mergeCells", count="1")
    ET.SubElement(merge_cells, f"{{{namespace}}}mergeCell", ref="A1:B1")
    return ET.tostring(worksheet, encoding="utf-8", xml_declaration=True)


def _append_text_cell(parent: ET.Element, reference: str, value: str, *, style: int) -> None:
    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    cell = ET.SubElement(
        parent,
        f"{{{namespace}}}c",
        r=reference,
        s=str(style),
        t="inlineStr",
    )
    inline = ET.SubElement(cell, f"{{{namespace}}}is")
    text = ET.SubElement(inline, f"{{{namespace}}}t")
    if value != value.strip():
        text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    text.text = value


def _append_number_cell(parent: ET.Element, reference: str, value: int, *, style: int) -> None:
    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    cell = ET.SubElement(parent, f"{{{namespace}}}c", r=reference, s=str(style))
    ET.SubElement(cell, f"{{{namespace}}}v").text = str(value)


def _cell_reference(column_index: int, row_index: int) -> str:
    letters = ""
    remaining = column_index
    while remaining:
        remaining, remainder = divmod(remaining - 1, 26)
        letters = chr(65 + remainder) + letters
    return f"{letters}{row_index}"


def _content_types_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>"""


def _root_relationships_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>"""


def _workbook_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Thời khóa biểu" sheetId="1" r:id="rId1"/>
    <sheet name="Thông tin xuất" sheetId="2" r:id="rId2"/>
  </sheets>
  <calcPr calcId="0"/>
</workbook>"""


def _workbook_relationships_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""


def _styles_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="3">
    <font><sz val="11"/><name val="Arial"/></font>
    <font><b/><sz val="16"/><color rgb="FF17324D"/><name val="Arial"/></font>
    <font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="Arial"/></font>
  </fonts>
  <fills count="3">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF0F766E"/><bgColor indexed="64"/></patternFill></fill>
  </fills>
  <borders count="2">
    <border><left/><right/><top/><bottom/><diagonal/></border>
    <border><left style="thin"><color rgb="FFD9E1E8"/></left><right style="thin"><color rgb="FFD9E1E8"/></right><top style="thin"><color rgb="FFD9E1E8"/></top><bottom style="thin"><color rgb="FFD9E1E8"/></bottom><diagonal/></border>
  </borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="5">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment horizontal="left" vertical="center"/></xf>
    <xf numFmtId="0" fontId="2" fillId="2" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="left" vertical="center" wrapText="1"/></xf>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""


def _core_properties_xml(exported_at: datetime) -> str:
    timestamp = exported_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:creator>GA-PO Timetabling</dc:creator>
  <cp:lastModifiedBy>GA-PO Timetabling</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{timestamp}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{timestamp}</dcterms:modified>
</cp:coreProperties>"""


def _app_properties_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>GA-PO Timetabling</Application>
</Properties>"""
