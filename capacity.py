# -*- coding: utf-8 -*-
"""상온창고 파렛트 케파 계산 모듈.

WMS 현재고(frozen_layout_재고 시트) x 품목정보(상온 수불부 시트, PLT입수)를
매칭해서, 상온 전체 사용 파렛트 수 / 가용률(%)을 계산한다.
"""
import math

import pandas as pd
import live  # 기존에 쓰고 있는 구글시트 read/write 브릿지

ITEM_MASTER_SHEET_ID = "1snL5O6TJ-TUj_d2dPCc1LVXXL66zQH_Upf7dC8fQ85U"   # 상온 수불부
FROZEN_LAYOUT_SHEET_ID = "1pUr4YIJwWxMuHZznJmCQCfy5xmdsuAwXyg4vWzUTtMY"  # frozen_layout_재고
AMBIENT_TOTAL_CAPACITY = 450  # 상온 총 파렛트 케파
AMBIENT_EXTRA_LOCS = {"상온 B2C", "상온 B2B"}
FROZEN_EXTRA_LOCS = {"라라스윗 의왕(B2B)", "의왕 출고용"}


def is_ambient_loc(loc: str) -> bool:
    return loc.startswith("Z") or loc in AMBIENT_EXTRA_LOCS


def is_frozen_extra_loc(loc: str) -> bool:
    return loc in FROZEN_EXTRA_LOCS


def _get_client():
    return live.client_from_secrets()


def load_wms_stock(client, loc_filter=None) -> pd.DataFrame:
    """frozen_layout_재고 > WMS재고 탭에서 품목별 현재고 합계를 가져온다.
    loc_filter: 로케이션명을 받아 True/False를 돌려주는 함수 (없으면 전체)"""
    sh = client.open_by_key(FROZEN_LAYOUT_SHEET_ID)
    ws = sh.worksheet("WMS재고")
    df = pd.DataFrame(ws.get_all_records())

    df["로케이션명"] = df["로케이션명"].astype(str).str.strip()
    if loc_filter is not None:
        df = df[df["로케이션명"].apply(loc_filter)]

    df["바코드"] = df["상품코드"].astype(str).str.replace(r"^UW", "", regex=True)
    df["상품 합계 수량"] = pd.to_numeric(df["상품 합계 수량"], errors="coerce").fillna(0)

    stock = df.groupby("바코드", as_index=False)["상품 합계 수량"].sum()
    return stock.rename(columns={"상품 합계 수량": "현재고수량"})


def load_item_master(client) -> pd.DataFrame:
    """품목정보 (연동) 기존 탭에서 제품명/바코드/보관구분/PLT입수를 가져온다."""
    sh = client.open_by_key(ITEM_MASTER_SHEET_ID)
    ws = sh.worksheet("품목정보 (연동) 기존")
    df = pd.DataFrame(ws.get_all_records())

    df["바코드"] = df["바코드"].astype(str)
    df["PLT입수"] = pd.to_numeric(
        df["PLT입수"].astype(str).str.replace(",", ""), errors="coerce"
    )
    return df[["제품명", "바코드", "보관구분", "PLT입수", "사용여부"]]


def calc_ambient_capacity(total_capacity: int = AMBIENT_TOTAL_CAPACITY) -> dict:
    client = _get_client()
    stock = load_wms_stock(client, is_ambient_loc)
    items = load_item_master(client)

    # 상온 품목만
    ambient_items = items[items["보관구분"] == "상온"].copy()
    # 단종 품목(사용여부=N)도 제외하고 싶으면 아래 줄 주석 해제
    # ambient_items = ambient_items[ambient_items["사용여부"] == "Y"]

    merged = ambient_items.merge(stock, on="바코드", how="left")
    merged["현재고수량"] = merged["현재고수량"].fillna(0)

    merged["사용파렛트"] = merged.apply(
        lambda r: math.ceil(r["현재고수량"] / r["PLT입수"]) if r["PLT입수"] and r["PLT입수"] > 0 else 0,
        axis=1,
    )

    used = int(merged["사용파렛트"].sum())
    return {
        "품목별상세": merged[["제품명", "현재고수량", "PLT입수", "사용파렛트"]].sort_values(
            "사용파렛트", ascending=False
        ),
        "사용파렛트": used,
        "총케파": total_capacity,
        "잔여파렛트": total_capacity - used,
        "가용률(%)": round(used / total_capacity * 100, 1),
    }

    
def calc_frozen_extra_pallets() -> dict:
    """냉동 비렉 로케이션(의왕 B2B, 의왕 출고용) 재고를 PLT입수로 환산"""
    client = _get_client()
    stock = load_wms_stock(client, is_frozen_extra_loc)
    items = load_item_master(client)

    merged = stock.merge(items, on="바코드", how="left")
    has_plt = merged["PLT입수"].fillna(0) > 0

    merged["사용파렛트"] = 0
    merged.loc[has_plt, "사용파렛트"] = (
        merged.loc[has_plt, "현재고수량"] / merged.loc[has_plt, "PLT입수"]
    ).apply(math.ceil)

    missing = merged[~has_plt & (merged["현재고수량"] > 0)]["바코드"].tolist()
    return {
        "비렉파렛트": int(merged["사용파렛트"].sum()),
        "PLT입수_누락": missing,
    }