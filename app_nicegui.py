# -*- coding: utf-8 -*-
"""냉동창고 레이아웃 시각화 - NiceGUI 버전.

Streamlit 버전과 달리 격자를 '네이티브 클릭 가능 셀'로 그려서,
칸을 클릭하면 우측 상세 패널에 로트(유통기한별) 내역이 뜬다.
(= 창고 도면 비전으로 갈 때 NiceGUI의 장점 데모)

실행:  python app_nicegui.py   ->  http://localhost:8080
"""
import os

import pandas as pd
from nicegui import ui

import warehouse as wh

def _data_path():
    here = os.path.dirname(__file__)
    for fn in ("sample_inventory.csv", "example_inventory.csv"):
        p = os.path.join(here, fn)
        if os.path.exists(p):
            return p
    raise FileNotFoundError("sample_inventory.csv / example_inventory.csv 둘 다 없음")


SAMPLE = _data_path()

state = {"df": None, "mode": "유통기한", "racks": [], "cats": [], "dday_max": 365,
         "reverse_bays": True, "selected": None}


def load_sample():
    state["df"] = wh.load_dataframe(pd.read_csv(SAMPLE, encoding="utf-8-sig"))


def all_cells():
    return wh.aggregate(state["df"]) if state["df"] is not None else {}


def current_cells():
    return {
        loc: c for loc, c in all_cells().items()
        if (not state["racks"] or c.rack in state["racks"])
        and (not state["cats"] or c.category in state["cats"])
        and (c.dday is None or c.dday <= state["dday_max"] if state["mode"] == "유통기한" else True)
    }


# --------------------------------------------------------------------------
# 상세 패널 (우측 드로어) - 클릭한 칸의 로트 내역
# --------------------------------------------------------------------------
@ui.refreshable
def detail():
    loc = state["selected"]
    cells = all_cells()
    c = cells.get(loc) if loc else None
    if c is None:
        ui.label("칸을 클릭하면 상세가 표시됩니다.").classes("text-gray-500")
        return
    ui.label(c.location).classes("text-xl font-bold")
    ui.label(f"랙 {c.rack} · 베이 {c.bay:02d} · {c.tier}단").classes("text-sm text-gray-500")
    with ui.row().classes("gap-6 my-2"):
        for lab, val in [("총 재고", f"{c.total_qty:,}"),
                         ("로트 수", f"{len(c.lots)}"),
                         ("품목군", c.category)]:
            with ui.column().classes("items-center"):
                ui.label(val).classes("text-lg font-bold")
                ui.label(lab).classes("text-xs text-gray-500")
    if c.dday is not None:
        color = "negative" if c.dday <= 30 else ("warning" if c.dday <= 120 else "positive")
        ui.badge(f"최임박 D{c.dday:+d}", color=color).classes("text-sm")
    ui.separator().classes("my-2")
    ui.table(
        columns=[
            {"name": "name", "label": "품목", "field": "name", "align": "left"},
            {"name": "expiry", "label": "유통기한", "field": "expiry", "align": "center"},
            {"name": "qty", "label": "수량", "field": "qty", "align": "right"},
        ],
        rows=[{"name": l["name"], "expiry": l["expiry"], "qty": f"{l['qty']:,}"} for l in c.lots],
    ).classes("w-full")


def select_cell(loc: str):
    state["selected"] = loc
    detail.refresh()
    right.show()


# --------------------------------------------------------------------------
# 네이티브 격자 (클릭 가능)
# --------------------------------------------------------------------------
def make_cell(loc, cell, qmax):
    bg = wh.cell_color(cell, state["mode"], qmax)
    fg = wh.text_on(bg)
    sel = (state["selected"] == loc)
    border = "2px solid #111" if sel else "1px solid #ccc"
    el = ui.element("div").style(
        f"width:84px;height:64px;background:{bg};color:{fg};border:{border};"
        "border-radius:4px;padding:3px;font-size:10px;line-height:1.2;overflow:hidden;"
        + ("cursor:pointer" if cell is not None else "")
    )
    with el:
        if cell is None:
            ui.label("·").classes("text-gray-300")
        else:
            ui.label(wh._short(cell.main_name)).style("font-weight:600")
            ui.label(f"{cell.total_qty:,}개")
            if cell.dday is not None:
                ui.label(f"D{cell.dday:+d}").style("opacity:.85")
    if cell is not None:
        el.on("click", lambda l=loc: select_cell(l))


@ui.refreshable
def grid():
    cells = current_cells()
    if not cells:
        ui.label("표시할 데이터가 없습니다. (사이드바에서 데이터 적재)").classes("text-gray-500")
        return
    qmax = max((c.total_qty for c in cells.values()), default=1)
    racks = sorted({c.rack for c in cells.values()})
    for rack in racks:
        rcells = {loc: c for loc, c in cells.items() if c.rack == rack}
        max_bay = max(c.bay for c in rcells.values())
        bays = list(range(1, max_bay + 1))
        if state["reverse_bays"]:
            bays = bays[::-1]
        ui.label(f"랙 {rack}").classes("font-bold text-base mt-3")
        with ui.column().classes("gap-1"):
            with ui.row().classes("gap-1 no-wrap items-center"):
                ui.label("").style("width:28px")
                for b in bays:
                    ui.label(f"{b:02d}").classes("text-xs text-gray-400").style("width:84px;text-align:center")
            for t in [4, 3, 2, 1]:
                with ui.row().classes("gap-1 no-wrap items-center"):
                    ui.label(f"{t}단").classes("text-xs text-gray-400").style("width:28px")
                    for b in bays:
                        loc = f"{rack}-{b:02d}-{t:02d}"
                        make_cell(loc, rcells.get(loc), qmax)


@ui.refreshable
def metrics():
    cells = current_cells()
    total = sum(c.total_qty for c in cells.values())
    soon = sum(1 for c in cells.values() if c.dday is not None and c.dday <= 30)
    expired = sum(1 for c in cells.values() if c.dday is not None and c.dday < 0)
    with ui.row().classes("gap-8"):
        for label, val in [("점유 로케이션", f"{len(cells):,}"), ("총 재고", f"{total:,}"),
                           ("임박(≤30일)", f"{soon:,}"), ("기한 경과", f"{expired:,}")]:
            with ui.column().classes("items-center"):
                ui.label(val).classes("text-2xl font-bold")
                ui.label(label).classes("text-xs text-gray-500")


def refresh_all():
    metrics.refresh()
    grid.refresh()
    legend.refresh()


@ui.refreshable
def legend():
    ui.html(wh._legend_html(state["mode"],
                            max((c.total_qty for c in current_cells().values()), default=1)))


def rebuild_filters():
    cells = all_cells()
    state["racks"] = sorted({c.rack for c in cells.values()})
    state["cats"] = sorted({c.category for c in cells.values()})
    rack_select.options = state["racks"]; rack_select.value = state["racks"]; rack_select.update()
    cat_select.options = state["cats"]; cat_select.value = state["cats"]; cat_select.update()
    refresh_all()


# --------------------------------------------------------------------------
# UI 구성
# --------------------------------------------------------------------------
ui.label("❄️ 냉동창고 레이아웃 / 재고 · 유통기한").classes("text-2xl font-bold q-mb-md")

right = ui.right_drawer(value=False).props("width=380").classes("bg-grey-1")
with right:
    ui.label("로케이션 상세").classes("font-bold text-sm text-gray-500")
    detail()

with ui.left_drawer().props("width=300"):
    ui.label("데이터").classes("font-bold")

    def on_source(e):
        if e.value == "샘플 데이터":
            load_sample(); rebuild_filters()
        elif e.value == "사방넷 자동 수집":
            try:
                state["df"] = wh.load_dataframe(wh.fetch_from_sabang()); rebuild_filters()
            except NotImplementedError as ex:
                ui.notify(str(ex), type="warning", multi_line=True)

    ui.radio(["샘플 데이터", "수동 업로드", "사방넷 자동 수집"], value="샘플 데이터", on_change=on_source)

    async def on_upload(e):
        state["df"] = wh.read_uploaded(e.content.read(), e.name)
        rebuild_filters()
        ui.notify(f"{e.name} 적재 완료", type="positive")

    ui.upload(on_upload=on_upload, label="수동 업로드 (csv/xlsx)").props("accept=.csv,.xlsx,.xls").classes("w-full")

    ui.separator()
    ui.label("보기").classes("font-bold")

    def set_mode(e):
        state["mode"] = e.value; refresh_all()

    ui.radio(["품목", "재고수량", "유통기한"], value=state["mode"], on_change=set_mode)

    def set_racks(e):
        state["racks"] = e.value; refresh_all()

    rack_select = ui.select([], multiple=True, label="랙 필터", on_change=set_racks).props("use-chips").classes("w-full")

    def set_cats(e):
        state["cats"] = e.value; refresh_all()

    cat_select = ui.select([], multiple=True, label="품목군 필터", on_change=set_cats).props("use-chips").classes("w-full")

    def set_dday(e):
        state["dday_max"] = e.value; refresh_all()

    ui.label("유통기한 D-day 이하 강조")
    ui.slider(min=-30, max=365, step=10, value=365, on_change=set_dday).props("label-always")

    def set_rev(e):
        state["reverse_bays"] = e.value; refresh_all()

    ui.switch("베이 좌우반전 (01번 오른쪽 = 시트 방향)", value=True, on_change=set_rev)

metrics()
legend()
ui.separator().classes("q-my-md")
grid()

# 초기 로드
load_sample()
state["racks"] = sorted({c.rack for c in all_cells().values()})
state["cats"] = sorted({c.category for c in all_cells().values()})

ui.run(title="냉동창고 레이아웃", reload=False, port=8080)
