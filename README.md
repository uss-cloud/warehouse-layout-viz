# 냉동창고 레이아웃 시각화 (프로토타입)

사방넷 풀필먼트의 **로케이션 재고 raw**(로케이션·상품·유통기한·수량)를 받아서,
시트의 "냉동 창고 Layout" 탭을 **랙/베이/단 격자**로 자동 렌더링한다.
색상으로 품목 / 재고수량 / 유통기한을 한눈에 본다.

> Streamlit / NiceGUI **두 가지 버전**을 같은 데이터 모듈로 만들었다. 비교 후 하나만 골라 발전시키면 됨.

## 로케이션 코드 규칙
```
A07-25-04
└┬┘ └┬┘ └┬┘
 │   │   └ 단(층) 01(하단)~04(상단)
 │   └──── 베이(랙 안 가로 위치) 01~29
 └──────── 랙(열) A01~A08
```

## 파일
| 파일 | 설명 |
|---|---|
| `warehouse.py` | 공용 모듈: 컬럼 정규화·로케이션 파싱·집계·색상·HTML 렌더, 사방넷 수집 스텁 |
| `app_streamlit.py` | Streamlit 버전 |
| `app_nicegui.py` | NiceGUI 버전 (칸 클릭 → 우측 상세 패널) |
| `example_inventory.csv` | **합성 예시 데이터** (repo 동봉, 바로 실행용) |
| `sample_inventory.csv` | 실제 로케이션 재고 (로컬 전용, `.gitignore`로 커밋 제외) |

> ⚠️ **데이터 보안**: 실제 재고 raw(`sample_inventory.csv`)는 `.gitignore`로 git에 올라가지 않는다.
> repo에는 합성 예시(`example_inventory.csv`)만 들어있고, 앱은 `sample_inventory.csv`가 있으면 그걸,
> 없으면 예시 데이터를 자동 사용한다.

## 실행 (로컬)
```bash
# Streamlit (운영 1차)
pip install -r requirements.txt
streamlit run app_streamlit.py

# NiceGUI (창고 도면 개발용 - 추후 전환)
pip install -r requirements-nicegui.txt
python app_nicegui.py        # http://localhost:8080
```

## 배포 (Streamlit Community Cloud)
> 운영 전략: **Streamlit으로 먼저 운영 → NiceGUI로 창고 도면 개발 후 전환.**

1. https://share.streamlit.io 접속 → GitHub 로그인(해당 repo 계정).
2. **New app → Deploy a public app from GitHub**.
3. 설정:
   - Repository: `<계정>/warehouse-layout-viz`
   - Branch: `main`
   - Main file path: `app_streamlit.py`
4. **Deploy** 클릭. (`requirements.txt`만 읽어 streamlit/pandas/openpyxl 설치 → nicegui 미설치)
5. repo 에 실제 데이터가 없으므로 클라우드 앱은 `example_inventory.csv` 로 구동된다.
   실데이터는 앱 사이드바의 **수동 업로드**로 올려서 본다(공개 앱엔 실데이터 상주 금지).

## 실시간 재고 연동 (사방넷 → 비공개 시트 → 앱)
> 앱이 사방넷을 직접 긁지 않는다. **수집과 표시를 분리**한다.
```
[collector.py]  사방넷 풀필먼트 ──Playwright 로그인+엑셀 다운──▶ 정규화
   │ (로컬/스케줄러, 30분~1h)        (sabang_auto 로그인 패턴 재사용)
   ▼
[비공개 Google Sheet]  ◀── 서비스계정 1개로 수집기 write / 앱 read
   ▲
[app_streamlit.py]  live.read_inventory() · 10분 캐시 · 🔄새로고침 · 마지막 갱신시각
```

**준비 절차**
1. **서비스계정 생성**: GCP 콘솔 → 서비스계정 만들기 → JSON 키 다운로드 → Google Sheets API 사용 설정.
2. **비공개 시트 생성** 후 서비스계정 이메일(`xxx@xxx.iam.gserviceaccount.com`)을 **편집자**로 공유.
3. **앱(클라우드)**: Streamlit Cloud → App settings → Secrets 에 `secrets.toml.example` 형식으로 SA 키와 `[sheet] id/tab` 입력.
4. **수집기(로컬)**: `secrets/service_account.json` 배치 + `.env`(.env.example 참고) 채우기.
   ```bash
   pip install -r requirements-collector.txt
   playwright install chromium
   python collector.py --discover   # 사방넷 재고 페이지/다운로드 버튼 셀렉터 확인
   python collector.py              # 1회 수집·적재
   ```
5. **스케줄링**: Windows 작업 스케줄러로 `python collector.py` 를 30분~1시간 주기 등록
   (Ecount/사방넷자동등록 봇과 동일 방식).

**남은 구현 한 곳**: `collector.download_location_inventory()` — 사방넷 재고/로케이션
조회 페이지 URL과 엑셀 내보내기 셀렉터가 확정되면 채운다(`--discover` 로 탐색).

## 데이터 넣는 법 (3가지)
1. **샘플 데이터** — 시트에서 뽑은 sample_inventory.csv (기본).
2. **수동 업로드** — 사방넷에서 받은 csv/xlsx 를 드래그&드롭.
   - 인식 컬럼: `로케이션명 / 상품코드 / 출고상품명 / 유통기한 / 상품 합계 수량`
     (별칭도 다수 허용 — `warehouse.COLUMN_ALIASES` 참고)
3. **사방넷 자동 수집** — 지금은 스텁(`warehouse.fetch_from_sabang`).
   자격증명 연결 시 둘 중 하나로 채우면 됨:
   - 사방넷 OpenAPI 있으면 `requests` 호출
   - 없으면 기존 Ecount 알람봇처럼 **Playwright 로그인→재고 엑셀 다운로드→pandas**

## 색상 모드
- **품목**: 품목군(초코바·요거트바·콘·모나카…)별 고유색 → 무엇이 어디 모였나
- **재고수량**: 연하늘→진파랑 농도 → 적재 밀도
- **유통기한**: 가장 임박한 로트 D-day → 경과(진빨강)·≤30(빨강)·≤60(주황)·≤120(노랑)·여유(초록)·기한없음(회색)

## 알아둘 점 / 다음 단계
- 현재 격자는 **데이터에 존재하는 로케이션만** 그린다(베이 수는 랙별 최댓값으로 자동).
  비어 있어도 "물리적으로 존재하는 슬롯"까지 표시하려면 랙별 베이 수 정의(슬롯 마스터)가 필요.
- `비상구(E/V홀)`, `4F`, `◀A04` 같은 시트의 물리 구조 표식은 아직 미반영(원하면 추가).
- 유통기한이 빈 품목(베이글 등)은 회색 처리.
- 샘플의 D-day가 음수로 많이 나오는 건 추출 시점 데이터가 과거(2025년 제조분)라서 정상.
