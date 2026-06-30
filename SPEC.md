# 냉동창고 레이아웃 시각화 — 사양서 (Specification)

> 문서 버전: 1.0 · 작성일: 2026-06-30 · 대상 코드: `C:\Users\choiyw\Desktop\frozen_layout`

---

## 1. 개요

### 1.1 목적
사방넷 풀필먼트의 **로케이션 재고 raw 데이터**(로케이션·상품·유통기한·수량)를 입력받아,
냉동 창고를 **랙(Rack) × 베이(Bay) × 단(Tier)** 격자로 자동 렌더링하는 시각화 도구.
색상으로 **품목 / 재고수량 / 유통기한**을 한눈에 파악하여 선입선출(FIFO)·폐기 점검·적재 밀도 관리를 돕는다.

### 1.2 범위
- 재고 데이터 적재(샘플 / 수동 업로드 / 사방넷 자동 수집) → 정규화 → 로케이션 파싱 → 집계 → 격자 렌더링.
- 두 가지 UI 구현(**Streamlit**, **NiceGUI**)을 동일 데이터 모듈(`warehouse.py`) 위에서 제공.
- 사방넷 → 비공개 Google Sheet → 앱으로 이어지는 실시간 연동 파이프라인(수집·표시 분리).

### 1.3 운영 전략
**Streamlit으로 먼저 운영 → NiceGUI로 창고 도면 개발 후 전환.**
- Streamlit: 운영 1차(클라우드 배포 용이, 빠른 대시보드).
- NiceGUI: 칸 클릭 → 상세 패널 등 인터랙션이 풍부, 추후 창고 도면 비전으로 확장.

---

## 2. 데이터 모델

### 2.1 로케이션 코드 규칙
```
A07-25-04
└┬┘ └┬┘ └┬┘
 │   │   └ 단(층)  01(하단) ~ 04(상단)
 │   └──── 베이(랙 안 가로 위치)  01 ~ 29
 └──────── 랙(열)  A01 ~ A08
```
- 파싱 정규식: `^\s*([A-Za-z]\d{2})-(\d{2})-(\d{2})` (`warehouse.LOC_RE`)
- 매칭 실패 시 `(None, None, None)` 반환 → 해당 행은 격자에서 제외.

### 2.2 입력 컬럼 (정규화 표준명)
| 표준명 | 필수 | 설명 | 허용 별칭(예) |
|---|---|---|---|
| `location` | ✅ | 로케이션 코드 | 로케이션명, 로케이션, 로케이션코드, 셀, 셀번호 |
| `code` | ⬜ | 상품코드 | 상품코드, wms코드, 바코드 |
| `name` | ✅ | 출고상품명 | 출고상품명, 상품명, 품목명 |
| `expiry` | ⬜ | 유통기한 | 유통기한, 소비기한 |
| `qty` | ✅ | 수량 | 상품 합계 수량, 수량, 재고, 재고수량 |

- 별칭 매핑: `warehouse.COLUMN_ALIASES`. 공백 제거 + 소문자 변환(`_norm`) 후 비교.
- 필수 컬럼(`location`, `name`, `qty`) 미발견 시 `ValueError` 발생.
- 선택 컬럼(`code`, `expiry`) 미존재 시 빈 문자열로 채움.

### 2.3 파생 필드 (`load_dataframe`)
- `qty`: 숫자 변환, 실패·결측은 `0`, 정수형.
- `expiry_dt`: `expiry`를 datetime 변환(실패 시 NaT).
- `name`: 접두어 `라라스윗) ` 제거 후 trim.
- `rack`, `bay`, `tier`: 로케이션 파싱 결과. `rack`이 없는 행은 제외.
- `category`: 품목명 키워드로 카테고리 추정.

### 2.4 품목 카테고리 (`CATEGORY_RULES`)
키워드 우선순위로 매칭, 미매칭은 `기타`.

| 카테고리 | 키워드 |
|---|---|
| 모나카 | 모나카 |
| 빵샌드 | 빵샌드 |
| 넛티/스틱바 | 넛티, 스틱바 |
| 초코바 | 초코바 |
| 제로바 | 제로바 |
| 요거트바 | 요거트바 |
| 요거트 | 요거트 |
| 콘 | 콘 |
| 파인트 | 파인트, 바닐라빈, 치즈케이크, 티라미수 |
| 쉐이크 | 쉐이크 |
| 베이글 | 베이글 |
| 우유/라떼 | 우유, 라떼 |
| 멜론바 | 멜론바 |
| 선데 | 선데, 초코볼 |

### 2.5 집계 단위 — `Cell` (dataclass)
로케이션 1칸 = `Cell` 1개. 동일 로케이션의 여러 로트(유통기한별)를 묶는다.

| 필드 | 타입 | 설명 |
|---|---|---|
| `location` | str | 로케이션 코드 |
| `rack` / `bay` / `tier` | str / int / int | 랙·베이·단 |
| `total_qty` | int | 로트 수량 합계 |
| `lots` | list[dict] | `{name, code, expiry, qty}` 목록 (수량 내림차순) |
| `main_name` | str | 대표 품목(최다 수량 로트) |
| `category` | str | 대표 품목 카테고리 |
| `min_expiry` | Timestamp\|None | 가장 임박한 유통기한 |
| `dday` | int\|None | 최임박 로트까지 남은 일수(D-day) |

- `aggregate(df, today=None)`: `today` 미지정 시 `datetime.now()` 기준 D-day 계산.

---

## 3. 색상 로직 (3가지 모드)

| 모드 | 의미 | 색 규칙 |
|---|---|---|
| **품목** | 품목군별 고유색 | 카테고리명 문자 합 % 팔레트(15색) — `category_color` |
| **재고수량** | 적재 밀도 | `qty/qmax` 비율로 연하늘(222,235,247) → 진파랑(8,81,156) 보간. 0/음수는 `#f5f5f5` |
| **유통기한** | 최임박 로트 D-day | 아래 구간색 — `dday_color` |

**유통기한 구간색**
| 조건 | 색 | 의미 |
|---|---|---|
| `dday is None` | `#eeeeee` | 기한 없음(베이글 등) |
| `dday < 0` | `#7a0c0c` | 기한 경과 |
| `≤ 30` | `#e15759` | 임박(빨강) |
| `≤ 60` | `#ff9d5c` | 주의(주황) |
| `≤ 120` | `#ffd966` | 보통(노랑) |
| `> 120` | `#8cd17d` | 여유(초록) |

- `text_on(bg)`: 배경 휘도(luminance) > 150이면 어두운 글자(`#111`), 아니면 흰 글자(`#fff`).
- `cell_color(cell, mode, qmax)`: 빈 칸은 `#ffffff`.

---

## 4. 렌더링 (HTML, Streamlit/NiceGUI 공용)

- `render_rack_html(rack, cells, mode, qmax, bay_range, only_loc)`: 한 랙을 `<table>` 격자로.
  - 행 = 단(4→3→2→1, 위가 상단), 열 = 베이.
  - 셀 크기 84×64px, 내부: 대표 품목명(10자 축약 `_short`) / 수량 / `D±n`.
  - `title` 속성 툴팁: 로케이션 + 로트별(품목/유통기한/수량) + 합계.
  - `only_loc` 지정 시 다른 칸은 `opacity:.18`로 흐리게(강조).
- `render_all_html(cells, mode, reverse_bays=True)`:
  - `qmax` = 전체 셀 최대 수량(재고수량 모드 정규화 기준).
  - 랙별로 데이터에 존재하는 **최대 베이 수**까지 격자 생성.
  - `reverse_bays=True`: 베이 01을 맨 오른쪽에 배치(시트 방향과 일치, 좌우반전).
  - 상단에 `_legend_html`로 범례 표시.
- `_legend_html(mode, qmax)`: 모드별 색상 범례.

> ⚠️ 현재 격자는 **데이터에 존재하는 로케이션만** 그린다. 베이 수는 랙별 최댓값으로 자동.
> 비어 있어도 "물리적 슬롯"까지 표시하려면 랙별 베이 수 정의(슬롯 마스터)가 필요.

---

## 5. 애플리케이션

### 5.1 Streamlit 버전 (`app_streamlit.py`)
실행: `streamlit run app_streamlit.py`

**데이터 소스(사이드바 라디오)**
1. **샘플 데이터** — `sample_inventory.csv`(있으면) 또는 `example_inventory.csv`. `@st.cache_data`.
2. **실시간 (사방넷→시트)** — `live.read_inventory()`로 비공개 시트 읽기. `ttl=600`(10분 캐시), `🔄 새로고침` 버튼으로 캐시 클리어. `📡 마지막 갱신` 시각 표시. 미설정 시 안내 경고.
3. **수동 업로드** — csv/xlsx 드래그&드롭 → `wh.read_uploaded`.

**보기 컨트롤**
- 색상 기준(품목/재고수량/유통기한), 랙 필터, 품목군 필터, D-day 강조 슬라이더(-30~365), 베이 좌우반전.

**요약 지표(metric)**: 점유 로케이션 / 총 재고 / 임박(≤30일) / 기한 경과.
**격자**: `components.v1.html`로 렌더(가로 스크롤).
**로트 상세 테이블**: expander 내 로트 단위 표(유통기한 정렬) — 선입선출/폐기 점검용.

### 5.2 NiceGUI 버전 (`app_nicegui.py`)
실행: `python app_nicegui.py` → http://localhost:8080

- 격자를 **네이티브 클릭 가능 셀**(`ui.element` div)로 렌더.
- 칸 클릭 → 우측 드로어(`right_drawer`) 상세 패널: 로케이션·랙/베이/단, 총재고·로트수·품목군, 최임박 D-day 배지, 로트 테이블.
- 선택 칸은 `2px solid #111` 테두리로 표시.
- 좌측 드로어: 데이터 소스(샘플/수동 업로드/사방넷 자동 수집), 보기 컨트롤(동일).
- `@ui.refreshable`로 metrics/grid/legend/detail 부분 갱신.
- 상태는 모듈 전역 `state` dict로 관리.

> 사방넷 자동 수집 선택 시 `wh.fetch_from_sabang()`가 `NotImplementedError` → 경고 알림.

---

## 6. 실시간 연동 파이프라인

```
[collector.py]  사방넷 풀필먼트 ──Playwright 로그인 + 엑셀 다운로드──▶ 정규화
   │ (로컬/스케줄러, 30분~1h)
   ▼
[비공개 Google Sheet]  ◀── 서비스계정 1개로 수집기 write / 앱 read
   ▲
[app_streamlit.py]  live.read_inventory() · 10분 캐시 · 🔄새로고침 · 마지막 갱신시각
```

**핵심 원칙: 수집과 표시를 분리.** 앱은 사방넷을 직접 긁지 않는다.

### 6.1 수집기 `collector.py`
- 로그인: `LOGIN_URL = https://wms02.sbfulfillment.co.kr/login`, `companyCode/id/password` 입력(sabang_auto 패턴 재사용). 환경변수 `SABANG_COMPANY_CODE / SABANG_ID / SABANG_PW`.
- `run_once()`: 로그인 → 재고 다운로드 → `_parse_download`(정규화) → `live.write_inventory`(시트 전량 덮어쓰기 + 갱신시각).
- `discover()` (`--discover`): 헤드풀 + `page.pause()` — 재고 페이지 URL/엑셀 버튼 셀렉터 탐색용.
- **미구현 1곳**: `download_location_inventory()` — 사방넷 재고 페이지 URL/내보내기 셀렉터 확정 후 채움(현재 `NotImplementedError`).

### 6.2 시트 브릿지 `live.py`
- 인증: 서비스계정 1개. 앱은 `st.secrets["gcp_service_account"]`, 수집기는 `secrets/service_account.json`. 시트에 서비스계정 이메일을 **편집자**로 공유 필요.
- `read_inventory` / `read_updated_at`(`_meta!A1`) / `write_inventory`(데이터 탭 clear 후 update + `_meta` 갱신시각).
- 데이터 컬럼: `로케이션명, 상품코드, 출고상품명, 유통기한, 상품 합계 수량`.

### 6.3 스텁 `warehouse.fetch_from_sabang()`
자격증명 연결 전 placeholder. 연결 시 ① 사방넷 OpenAPI(`requests`) 또는 ② Playwright 다운로드 중 택1.

---

## 7. 설정 / 보안

| 항목 | 내용 |
|---|---|
| `.streamlit/config.toml` | 테마(light, primaryColor `#08519c`), 업로드 한도 50MB |
| `.streamlit/secrets.toml` | `[gcp_service_account]` + `[sheet] id/tab` (커밋 제외) |
| `.env` | `SABANG_*`, `SABANG_INVENTORY_URL`, `GSHEET_ID/TAB` (커밋 제외) |
| `secrets/service_account.json` | 수집기용 SA 키 (커밋 제외) |

**데이터 보안**: 실제 재고 `sample_inventory.csv`는 `.gitignore`로 git 제외. repo엔 합성 예시 `example_inventory.csv`만 포함. 앱은 `sample_inventory.csv` 있으면 우선 사용, 없으면 예시 사용. 공개 클라우드 앱엔 실데이터 상주 금지(수동 업로드 또는 비공개 시트 경유).

---

## 8. 의존성

| 파일 | 용도 | 주요 패키지 |
|---|---|---|
| `requirements.txt` | Streamlit 앱(클라우드) | streamlit≥1.30, pandas≥2.0, openpyxl≥3.1, gspread≥6.0, google-auth≥2.28 |
| `requirements-collector.txt` | 수집기(로컬) | playwright≥1.40, gspread, google-auth, pandas, openpyxl, python-dotenv |
| `requirements-nicegui.txt` | NiceGUI 버전 | nicegui, pandas, openpyxl |

---

## 9. 배포 (Streamlit Community Cloud)
1. https://share.streamlit.io → GitHub 로그인.
2. New app → Deploy a public app from GitHub.
3. Repository / Branch=`main` / Main file path=`app_streamlit.py`.
4. Deploy (`requirements.txt`만 읽어 nicegui 미설치).
5. 실데이터는 사이드바 **수동 업로드** 또는 비공개 시트 연동으로.

---

## 10. 파일 구성

| 파일 | 설명 |
|---|---|
| `warehouse.py` | 공용 모듈: 컬럼 정규화·로케이션 파싱·집계·색상·HTML 렌더, 사방넷 수집 스텁 |
| `app_streamlit.py` | Streamlit 버전 (운영 1차) |
| `app_nicegui.py` | NiceGUI 버전 (칸 클릭 → 우측 상세 패널) |
| `collector.py` | 사방넷 수집기 (Playwright → 시트 적재, 로컬/스케줄러) |
| `live.py` | 비공개 Google Sheet 읽기/쓰기 브릿지 |
| `example_inventory.csv` | 합성 예시 데이터 (repo 동봉, 바로 실행용) |
| `sample_inventory.csv` | 실제 로케이션 재고 (로컬 전용, `.gitignore`) |

---

## 11. 한계 / 다음 단계
- 빈 슬롯까지 그리려면 랙별 베이 수 정의(슬롯 마스터) 필요.
- 시트의 물리 구조 표식(`비상구(E/V홀)`, `4F`, `◀A04`) 미반영.
- 유통기한 빈 품목(베이글 등)은 회색 처리.
- 샘플 D-day 음수 다수는 추출 시점 데이터가 과거(2025 제조분)라 정상.
- `collector.download_location_inventory()` 구현이 실시간 연동의 마지막 남은 작업.
