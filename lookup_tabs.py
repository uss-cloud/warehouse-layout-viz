# -*- coding: utf-8 -*-
"""app_streamlit.py 에 추가하는 '품목별 조회' / '로케이션별 조회' 탭.

기존 app_streamlit.py 맨 위에서 데이터를 불러온 뒤(state["df"] 등),
탭 구조를 만들어 아래 두 함수를 그 안에 넣어주면 됩니다.

전제: warehouse.py 에 다음 함수가 있다고 가정합니다.
    - wh.load_dataframe(raw_df) -> 정규화된 DataFrame (rack, bay, tier, category 등 컬럼 포함)
    - wh.aggregate(df) -> {location: Cell} 딕셔너리
      Cell 필드: location, rack, bay, tier, total_qty, lots(list[dict]), main_name, category, dday 등

사용 예 (기존 app_streamlit.py 안에서):

    tab1, tab2, tab3 = st.tabs(["창고 격자", "품목별 조회", "로케이션별 조회"])

    with tab1:
        # 기존 격자 렌더링 코드 그대로
        ...

    with tab2:
        render_item_lookup_tab(state["df"])

    with tab3:
        render_location_lookup_tab(state["df"])
"""
import pandas as pd
import streamlit as st

import warehouse as wh


# ---------------------------------------------------------------------------
# 탭 1: 품목별 조회
#   - 상품명/코드로 검색 -> 그 품목이 있는 모든 로케이션/수량/유통기한을 표로
# ---------------------------------------------------------------------------
def render_item_lookup_tab(df: pd.DataFrame) -> None:
    st.subheader("품목별 재고 조회")

    if df is None or df.empty:
        st.info("표시할 데이터가 없습니다. 사이드바에서 데이터를 먼저 불러오세요.")
        return

    # 검색 가능한 품목명 목록 (중복 제거, 가나다/알파벳 순)
    item_names = sorted(df["name"].dropna().unique().tolist())

    query = st.text_input("품목명 검색 (일부만 입력해도 검색됩니다)", "")

    if query:
        matched = [n for n in item_names if query.strip() in n]
    else:
        matched = item_names

    if not matched:
        st.warning("검색 결과가 없습니다.")
        return

    selected_item = st.selectbox(f"품목 선택 ({len(matched)}건 검색됨)", matched)

    if not selected_item:
        return

    item_df = df[df["name"] == selected_item].copy()

    if item_df.empty:
        st.warning("해당 품목의 재고 데이터가 없습니다.")
        return

    # 요약 지표
    total_qty = int(item_df["qty"].sum())
    loc_count = item_df["location"].nunique()
    col1, col2 = st.columns(2)
    col1.metric("총 재고", f"{total_qty:,}")
    col2.metric("점유 로케이션 수", f"{loc_count}")

    # 표: 로케이션, 수량, 유통기한 (수량 내림차순)
    display_cols = ["location", "qty", "expiry"]
    rename_map = {"location": "로케이션", "qty": "수량", "expiry": "유통기한"}

    table_df = (
        item_df[display_cols]
        .rename(columns=rename_map)
        .sort_values("수량", ascending=False)
        .reset_index(drop=True)
    )

    # 유통기한 기준 D-day 컬럼 추가 (있는 경우만)
    if "expiry_dt" in item_df.columns:
        today = pd.Timestamp.now().normalize()
        dday_series = (item_df["expiry_dt"] - today).dt.days
        table_df.insert(2, "D-day", dday_series.apply(
            lambda d: f"D{d:+d}" if pd.notna(d) else ""
        ).values)

    st.dataframe(table_df, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# 탭 2: 로케이션별 조회
#   - 랙/베이/단 선택 -> 해당 위치만 확대해서 나열
# ---------------------------------------------------------------------------
def render_location_lookup_tab(df: pd.DataFrame) -> None:
    st.subheader("로케이션별 재고 조회")

    if df is None or df.empty:
        st.info("표시할 데이터가 없습니다. 사이드바에서 데이터를 먼저 불러오세요.")
        return

    cells = wh.aggregate(df)
    if not cells:
        st.info("집계된 로케이션이 없습니다.")
        return

    all_racks = sorted({c.rack for c in cells.values()})

    col1, col2, col3 = st.columns(3)
    with col1:
        sel_racks = st.multiselect("랙 선택", all_racks, default=all_racks[:1] if all_racks else [])
    with col2:
        bay_options = sorted({c.bay for c in cells.values() if not sel_racks or c.rack in sel_racks})
        sel_bays = st.multiselect("베이 선택 (비워두면 전체)", bay_options)
    with col3:
        tier_options = sorted({c.tier for c in cells.values() if not sel_racks or c.rack in sel_racks})
        sel_tiers = st.multiselect("단 선택 (비워두면 전체)", tier_options)

    filtered = {
        loc: c for loc, c in cells.items()
        if (not sel_racks or c.rack in sel_racks)
        and (not sel_bays or c.bay in sel_bays)
        and (not sel_tiers or c.tier in sel_tiers)
    }

    if not filtered:
        st.warning("선택한 조건에 해당하는 로케이션이 없습니다.")
        return

    st.caption(f"선택된 로케이션 {len(filtered)}개")

    # 로케이션별로 확대 카드 형태로 나열 (수량 많은 순)
    sorted_locs = sorted(filtered.items(), key=lambda kv: kv[1].total_qty, reverse=True)

    for loc, cell in sorted_locs:
        with st.container(border=True):
            header_col1, header_col2, header_col3 = st.columns([2, 1, 1])
            header_col1.markdown(f"**{loc}**")
            header_col2.markdown(f"총재고: **{cell.total_qty:,}**")
            if cell.dday is not None:
                dday_label = f"D{cell.dday:+d}"
                header_col3.markdown(f"최임박: **{dday_label}**")
            else:
                header_col3.markdown("유통기한 없음")

            if cell.lots:
                lot_df = pd.DataFrame(cell.lots)
                rename_map = {"name": "품목", "code": "상품코드", "expiry": "유통기한", "qty": "수량"}
                lot_df = lot_df.rename(columns=rename_map)
                st.dataframe(lot_df, use_container_width=True, hide_index=True)
            else:
                st.caption("로트 정보 없음")
