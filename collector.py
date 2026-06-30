# -*- coding: utf-8 -*-
"""사방넷 WMS 로케이션별 재고 자동 수집기.

[로그인] -> [로케이션별 재고 API 호출] -> [정규화] -> [Google Sheet에 적재]

사용한 사방넷 API:
- 로그인:   POST https://wms02.sbfulfillment.co.kr/v1/wms/auth/login
- 재고조회: POST https://wms02.sbfulfillment.co.kr/api/v1/wms/inventory/stocks/stock-descriptions/with-expiration-date-and-locations

환경변수(.env)로 다음 값을 채운다 (.env.example 참고):
    SABANG_COMPANY_CODE=D8432
    SABANG_ID=uss
    SABANG_PASSWORD=...
    SABANG_MEMBER_ID=53          # "라라스윗 의왕" 고정값
    SHEET_ID=1DgNOjaVD0OvVbxWmrZZZsO7VW8dhuvzqD0HOd6mioHQ
    SHEET_TAB=WMS재고
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone, timedelta

import requests
import pandas as pd
from dotenv import load_dotenv

import live  # 구글 시트 read/write 브릿지 (live.py)

load_dotenv()

BASE_URL = "https://wms02.sbfulfillment.co.kr"
LOGIN_PATH = "/v1/wms/auth/login"
STOCK_PATH = "/api/v1/wms/inventory/stocks/stock-descriptions/with-expiration-date-and-locations"

KST = timezone(timedelta(hours=9))

# warehouse.py 의 COLUMN_ALIASES 표준명에 맞춘 출력 컬럼
OUTPUT_COLUMNS = ["로케이션명", "상품코드", "출고상품명", "유통기한", "상품 합계 수량"]


# ---------------------------------------------------------------------------
# 1. 로그인 -> access_token 획득
# ---------------------------------------------------------------------------
def login() -> str:
    payload = {
        "company_code": os.environ["SABANG_COMPANY_CODE"],
        "id": os.environ["SABANG_ID"],
        "password": os.environ["SABANG_PASSWORD"],
    }
    resp = requests.post(f"{BASE_URL}{LOGIN_PATH}", json=payload, timeout=15)
    resp.raise_for_status()
    body = resp.json()
    if body.get("code") != "SUCCESS":
        raise RuntimeError(f"로그인 실패: {body.get('message')}")
    return body["data"]["access_token"]


# ---------------------------------------------------------------------------
# 2. 로케이션별 재고 조회 (페이지네이션은 page_size를 크게 줘서 1회 호출로 해결)
# ---------------------------------------------------------------------------
def fetch_location_inventory(access_token: str, member_id: int,
                              page_size: int = 1000) -> list[dict]:
    headers = {"Authorization": f"Bearer {access_token}"}
    all_products: list[dict] = []
    page_no = 1

    while True:
        payload = {
            "member_ids": [member_id],
            "page_info": {"page_no": page_no, "page_size": page_size},
            "supply_company_ids": [],
        }
        resp = requests.post(f"{BASE_URL}{STOCK_PATH}", json=payload,
                              headers=headers, timeout=30)
        resp.raise_for_status()
        body = resp.json()
        if body.get("code") != "SUCCESS":
            raise RuntimeError(f"재고조회 실패: {body.get('message')}")

        products = body["data"]["product_stock_list"]
        all_products.extend(products)

        # 받은 개수가 page_size보다 작으면 마지막 페이지
        if len(products) < page_size:
            break
        page_no += 1

    return all_products


# ---------------------------------------------------------------------------
# 3. 정규화: product_stock_list -> 로케이션 단위 평탄화(flatten)
#    standby_info[] 안에 location_name 별 재고가 있고,
#    그 안에 expire_info_list[] 로 유통기한별 수량이 또 나뉜다.
#    "라라스윗 의왕"/"기본존" 같은 구역명도 그대로 둔다.
#    (warehouse.py의 로케이션 정규식이 셀 코드만 알아서 골라 시각화함)
# ---------------------------------------------------------------------------
def normalize(products: list[dict]) -> pd.DataFrame:
    rows = []
    for p in products:
        code = p.get("product_code", "")
        name = p.get("product_name", "")
        for loc in p.get("standby_info", []) or []:
            location_name = loc.get("location_name", "")
            expire_list = loc.get("expire_info_list") or []

            if expire_list:
                for exp in expire_list:
                    rows.append({
                        "로케이션명": location_name,
                        "상품코드": code,
                        "출고상품명": name,
                        "유통기한": _format_expiry(exp.get("expire_date")),
                        "상품 합계 수량": exp.get("sum_quantity", 0),
                    })
            else:
                # 유통기한 정보가 없는 로트 (예: 베이글 등)
                rows.append({
                    "로케이션명": location_name,
                    "상품코드": code,
                    "출고상품명": name,
                    "유통기한": "",
                    "상품 합계 수량": loc.get("sum_quantity", 0),
                })

    df = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    # 수량 0인 빈 로케이션 행은 제외 (격자에 노이즈만 추가)
    df = df[df["상품 합계 수량"] > 0].reset_index(drop=True)
    return df


def _format_expiry(expire_date: str | None) -> str:
    """'20260624' -> '2026-06-24'. 없으면 빈 문자열."""
    if not expire_date or len(expire_date) != 8:
        return ""
    return f"{expire_date[0:4]}-{expire_date[4:6]}-{expire_date[6:8]}"


# ---------------------------------------------------------------------------
# 4. 메인 실행: 수집 -> 시트 적재
# ---------------------------------------------------------------------------
def run() -> None:
    member_id = int(os.environ.get("SABANG_MEMBER_ID", "53"))
    sheet_id = os.environ["SHEET_ID"]
    sheet_tab = os.environ.get("SHEET_TAB", "WMS재고")

    print("[1/4] 사방넷 로그인 중...")
    token = login()

    print("[2/4] 로케이션별 재고 조회 중...")
    products = fetch_location_inventory(token, member_id)
    print(f"      -> 상품 {len(products)}건 수신")

    print("[3/4] 데이터 정규화 중...")
    df = normalize(products)
    print(f"      -> 로케이션 단위 {len(df)}행으로 평탄화")

    print("[4/4] Google Sheet 적재 중...")
    client = live.client_from_file() if os.path.exists("secrets/service_account.json") \
        else live.client_from_secrets()
    updated_at = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    n = live.write_inventory(client, sheet_id, sheet_tab, df, updated_at)
    print(f"완료: {n}행 적재 (갱신시각 {updated_at})")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        print(f"[오류] {e}", file=sys.stderr)
        sys.exit(1)
