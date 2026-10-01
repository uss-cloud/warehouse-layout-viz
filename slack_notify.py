# -*- coding: utf-8 -*-
"""냉동/상온 케파를 매일 정해진 시각에 Slack으로 자동 전송.

Windows 작업 스케줄러에 등록해서, 퇴근 전(예: 매일 18:30)에 1회 실행.
"""
import os
import math
import requests
import pandas as pd

import live       # 기존 구글시트 read/write 브릿지
import warehouse as wh
import capacity    # 상온 파렛트 케파 계산 모듈

import os
from dotenv import load_dotenv
load_dotenv()
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

FROZEN_LAYOUT_SHEET_ID = "1pUr4YIJwWxMuHZznJmCQCfy5xmdsuAwXyg4vWzUTtMY"
TOTAL_FROZEN_LOCATIONS = 600


def get_client():
    if os.path.exists("secrets/service_account.json"):
        return live.client_from_file()
    return live.client_from_secrets()


def calc_frozen_capacity(client) -> dict:
    sh = client.open_by_key(FROZEN_LAYOUT_SHEET_ID)
    ws = sh.worksheet("WMS재고")
    raw = pd.DataFrame(ws.get_all_records())
    df = wh.load_dataframe(raw)
    frozen_df = df[~df["rack"].astype(str).str.upper().str.startswith("Z")]
    used = frozen_df["location"].nunique()
    return {
        "사용로케이션": used,
        "총케파": TOTAL_FROZEN_LOCATIONS,
        "가용률(%)": round(used / TOTAL_FROZEN_LOCATIONS * 100, 1),
    }


def build_message(frozen: dict, ambient: dict) -> str:
    today = pd.Timestamp.now().strftime("%Y-%m-%d")
    lines = [
        f"*📦 {today} 마감 케파 현황*",
        f"🧊 냉동: {frozen['사용로케이션']:,} / {frozen['총케파']:,} 로케이션 ({frozen['가용률(%)']}% 사용)",
        f"🌡️ 상온: {ambient['사용파렛트']:,} / {ambient['총케파']:,} 파렛트 ({ambient['가용률(%)']}% 사용)",
    ]
    if frozen["가용률(%)"] >= 90:
        lines.append("⚠️ 냉동 케파 90% 이상 — 입고 계획 시 주의 필요")
    if ambient["가용률(%)"] >= 90:
        lines.append("⚠️ 상온 케파 90% 이상 — 입고 계획 시 주의 필요")
    return "\n".join(lines)


def send_to_slack(text: str):
    payload = {
        "text": text,
        "username": "의왕센터 케파알리미",
        "icon_emoji": ":package:",
    }
    resp = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=15)
    resp.raise_for_status()


def run():
    client = get_client()
    frozen = calc_frozen_capacity(client)
    ambient = capacity.calc_ambient_capacity()
    message = build_message(frozen, ambient)
    send_to_slack(message)
    print("전송 완료:\n", message)


if __name__ == "__main__":
    run()