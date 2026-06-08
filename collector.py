# -*- coding: utf-8 -*-
"""사방넷 풀필먼트 재고 수집기 → 비공개 Google Sheet 적재.

로컬/스케줄러에서 주기 실행(예: 30분~1시간). Streamlit Cloud 에서는 돌리지 않는다.

흐름:
  1) 사방넷 풀필먼트 로그인 (sabang_auto 와 동일 패턴)
  2) 재고/로케이션 조회 페이지 → 엑셀 다운로드   ← [TODO] 사이트 확인 필요
  3) warehouse.load_dataframe 로 정규화
  4) live.write_inventory 로 시트에 덮어쓰기 (+ 갱신시각)

준비:
  pip install -r requirements-collector.txt
  playwright install chromium
  .env 채우기 (.env.example 참고)
  secrets/service_account.json 배치 (시트에 편집자로 공유된 서비스계정 키)

사용:
  python collector.py             # 1회 수집·적재
  python collector.py --discover  # 헤드풀 + 일시정지: 재고 페이지/버튼 셀렉터 찾기용
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from playwright.sync_api import Page, sync_playwright

import live
import warehouse as wh

ROOT = Path(__file__).resolve().parent
DOWNLOADS = ROOT / "downloads"
LOGIN_URL = "https://wms02.sbfulfillment.co.kr/login"


# --- 로그인 (sabang_auto/src/sabang.py 패턴 재사용) -----------------------
def _on_login_page(page: Page) -> bool:
    if "/login" in page.url:
        return True
    try:
        return page.locator('input[name="companyCode"]').count() > 0
    except Exception:
        return False


def _login(page: Page) -> None:
    page.goto(LOGIN_URL)
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(1200)
    page.fill('input[name="companyCode"]', os.environ["SABANG_COMPANY_CODE"])
    page.fill('input[name="id"]', os.environ["SABANG_ID"])
    page.fill('input[name="password"]', os.environ["SABANG_PW"])
    page.click('button:has-text("로그인")')
    try:
        page.wait_for_url(lambda u: "/login" not in u, timeout=20000)
        page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass
    page.wait_for_timeout(1500)
    if _on_login_page(page):
        raise RuntimeError("로그인 실패 — 자격증명/2단계인증/사이트 상태 확인")


# --- 재고 다운로드 [TODO: 사방넷 재고 페이지 확인 후 구현] ----------------
def download_location_inventory(page: Page) -> Path:
    """재고/로케이션 조회 페이지로 이동 → 엑셀 다운로드 → 파일 경로 반환.

    아직 사방넷 재고 페이지 URL/내보내기 방식이 확정되지 않아 미구현.
    `python collector.py --discover` 로 아래를 확인한 뒤 채운다:
      - 재고 페이지 URL (SABANG_INVENTORY_URL)
      - '엑셀 다운로드' 버튼 텍스트/셀렉터
      - 회사(라라스윗 의왕) 선택이 필요한지

    구현 예시(셀렉터는 확인 후 교체):
        page.goto(os.environ["SABANG_INVENTORY_URL"])
        page.wait_for_load_state("networkidle")
        with page.expect_download() as dl:
            page.click('button:has-text("엑셀 다운로드")')
        path = DOWNLOADS / dl.value.suggested_filename
        dl.value.save_as(str(path))
        return path
    """
    raise NotImplementedError(
        "재고 다운로드 미구현 — `python collector.py --discover` 로 페이지/셀렉터 확인 후 채우세요."
    )


def _parse_download(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in (".xlsx", ".xls"):
        raw = pd.read_excel(path)
    else:
        raw = pd.read_csv(path, encoding="utf-8-sig")
    return wh.load_dataframe(raw)


# --- 실행 모드 ------------------------------------------------------------
def run_once() -> None:
    DOWNLOADS.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(accept_downloads=True).new_page()
        try:
            _login(page)
            path = download_location_inventory(page)
        finally:
            browser.close()

    df = _parse_download(path)
    client = live.client_from_file(ROOT / "secrets" / "service_account.json")
    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    n = live.write_inventory(client, os.environ["GSHEET_ID"],
                             os.environ.get("GSHEET_TAB", "재고"), df, updated_at)
    print(f"[OK] {n}행 적재 완료 @ {updated_at}")


def discover() -> None:
    """헤드풀로 로그인 후 일시정지 — 재고 페이지로 이동해 셀렉터를 찾는다."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_context(accept_downloads=True).new_page()
        _login(page)
        print("\n로그인 완료. 브라우저에서 '재고/로케이션 조회' 페이지로 이동하세요.")
        print("→ 그 페이지의 URL 과 '엑셀 다운로드' 버튼을 확인한 뒤 알려주세요.")
        page.pause()   # Playwright Inspector 열림 (셀렉터 탐색)
        print("현재 URL:", page.url)
        browser.close()


if __name__ == "__main__":
    load_dotenv(ROOT / ".env")
    if "--discover" in sys.argv:
        discover()
    else:
        run_once()
