# -*- coding: utf-8 -*-
"""냉동창고 레이아웃 시각화 - Streamlit 버전.

실행:  streamlit run app_streamlit.py
"""
import os

import pandas as pd
import streamlit as st

import warehouse as wh

st.set_page_config(page_title="냉동창고 레이아웃", layout="wide")
st.title("❄️ 냉동창고 레이아웃 / 재고 · 유통기한")

def _data_path():
    here = os.path.dirname(__file__)
    for fn in ("sample_inventory.csv", "example_inventory.csv"):
        p = os.path.join(here, fn)
        if os.path.exists(p):
            return p
    raise FileNotFoundError("sample_inventory.csv / example_inventory.csv 둘 다 없음")


SAMPLE = _data_path()


# ---- 데이터 적재 ---------------------------------------------------------
@st.cache_data(show_spinner=False)
def load_sample():
    return wh.load_dataframe(pd.read_csv(SAMPLE, encoding="utf-8-sig"))


with st.sidebar:
    st.header("데이터")
    source = st.radio("원본 선택", ["샘플 데이터", "수동 업로드", "사방넷 자동 수집"])
    df = None
    if source == "샘플 데이터":
        df = load_sample()
    elif source == "수동 업로드":
        up = st.file_uploader("사방넷 재고 export (csv / xlsx)", type=["csv", "xlsx", "xls"])
        if up is not None:
            df = wh.read_uploaded(up.getvalue(), up.name)
        else:
            st.info("파일을 올리면 표시됩니다. (컬럼: 로케이션명/상품코드/출고상품명/유통기한/수량)")
    else:
        try:
            df = wh.fetch_from_sabang()
            df = wh.load_dataframe(df)
        except NotImplementedError as e:
            st.warning(str(e))

if df is None or df.empty:
    st.stop()

cells = wh.aggregate(df)

# ---- 컨트롤 --------------------------------------------------------------
with st.sidebar:
    st.header("보기")
    mode = st.radio("색상 기준", ["품목", "재고수량", "유통기한"], horizontal=False)
    racks = sorted({c.rack for c in cells.values()})
    sel_racks = st.multiselect("랙 필터", racks, default=racks)
    cats = sorted({c.category for c in cells.values()})
    sel_cats = st.multiselect("품목군 필터", cats, default=cats)
    dday_max = st.slider("유통기한 D-day 이하만 강조(필터)", -30, 365, 365, step=10)
    reverse_bays = st.checkbox("베이 좌우반전 (01번을 오른쪽에 = 시트 방향)", value=True)

# ---- 필터 적용 -----------------------------------------------------------
filtered = {
    loc: c for loc, c in cells.items()
    if c.rack in sel_racks
    and c.category in sel_cats
    and (c.dday is None or c.dday <= dday_max if mode == "유통기한" else True)
}

# ---- 요약 지표 -----------------------------------------------------------
total_qty = sum(c.total_qty for c in filtered.values())
n_loc = len(filtered)
soon = sum(1 for c in filtered.values() if c.dday is not None and c.dday <= 30)
expired = sum(1 for c in filtered.values() if c.dday is not None and c.dday < 0)
c1, c2, c3, c4 = st.columns(4)
c1.metric("점유 로케이션", f"{n_loc:,}")
c2.metric("총 재고", f"{total_qty:,}")
c3.metric("유통기한 임박(≤30일)", f"{soon:,}")
c4.metric("기한 경과", f"{expired:,}")

# ---- 레이아웃 그리드 -----------------------------------------------------
html = wh.render_all_html(filtered, mode, reverse_bays=reverse_bays)
st.components.v1.html(
    f"<div style='overflow-x:auto'>{html}</div>",
    height=260 + 150 * len(sel_racks),
    scrolling=True,
)

# ---- 상세 테이블 ---------------------------------------------------------
with st.expander("📋 로트 상세 (선입선출/폐기 점검용)"):
    rows = []
    for c in filtered.values():
        for l in c.lots:
            rows.append(
                {"로케이션": c.location, "랙": c.rack, "품목": l["name"],
                 "유통기한": l["expiry"], "수량": l["qty"], "D-day": c.dday}
            )
    det = pd.DataFrame(rows).sort_values(["유통기한"], na_position="last")
    st.dataframe(det, use_container_width=True, hide_index=True)
