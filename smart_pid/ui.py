from __future__ import annotations

import base64
import html
import io
import json
from pathlib import Path
import zipfile
from xml.sax.saxutils import escape

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from smart_pid.config import AppConfig
from smart_pid.models import PipelineResult


def _image_data_uri(path: Path) -> str:
    data = path.read_bytes()
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def _viewer_html(
    image_path: Path,
    instruments: pd.DataFrame,
    line_tags: pd.DataFrame,
    selected_ids: set[int],
) -> str:
    data_uri = _image_data_uri(image_path)
    instrument_rows = []
    instrument_overlays = []
    for inst in instruments.itertuples(index=False):
        inst_id = int(inst.instrument_id)
        tag = html.escape(str(getattr(inst, "tag_number", "") or "UNTAGGED"))
        typ = html.escape(str(getattr(inst, "instrument_type", "") or "UNKNOWN"))
        target = f"inst-{inst_id}"
        instrument_overlays.append(
            {
                "target": target,
                "x1": float(inst.x1),
                "y1": float(inst.y1),
                "x2": float(inst.x2),
                "y2": float(inst.y2),
                "tag": tag,
                "selected": inst_id in selected_ids,
            }
        )
        selected = " selected" if inst_id in selected_ids else ""
        instrument_rows.append(
            f"<tr data-target='{target}' class='{selected}'><td>{tag}</td><td>{typ}</td></tr>"
        )

    line_rows = []
    line_overlays = []
    if "line_number" not in line_tags and "text" in line_tags:
        line_tags = line_tags.copy()
        line_tags["line_number"] = line_tags["text"]
    if {"line_number", "img_x", "img_y"}.issubset(line_tags.columns):
        for line_index, line in enumerate(line_tags.itertuples(index=False), start=1):
            if pd.isna(getattr(line, "img_x", None)) or pd.isna(getattr(line, "img_y", None)):
                continue
            line_number = html.escape(str(getattr(line, "line_number", "") or "").strip())
            if not line_number:
                continue
            target = f"line-{line_index}"
            x = float(getattr(line, "img_x"))
            y = float(getattr(line, "img_y"))
            line_overlays.append({"target": target, "x": x, "y": y, "line_number": line_number})
            line_rows.append(f"<tr data-target='{target}'><td>{line_number}</td></tr>")

    instrument_payload = json.dumps(instrument_overlays)
    line_payload = json.dumps(line_overlays)
    return f"""
<div class="pid-shell">
  <div class="drawing" id="drawing">
    <div class="viewer-tools">
      <button type="button" id="zoom-out" title="Zoom out">-</button>
      <button type="button" id="zoom-reset" title="Reset view">100%</button>
      <button type="button" id="zoom-in" title="Zoom in">+</button>
    </div>
    <canvas id="pid-canvas"></canvas>
    <svg id="overlay"></svg>
    <img id="pid-img" src="{data_uri}" alt="" />
  </div>
  <div class="side-panel">
    <div class="panel-title">Instruments</div>
    <table>
      <thead><tr><th>Tag</th><th>Type</th></tr></thead>
      <tbody>{''.join(instrument_rows)}</tbody>
    </table>
    <div class="panel-title line-title">Line Numbers</div>
    <table>
      <thead><tr><th>Line Number</th></tr></thead>
      <tbody>{''.join(line_rows)}</tbody>
    </table>
  </div>
</div>
<style>
  .pid-shell {{ display:grid; grid-template-columns:minmax(0, 1fr) 420px; gap:16px; height:760px; min-height:520px; font-family:Inter, Arial, sans-serif; }}
  .drawing {{ position:relative; width:100%; height:100%; min-height:520px; overflow:hidden; background:#fff; border:1px solid #d7dde8; border-radius:8px; cursor:grab; touch-action:none; }}
  .drawing.dragging {{ cursor:grabbing; }}
  #pid-canvas {{ position:absolute; inset:0; width:100%; height:100%; user-select:none; pointer-events:none; }}
  #pid-img {{ display:none; }}
  #overlay {{ position:absolute; inset:0; width:100%; height:100%; pointer-events:none; }}
  .viewer-tools {{ position:absolute; z-index:5; top:10px; left:10px; display:flex; gap:6px; padding:6px; background:rgba(255,255,255,0.92); border:1px solid #d7dde8; border-radius:8px; box-shadow:0 8px 24px rgba(15,23,42,0.12); }}
  .viewer-tools button {{ min-width:36px; height:32px; border:1px solid #cbd5e1; background:#ffffff; color:#0f172a; border-radius:6px; font-weight:700; cursor:pointer; }}
  .viewer-tools button:hover {{ background:#f1f5f9; }}
  .side-panel {{ overflow:auto; border:1px solid #d7dde8; border-radius:8px; background:white; }}
  .panel-title {{ position:sticky; top:0; z-index:2; padding:10px 9px; background:#e2e8f0; color:#0f172a; font-size:13px; font-weight:800; border-bottom:1px solid #cbd5e1; }}
  .line-title {{ top:36px; margin-top:10px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th {{ position:sticky; top:36px; background:#f1f5f9; text-align:left; padding:9px; border-bottom:1px solid #d7dde8; }}
  td {{ padding:8px 9px; border-bottom:1px solid #edf1f7; white-space:nowrap; }}
  tr:hover, tr.active {{ background:#e8f2ff; }}
  tr.selected {{ background:#ecfdf5; }}
  .box {{ fill:rgba(31, 111, 235, 0.08); stroke:#1f6feb; stroke-width:3; vector-effect:non-scaling-stroke; }}
  .box.selected {{ stroke:#0f9f6e; stroke-width:5; }}
  .box.active {{ stroke:#ef4444; stroke-width:6; }}
  .line-marker {{ fill:rgba(250, 204, 21, 0.28); stroke:rgba(202, 138, 4, 0.86); stroke-width:7; vector-effect:non-scaling-stroke; }}
  .line-marker.active {{ fill:rgba(250, 204, 21, 0.52); stroke:#ef4444; stroke-width:12; filter:drop-shadow(0 0 10px rgba(250, 204, 21, 0.95)); animation:lineGlow 0.75s ease-in-out infinite alternate; }}
  @keyframes lineGlow {{ from {{ opacity:0.78; }} to {{ opacity:1; }} }}
  .label {{ font-size:24px; fill:#0f172a; font-weight:700; paint-order:stroke; stroke:#fff; stroke-width:5px; }}
  @media (max-width: 900px) {{ .pid-shell {{ grid-template-columns:1fr; height:auto; }} .drawing {{ height:640px; }} .side-panel {{ max-height:420px; }} }}
</style>
<script>
const instruments = {instrument_payload};
const lineNumbers = {line_payload};
const drawing = document.getElementById('drawing');
const canvas = document.getElementById('pid-canvas');
const ctx = canvas.getContext('2d', {{ alpha: false }});
const img = document.getElementById('pid-img');
const svg = document.getElementById('overlay');
let zoom = 1;
let fitZoom = 1;
let panX = 0;
let panY = 0;
let dragging = false;
let lastX = 0;
let lastY = 0;
let rafId = 0;
let overlayGroup = null;

function scheduleRender() {{
  document.getElementById('zoom-reset').textContent = `${{Math.round(zoom * 100)}}%`;
  if (rafId) return;
  rafId = window.requestAnimationFrame(renderViewport);
}}

function clampZoom(value) {{
  return Math.min(24, Math.max(0.03, value));
}}

function clampPan() {{
  const viewportW = drawing.clientWidth;
  const viewportH = drawing.clientHeight;
  const imageW = img.naturalWidth * zoom;
  const imageH = img.naturalHeight * zoom;
  if (imageW <= viewportW) {{
    panX = (viewportW - imageW) / 2;
  }} else {{
    panX = Math.min(0, Math.max(viewportW - imageW, panX));
  }}
  if (imageH <= viewportH) {{
    panY = (viewportH - imageH) / 2;
  }} else {{
    panY = Math.min(0, Math.max(viewportH - imageH, panY));
  }}
}}

function zoomAt(nextZoom, clientX, clientY) {{
  const rect = drawing.getBoundingClientRect();
  const localX = clientX - rect.left;
  const localY = clientY - rect.top;
  const contentX = (localX - panX) / zoom;
  const contentY = (localY - panY) / zoom;
  zoom = clampZoom(nextZoom);
  panX = localX - contentX * zoom;
  panY = localY - contentY * zoom;
  clampPan();
  scheduleRender();
}}

function zoomCenter(factor) {{
  const rect = drawing.getBoundingClientRect();
  zoomAt(zoom * factor, rect.left + rect.width / 2, rect.top + rect.height / 2);
}}

function resetView() {{
  zoom = fitZoom;
  panX = 0;
  panY = 0;
  clampPan();
  scheduleRender();
}}

function buildOverlay() {{
  const w = img.naturalWidth, h = img.naturalHeight;
  svg.setAttribute('viewBox', `0 0 ${{drawing.clientWidth}} ${{drawing.clientHeight}}`);
  svg.innerHTML = '';
  overlayGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  svg.appendChild(overlayGroup);
  lineNumbers.forEach(d => {{
    const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    circle.setAttribute('cx', d.x); circle.setAttribute('cy', d.y); circle.setAttribute('r', 52);
    circle.setAttribute('class', 'line-marker');
    circle.dataset.target = d.target;
    overlayGroup.appendChild(circle);
  }});
  instruments.forEach(d => {{
    const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    rect.setAttribute('x', d.x1); rect.setAttribute('y', d.y1);
    rect.setAttribute('width', d.x2 - d.x1); rect.setAttribute('height', d.y2 - d.y1);
    rect.setAttribute('class', 'box' + (d.selected ? ' selected' : ''));
    rect.dataset.target = d.target;
    overlayGroup.appendChild(rect);
    const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    text.setAttribute('x', d.x1); text.setAttribute('y', Math.max(26, d.y1 - 8));
    text.setAttribute('class', 'label'); text.textContent = d.tag;
    overlayGroup.appendChild(text);
  }});
}}

function renderViewport() {{
  rafId = 0;
  const cssW = drawing.clientWidth;
  const cssH = drawing.clientHeight;
  const dpr = window.devicePixelRatio || 1;
  const pixelW = Math.max(1, Math.round(cssW * dpr));
  const pixelH = Math.max(1, Math.round(cssH * dpr));
  if (canvas.width !== pixelW || canvas.height !== pixelH) {{
    canvas.width = pixelW;
    canvas.height = pixelH;
  }}
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(img, panX, panY, img.naturalWidth * zoom, img.naturalHeight * zoom);
  svg.setAttribute('viewBox', `0 0 ${{cssW}} ${{cssH}}`);
  if (overlayGroup) {{
    overlayGroup.setAttribute('transform', `translate(${{panX}} ${{panY}}) scale(${{zoom}})`);
  }}
}}

function draw() {{
  const w = img.naturalWidth, h = img.naturalHeight;
  if (!w || !h) return;
  if (!drawing.clientWidth || !drawing.clientHeight) {{
    window.setTimeout(draw, 50);
    return;
  }}
  fitZoom = Math.min(1, drawing.clientWidth / w, drawing.clientHeight / h);
  if (!drawing.dataset.ready) {{
    zoom = fitZoom;
    drawing.dataset.ready = '1';
  }}
  buildOverlay();
  clampPan();
  scheduleRender();
}}
function setActive(id, on) {{
  document.querySelectorAll(`[data-target="${{id}}"]`).forEach(el => el.classList.toggle('active', on));
}}

drawing.addEventListener('wheel', event => {{
  event.preventDefault();
  const factor = event.deltaY < 0 ? 1.15 : 1 / 1.15;
  zoomAt(zoom * factor, event.clientX, event.clientY);
}}, {{ passive:false }});

drawing.addEventListener('pointerdown', event => {{
  if (event.target.closest('.viewer-tools')) return;
  dragging = true;
  lastX = event.clientX;
  lastY = event.clientY;
  drawing.classList.add('dragging');
  drawing.setPointerCapture(event.pointerId);
}});

drawing.addEventListener('pointermove', event => {{
  if (!dragging) return;
  panX += event.clientX - lastX;
  panY += event.clientY - lastY;
  lastX = event.clientX;
  lastY = event.clientY;
  clampPan();
  scheduleRender();
}});

function endDrag(event) {{
  dragging = false;
  drawing.classList.remove('dragging');
  if (event.pointerId !== undefined && drawing.hasPointerCapture(event.pointerId)) {{
    drawing.releasePointerCapture(event.pointerId);
  }}
}}

drawing.addEventListener('pointerup', endDrag);
drawing.addEventListener('pointercancel', endDrag);
document.getElementById('zoom-out').addEventListener('click', () => zoomCenter(1 / 1.2));
document.getElementById('zoom-in').addEventListener('click', () => zoomCenter(1.2));
document.getElementById('zoom-reset').addEventListener('click', resetView);
document.querySelectorAll('tbody tr[data-target]').forEach(row => {{
  row.addEventListener('mouseenter', () => setActive(row.dataset.target, true));
  row.addEventListener('mouseleave', () => setActive(row.dataset.target, false));
}});
window.addEventListener('resize', () => {{
  clampPan();
  buildOverlay();
  scheduleRender();
}});
if (img.complete) draw(); else img.onload = draw;
</script>
"""


def _selection_rows(event: object) -> list[int]:
    if event is None:
        return []
    selection = getattr(event, "selection", None)
    if selection is None and isinstance(event, dict):
        selection = event.get("selection")
    if selection is None:
        return []
    rows = getattr(selection, "rows", None)
    if rows is None and isinstance(selection, dict):
        rows = selection.get("rows")
    return list(rows or [])


def _excel_bytes(register: pd.DataFrame) -> bytes:
    def col_name(index: int) -> str:
        name = ""
        while index:
            index, remainder = divmod(index - 1, 26)
            name = chr(65 + remainder) + name
        return name

    def cell_xml(row_num: int, col_num: int, value: object) -> str:
        ref = f"{col_name(col_num)}{row_num}"
        style = ' s="1"' if row_num == 1 else ""
        if pd.isna(value):
            return f'<c r="{ref}"{style}/>'
        if isinstance(value, bool):
            return f'<c r="{ref}"{style} t="b"><v>{int(value)}</v></c>'
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return f'<c r="{ref}"{style}><v>{value}</v></c>'
        text = escape(str(value))
        return f'<c r="{ref}"{style} t="inlineStr"><is><t>{text}</t></is></c>'

    rows = []
    values = [list(register.columns)] + register.fillna("").values.tolist()
    for row_num, row_values in enumerate(values, start=1):
        cells = "".join(cell_xml(row_num, col_num, value) for col_num, value in enumerate(row_values, start=1))
        rows.append(f'<row r="{row_num}">{cells}</row>')

    cols = []
    for col_num, column in enumerate(register.columns, start=1):
        text_lengths = [len(str(column))]
        if column in register:
            text_lengths.extend(len("" if pd.isna(value) else str(value)) for value in register[column])
        width = max(10, min(max(text_lengths) + 3, 60))
        cols.append(f'<col min="{col_num}" max="{col_num}" width="{width}" customWidth="1"/>')

    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<cols>{''.join(cols)}</cols>"
        f"<sheetData>{''.join(rows)}</sheetData>"
        "</worksheet>"
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Instrument Register" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
        "</Relationships>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        "</Types>"
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2">'
        '<font><sz val="11"/><color theme="1"/><name val="Calibri"/><family val="2"/></font>'
        '<font><b/><sz val="11"/><color theme="1"/><name val="Calibri"/><family val="2"/></font>'
        '</fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="2">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
        '</cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        '</styleSheet>'
    )

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/styles.xml", styles_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return output.getvalue()


def render_app(result: PipelineResult, config: AppConfig) -> None:
    instruments = result.instruments.copy()
    if "instrument_type" not in instruments:
        instruments["instrument_type"] = "UNKNOWN"
    if "tag_number" not in instruments:
        instruments["tag_number"] = ""

    st.sidebar.success(f"Cache key: {result.pdf_hash}")
    page = st.sidebar.selectbox("Page", sorted(result.page_images.keys()))
    page_df = instruments[instruments["page"] == page].copy()

    types = sorted(t for t in page_df["instrument_type"].dropna().unique())
    type_filter_key = f"instrument_type_filter:{result.pdf_hash}:{page}"
    if type_filter_key not in st.session_state:
        st.session_state[type_filter_key] = types
    else:
        st.session_state[type_filter_key] = [t for t in st.session_state[type_filter_key] if t in types]

    with st.sidebar.form(f"instrument_type_form_{result.pdf_hash}_{page}"):
        pending_types = st.multiselect(
            "Instrument type",
            types,
            default=st.session_state[type_filter_key],
            key=f"{type_filter_key}:pending",
        )
        show_types = st.form_submit_button("Show", use_container_width=True)
    if show_types:
        st.session_state[type_filter_key] = pending_types

    selected_types = st.session_state[type_filter_key]
    filtered = page_df[page_df["instrument_type"].isin(selected_types)] if selected_types else page_df.iloc[0:0]

    counts = page_df["instrument_type"].value_counts().rename_axis("type").reset_index(name="count")
    c1, c2 = st.columns([0.28, 0.72])
    with c1:
        st.subheader("Instrument Counts")
        st.dataframe(counts, hide_index=True, use_container_width=True)
    with c2:
        st.subheader("Detected Instruments")
        display_cols = [
            "instrument_id",
            "tag_number",
            "instrument_type",
            "confidence",
        ]
        available = [col for col in display_cols if col in filtered.columns]
        register = filtered[available].reset_index(drop=True)
        if "instrument_id" in register:
            register["instrument_id"] = register["instrument_id"].astype(int) + 1
        st.dataframe(
            register,
            hide_index=True,
            use_container_width=True,
            height=220,
            column_config={
                "instrument_id": st.column_config.NumberColumn("ID"),
                "tag_number": st.column_config.TextColumn("Tag Number"),
                "instrument_type": st.column_config.TextColumn("Instrument Type"),
                "confidence": st.column_config.NumberColumn("Confidence", format="%.3f"),
            },
        )
        st.download_button(
            "Download Instrument Excel",
            data=_excel_bytes(register),
            file_name=f"instrument_register_{result.pdf_hash}_page_{page}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    line_tags = result.line_tags.copy()
    if "line_number" not in line_tags and "text" in line_tags:
        line_tags["line_number"] = line_tags["text"]
    if line_tags.empty or "line_number" not in line_tags:
        line_list = pd.DataFrame(columns=["line_number", "pages", "count"])
    else:
        line_tags["line_number"] = line_tags["line_number"].astype(str).str.strip()
        line_tags = line_tags[line_tags["line_number"] != ""]
        line_list = line_tags.groupby("line_number", as_index=False).agg(
            pages=("page", lambda values: ", ".join(str(page_no) for page_no in sorted(set(values)))),
            count=("line_number", "size"),
        )
        line_list = line_list.sort_values("line_number").reset_index(drop=True)

    with st.expander("Line List", expanded=True):
        st.download_button(
            "Download Line List Excel",
            data=_excel_bytes(line_list),
            file_name=f"line_list_{result.pdf_hash}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
        line_table_height = max(120, 38 + (len(line_list) + 1) * 35)
        st.dataframe(
            line_list,
            hide_index=True,
            use_container_width=True,
            height=line_table_height,
            column_config={
                "line_number": st.column_config.TextColumn("Line Number"),
                "pages": st.column_config.TextColumn("Pages"),
                "count": st.column_config.NumberColumn("Occurrences"),
            },
        )

    tag_labels = {
        int(r.instrument_id): f"{r.tag_number or 'UNTAGGED'} | {r.instrument_type}"
        for r in filtered.itertuples(index=False)
    }
    highlight_key = f"highlight_instruments:{result.pdf_hash}:{page}"
    if highlight_key not in st.session_state:
        st.session_state[highlight_key] = []
    else:
        st.session_state[highlight_key] = [
            inst_id for inst_id in st.session_state[highlight_key] if inst_id in tag_labels
        ]

    with st.sidebar.form(f"highlight_instruments_form_{result.pdf_hash}_{page}"):
        pending_highlights = st.multiselect(
            "Highlight instruments",
            list(tag_labels),
            default=st.session_state[highlight_key],
            format_func=lambda inst_id: tag_labels.get(inst_id, str(inst_id)),
            key=f"{highlight_key}:pending",
        )
        apply_highlights = st.form_submit_button("Highlight", use_container_width=True)
    if apply_highlights:
        st.session_state[highlight_key] = pending_highlights

    selected_ids = set(st.session_state[highlight_key])

    st.subheader("P&ID Viewer")
    page_line_tags = result.line_tags[result.line_tags["page"] == page].copy() if "page" in result.line_tags else result.line_tags
    components.html(
        _viewer_html(result.page_images[page], filtered, page_line_tags, selected_ids),
        height=800,
        scrolling=True,
    )
