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


def _get_client():
    return live.client_from_secrets()


def load_wms_stock(client) -> pd.DataFrame:
    """frozen_layout_재고 > WMS재고 탭에서 품목별 현재고 합계를 가져온다."""
    sh = client.open_by_key(FROZEN_LAYOUT_SHEET_ID)
    ws = sh.worksheet("WMS재고")
    df = pd.DataFrame(ws.get_all_records())  # 로케이션명, 상품코드, 출고상품명, 유통기한, 상품 합계 수량

    # "UW8809599361019" -> "8809599361019" 로 변환해서 품목정보 탭의 바코드(G열)와 맞춤
    df["바코드"] = df["상품코드"].astype(str).str.replace(r"^UW", "", regex=True)
    df["상품 합계 수량"] = pd.to_numeric(df["상품 합계 수량"], errors="coerce").fillna(0)

    # 로케이션이 여러 개로 쪼개져 있으니 바코드 기준으로 전체 합산
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
    stock = load_wms_stock(client)
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