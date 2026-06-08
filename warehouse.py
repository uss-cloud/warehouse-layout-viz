# -*- coding: utf-8 -*-
"""냉동창고 레이아웃 시각화 - 공용 데이터/렌더링 모듈.

Streamlit 버전(app_streamlit.py)과 NiceGUI 버전(app_nicegui.py)이
이 모듈을 함께 사용한다. 데이터 적재 -> 정규화 -> 로케이션 파싱 ->
집계 -> 셀 색상/HTML 생성까지 여기서 담당.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

# ---------------------------------------------------------------------------
# 1) 컬럼 정규화 : 사방넷/시트 export 의 한글 헤더를 내부 표준명으로 매핑
# ---------------------------------------------------------------------------
COLUMN_ALIASES = {
    "location": ["로케이션명", "로케이션", "location", "로케이션코드", "셀", "셀번호"],
    "code": ["상품코드", "code", "상품 코드", "wms코드", "wms 코드", "바코드"],
    "name": ["출고상품명", "상품명", "품목명", "name", "출고 상품명"],
    "expiry": ["유통기한", "expiry", "유통 기한", "소비기한"],
    "qty": ["상품 합계 수량", "수량", "재고", "재고수량", "qty", "상품합계수량"],
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", str(s)).lower()


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    lookup = {}
    for std, aliases in COLUMN_ALIASES.items():
        for a in aliases:
            lookup[_norm(a)] = std
    rename = {}
    for col in df.columns:
        key = _norm(col)
        if key in lookup:
            rename[col] = lookup[key]
    df = df.rename(columns=rename)
    missing = {"location", "name", "qty"} - set(df.columns)
    if missing:
        raise ValueError(
            f"필수 컬럼을 찾지 못했습니다: {missing}. "
            f"원본 컬럼명: {list(df.columns)}"
        )
    for opt in ("code", "expiry"):
        if opt not in df.columns:
            df[opt] = ""
    return df[["location", "code", "name", "expiry", "qty"]].copy()


# ---------------------------------------------------------------------------
# 2) 로케이션 코드 파싱 :  A07-25-04  ->  rack=A07, bay=25, tier=4
# ---------------------------------------------------------------------------
LOC_RE = re.compile(r"^\s*([A-Za-z]\d{2})-(\d{2})-(\d{2})")


def parse_location(loc: str):
    m = LOC_RE.match(str(loc))
    if not m:
        return None, None, None
    return m.group(1).upper(), int(m.group(2)), int(m.group(3))


# ---------------------------------------------------------------------------
# 3) 품목 카테고리 추정 (색상 그룹용). 키워드 우선순위.
# ---------------------------------------------------------------------------
CATEGORY_RULES = [
    ("모나카", ["모나카"]),
    ("빵샌드", ["빵샌드"]),
    ("넛티/스틱바", ["넛티", "스틱바"]),
    ("초코바", ["초코바"]),
    ("제로바", ["제로바"]),
    ("요거트바", ["요거트바"]),
    ("요거트", ["요거트"]),
    ("콘", ["콘"]),
    ("파인트", ["파인트", "바닐라빈", "치즈케이크", "티라미수"]),
    ("쉐이크", ["쉐이크"]),
    ("베이글", ["베이글"]),
    ("우유/라떼", ["우유", "라떼"]),
    ("멜론바", ["멜론바"]),
    ("선데", ["선데", "초코볼"]),
]


def category(name: str) -> str:
    n = str(name)
    for cat, kws in CATEGORY_RULES:
        if any(k in n for k in kws):
            return cat
    return "기타"


# ---------------------------------------------------------------------------
# 4) 적재 + 집계
# ---------------------------------------------------------------------------
def load_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = normalize_columns(df)
    df["qty"] = pd.to_numeric(df["qty"], errors="coerce").fillna(0).astype(int)
    df["expiry_dt"] = pd.to_datetime(df["expiry"], errors="coerce")
    df["name"] = df["name"].astype(str).str.replace(r"^라라스윗\)\s*", "", regex=True).str.strip()
    rb = df["location"].apply(parse_location)
    df["rack"] = [x[0] for x in rb]
    df["bay"] = [x[1] for x in rb]
    df["tier"] = [x[2] for x in rb]
    df = df[df["rack"].notna()].copy()
    df["category"] = df["name"].apply(category)
    return df


def read_uploaded(file_bytes: bytes, filename: str) -> pd.DataFrame:
    name = filename.lower()
    if name.endswith((".xlsx", ".xls")):
        df = pd.read_excel(io.BytesIO(file_bytes))
    else:
        # csv : utf-8-sig 우선, 실패 시 cp949(엑셀 한글)
        try:
            df = pd.read_csv(io.BytesIO(file_bytes), encoding="utf-8-sig")
        except UnicodeDecodeError:
            df = pd.read_csv(io.BytesIO(file_bytes), encoding="cp949")
    return load_dataframe(df)


@dataclass
class Cell:
    location: str
    rack: str
    bay: int
    tier: int
    total_qty: int
    lots: list          # [{name, code, expiry, qty}]
    main_name: str
    category: str
    min_expiry: pd.Timestamp | None
    dday: int | None    # 가장 임박한 로트까지 남은 일수


def aggregate(df: pd.DataFrame, today: datetime | None = None) -> dict:
    today = today or datetime.now()
    cells: dict[str, Cell] = {}
    for loc, g in df.groupby("location"):
        g = g.sort_values("qty", ascending=False)
        main = g.iloc[0]
        exps = g["expiry_dt"].dropna()
        min_exp = exps.min() if not exps.empty else None
        dday = (min_exp.normalize() - pd.Timestamp(today).normalize()).days if min_exp is not None else None
        cells[loc] = Cell(
            location=loc,
            rack=main["rack"],
            bay=int(main["bay"]),
            tier=int(main["tier"]),
            total_qty=int(g["qty"].sum()),
            lots=[
                {
                    "name": r["name"],
                    "code": r["code"],
                    "expiry": (r["expiry_dt"].strftime("%Y-%m-%d") if pd.notna(r["expiry_dt"]) else "-"),
                    "qty": int(r["qty"]),
                }
                for _, r in g.iterrows()
            ],
            main_name=main["name"],
            category=main["category"],
            min_expiry=min_exp,
            dday=dday,
        )
    return cells


# ---------------------------------------------------------------------------
# 5) 색상 로직 (3가지 모드)
# ---------------------------------------------------------------------------
CAT_PALETTE = [
    "#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
    "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac",
    "#86bcb6", "#d37295", "#a0cbe8", "#ffbe7d", "#8cd17d",
]


def category_color(cat: str) -> str:
    idx = (sum(ord(ch) for ch in cat)) % len(CAT_PALETTE)
    return CAT_PALETTE[idx]


def _lerp(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def _hex(rgb):
    return "#%02x%02x%02x" % rgb


def qty_color(qty: int, qmax: int) -> str:
    if qty <= 0 or qmax <= 0:
        return "#f5f5f5"
    t = min(qty / qmax, 1.0)
    return _hex(_lerp((222, 235, 247), (8, 81, 156), t))  # 연하늘 -> 진파랑


def dday_color(dday: int | None) -> str:
    if dday is None:
        return "#eeeeee"          # 유통기한 없음(베이글 등)
    if dday < 0:
        return "#7a0c0c"          # 기한 경과
    if dday <= 30:
        return "#e15759"          # 임박(빨강)
    if dday <= 60:
        return "#ff9d5c"          # 주의(주황)
    if dday <= 120:
        return "#ffd966"          # 보통(노랑)
    return "#8cd17d"              # 여유(초록)


def text_on(bg: str) -> str:
    bg = bg.lstrip("#")
    r, g, b = int(bg[0:2], 16), int(bg[2:4], 16), int(bg[4:6], 16)
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    return "#111" if lum > 150 else "#fff"


def cell_color(cell: Cell | None, mode: str, qmax: int) -> str:
    if cell is None:
        return "#ffffff"
    if mode == "품목":
        return category_color(cell.category)
    if mode == "재고수량":
        return qty_color(cell.total_qty, qmax)
    if mode == "유통기한":
        return dday_color(cell.dday)
    return "#ffffff"


# ---------------------------------------------------------------------------
# 6) HTML 렌더링 (Streamlit / NiceGUI 공용)
# ---------------------------------------------------------------------------
def _short(name: str, n: int = 10) -> str:
    return name if len(name) <= n else name[: n - 1] + "…"


def render_rack_html(rack: str, cells: dict, mode: str, qmax: int,
                     bay_range, only_loc: str | None = None) -> str:
    tiers = [4, 3, 2, 1]
    css_cell = (
        "border:1px solid #ccc;width:84px;height:64px;vertical-align:top;"
        "font-size:10px;line-height:1.25;padding:3px;overflow:hidden;border-radius:4px;"
    )
    html = [f'<div style="margin:6px 0 18px 0">']
    html.append(f'<div style="font-weight:700;font-size:15px;margin-bottom:4px">랙 {rack}</div>')
    html.append('<table style="border-collapse:separate;border-spacing:3px">')
    # 베이 번호 헤더
    html.append("<tr><td style='font-size:10px;color:#888'></td>")
    for b in bay_range:
        html.append(f"<td style='text-align:center;font-size:10px;color:#888'>{b:02d}</td>")
    html.append("</tr>")
    for t in tiers:
        html.append(f"<tr><td style='font-size:10px;color:#888;padding-right:4px'>{t}단</td>")
        for b in bay_range:
            loc = f"{rack}-{b:02d}-{t:02d}"
            cell = cells.get(loc)
            bg = cell_color(cell, mode, qmax)
            fg = text_on(bg)
            if cell is None:
                inner = "<span style='color:#ccc'>·</span>"
                tip = f"{loc} (빈 칸)"
            else:
                lots_txt = " | ".join(
                    f"{l['name']} / {l['expiry']} / {l['qty']:,}개" for l in cell.lots
                )
                tip = f"{loc}\n{lots_txt}\n합계 {cell.total_qty:,}개"
                dtxt = (f"D{cell.dday:+d}" if cell.dday is not None else "")
                inner = (
                    f"<div style='font-weight:600'>{_short(cell.main_name)}</div>"
                    f"<div>{cell.total_qty:,}개</div>"
                    f"<div style='opacity:.8'>{dtxt}</div>"
                )
            dim = (only_loc is not None and loc != only_loc)
            opacity = "opacity:.18;" if dim else ""
            html.append(
                f"<td title=\"{tip}\" style='{css_cell}background:{bg};color:{fg};{opacity}'>{inner}</td>"
            )
        html.append("</tr>")
    html.append("</table></div>")
    return "".join(html)


def render_all_html(cells: dict, mode: str, reverse_bays: bool = True) -> str:
    """reverse_bays=True 이면 시트처럼 베이 01번을 맨 오른쪽에 배치(좌우반전)."""
    if not cells:
        return "<p>표시할 데이터가 없습니다.</p>"
    qmax = max((c.total_qty for c in cells.values()), default=1)
    racks = sorted({c.rack for c in cells.values()})
    blocks = [_legend_html(mode, qmax)]
    for rack in racks:
        max_bay = max(c.bay for c in cells.values() if c.rack == rack)
        bays = list(range(1, max_bay + 1))
        if reverse_bays:
            bays = bays[::-1]
        blocks.append(render_rack_html(rack, cells, mode, qmax, bays))
    return "<div style='font-family:system-ui,Segoe UI,Malgun Gothic'>" + "".join(blocks) + "</div>"


def _legend_html(mode: str, qmax: int) -> str:
    items = []
    if mode == "유통기한":
        legend = [
            ("기한 경과", "#7a0c0c"), ("≤30일", "#e15759"), ("≤60일", "#ff9d5c"),
            ("≤120일", "#ffd966"), (">120일", "#8cd17d"), ("기한 없음", "#eeeeee"),
        ]
    elif mode == "재고수량":
        legend = [("적음", "#deebf7"), ("중간", "#6baed6"), (f"많음(최대 {qmax:,})", "#08519c")]
    else:
        cats = [c for c, _ in CATEGORY_RULES] + ["기타"]
        legend = [(c, category_color(c)) for c in cats]
    for label, color in legend:
        items.append(
            f"<span style='display:inline-flex;align-items:center;margin:2px 10px 2px 0;font-size:12px'>"
            f"<span style='width:14px;height:14px;background:{color};border:1px solid #aaa;"
            f"border-radius:3px;margin-right:5px'></span>{label}</span>"
        )
    return f"<div style='margin:6px 0 10px 0'><b>색상 기준: {mode}</b><br>{''.join(items)}</div>"


# ---------------------------------------------------------------------------
# 7) 사방넷 자동 수집 (스텁) - 자격증명 연결 전 placeholder
# ---------------------------------------------------------------------------
def fetch_from_sabang() -> pd.DataFrame:
    """사방넷 풀필먼트에서 로케이션 재고 raw 를 받아오는 자리.

    실제 연동 시 두 가지 방식 중 택1:
      (1) 사방넷 OpenAPI 가 있으면 requests 로 호출 -> DataFrame
      (2) API 가 없으면 기존 Ecount 알람봇처럼 Playwright 로 로그인 ->
          재고 조회 엑셀 다운로드 -> pandas 로 읽기
    지금은 자격증명이 없으므로 NotImplementedError 를 던진다.
    반환 DataFrame 은 load_dataframe() 가 먹을 수 있는 원본 컬럼이면 된다.
    """
    raise NotImplementedError(
        "사방넷 자동 수집은 자격증명/엔드포인트 연결 후 활성화됩니다. "
        "지금은 '수동 업로드' 또는 sample_inventory.csv 를 사용하세요."
    )
