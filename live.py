# -*- coding: utf-8 -*-
"""실시간 재고 브릿지 - 비공개 Google Sheet 읽기/쓰기 (서비스계정).

- 수집기(collector.py): 사방넷에서 받은 재고를 시트에 write_inventory() 로 적재
- Streamlit 앱(app_streamlit.py): read_inventory() 로 최신 재고를 읽음

인증: 서비스계정 1개로 통일.
  - 앱(클라우드): st.secrets["gcp_service_account"] (dict)
  - 수집기(로컬):  secrets/service_account.json
대상 시트는 서비스계정 이메일에 '편집자'로 공유돼 있어야 한다.
"""
from __future__ import annotations

import json
from pathlib import Path

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
META_TAB = "_meta"
DATA_COLUMNS = ["로케이션명", "상품코드", "출고상품명", "유통기한", "상품 합계 수량"]


def _client(info: dict) -> gspread.Client:
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)


def client_from_secrets() -> gspread.Client:
    """Streamlit 앱용 - st.secrets 에서 서비스계정 정보."""
    import streamlit as st
    return _client(dict(st.secrets["gcp_service_account"]))


def client_from_file(path: str | Path = "secrets/service_account.json") -> gspread.Client:
    """수집기(로컬)용 - JSON 키 파일."""
    with open(path, encoding="utf-8") as f:
        return _client(json.load(f))


def read_inventory(client: gspread.Client, sheet_id: str, tab: str) -> pd.DataFrame:
    ws = client.open_by_key(sheet_id).worksheet(tab)
    records = ws.get_all_records()        # 첫 행을 헤더로
    return pd.DataFrame(records)


def read_updated_at(client: gspread.Client, sheet_id: str) -> str:
    try:
        ws = client.open_by_key(sheet_id).worksheet(META_TAB)
        return ws.acell("A1").value or ""
    except Exception:
        return ""


def write_inventory(client: gspread.Client, sheet_id: str, tab: str,
                    df: pd.DataFrame, updated_at: str) -> int:
    """df 를 시트 탭에 전량 덮어쓰기 + _meta!A1 에 갱신시각 기록."""
    cols = [c for c in DATA_COLUMNS if c in df.columns] or list(df.columns)
    df = df[cols]
    sh = client.open_by_key(sheet_id)
    try:
        ws = sh.worksheet(tab)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(tab, rows=max(len(df) + 10, 100), cols=len(cols) + 2)
    ws.clear()
    ws.update([cols] + df.astype(str).values.tolist(), value_input_option="RAW")
    try:
        m = sh.worksheet(META_TAB)
    except gspread.WorksheetNotFound:
        m = sh.add_worksheet(META_TAB, rows=5, cols=2)
    m.update_acell("A1", updated_at)
    return len(df)
