import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import feedparser
import urllib.parse
import requests
import zipfile
import xml.etree.ElementTree as ET
import io
import json
import os
import smtplib
import re as _re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from openai import OpenAI

CONFIG_FILE = "config.json"

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_config(data: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

st.set_page_config(
    page_title="국내 주식 대시보드",
    page_icon="📈",
    layout="wide"
)

STOCKS = {
    "삼성전자": "005930.KS",
    "SK하이닉스": "000660.KS",
    "LG에너지솔루션": "373220.KS",
    "현대차": "005380.KS",
    "삼성바이오로직스": "207940.KS",
    "NAVER": "035420.KS",
    "카카오": "035720.KS",
    "POSCO홀딩스": "005490.KS",
    "KB금융": "105560.KS",
    "셀트리온": "068270.KS",
}

# OpenDART 고유번호 (corpCode) 매핑 — DART 기업코드 기준
DART_CORP_CODE = {
    "삼성전자":        "00126380",
    "SK하이닉스":      "00164779",
    "LG에너지솔루션":  "01515323",
    "현대차":          "00164742",
    "삼성바이오로직스": "00877059",
    "NAVER":           "00266961",
    "카카오":          "00258801",
    "POSCO홀딩스":     "00155319",
    "KB금융":          "00688996",
    "셀트리온":        "00413046",
}

# 공시 유형 코드
DART_REPORT_TYPE = {
    "전체": "",
    "정기공시": "A",
    "주요사항보고": "B",
    "발행공시": "C",
    "지분공시": "D",
    "기타공시": "E",
    "외부감사관련": "F",
    "펀드공시": "G",
    "자산유동화": "H",
    "거래소공시": "I",
    "공정위공시": "J",
}

# 구글 뉴스 검색어 매핑 (영문 티커보다 한국어 검색이 정확)
NEWS_QUERY = {
    "삼성전자": "삼성전자 주식",
    "SK하이닉스": "SK하이닉스 주식",
    "LG에너지솔루션": "LG에너지솔루션 주식",
    "현대차": "현대자동차 주식",
    "삼성바이오로직스": "삼성바이오로직스 주식",
    "NAVER": "네이버 주식",
    "카카오": "카카오 주식",
    "POSCO홀딩스": "POSCO홀딩스 주식",
    "KB금융": "KB금융 주식",
    "셀트리온": "셀트리온 주식",
}

st.title("📈 국내 주식 대시보드")
st.markdown("---")

# ── 저장된 API 키 초기 로드 (세션 최초 1회) ──────────────────────────────
if "config_loaded" not in st.session_state:
    # 우선순위: st.secrets (클라우드) > config.json (로컬)
    _cfg = load_config()
    for _k in ("openai_api_key", "dart_api_key", "smtp_email", "smtp_app_password", "smtp_provider"):
        try:
            val = st.secrets.get(_k)  # Streamlit Cloud secrets 우선
        except Exception:
            val = None
        if not val:
            val = _cfg.get(_k)        # 로컬 config.json 폴백
        if val:
            st.session_state[_k] = val
    st.session_state["config_loaded"] = True

# ── 사이드바 ──────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 설정")

    # ── OpenAI API Key ────────────────────────────────────────────────
    st.subheader("🤖 AI 챗봇 설정")
    openai_saved = bool(st.session_state.get("openai_api_key"))
    if openai_saved:
        st.success("OpenAI API Key 저장됨", icon="✅")
        if st.button("OpenAI Key 변경 / 삭제", key="openai_change_btn"):
            st.session_state["show_openai_input"] = True
    else:
        st.session_state["show_openai_input"] = True

    if st.session_state.get("show_openai_input"):
        new_openai_key = st.text_input(
            "OpenAI API Key",
            type="password",
            placeholder="sk-...",
            value="",
            key="openai_key_input",
        )
        oc1, oc2 = st.columns(2)
        with oc1:
            if st.button("저장", key="openai_save_btn", use_container_width=True):
                if new_openai_key.strip():
                    st.session_state["openai_api_key"] = new_openai_key.strip()
                    _cfg = load_config()
                    _cfg["openai_api_key"] = new_openai_key.strip()
                    save_config(_cfg)
                    st.session_state["show_openai_input"] = False
                    st.rerun()
                else:
                    st.warning("키를 입력해주세요.")
        with oc2:
            if st.button("삭제", key="openai_del_btn", use_container_width=True):
                st.session_state.pop("openai_api_key", None)
                st.session_state["show_openai_input"] = False
                _cfg = load_config()
                _cfg.pop("openai_api_key", None)
                save_config(_cfg)
                st.rerun()

    st.markdown("---")

    # ── DART API Key ──────────────────────────────────────────────────
    st.subheader("🏛️ OpenDART 설정")
    dart_saved = bool(st.session_state.get("dart_api_key"))
    if dart_saved:
        st.success("DART API Key 저장됨", icon="✅")
        if st.button("DART Key 변경 / 삭제", key="dart_change_btn"):
            st.session_state["show_dart_input"] = True
    else:
        st.session_state["show_dart_input"] = True

    if st.session_state.get("show_dart_input"):
        new_dart_key = st.text_input(
            "OpenDART API Key",
            type="password",
            placeholder="발급받은 인증키 입력",
            value="",
            key="dart_key_input",
        )
        dc1, dc2 = st.columns(2)
        with dc1:
            if st.button("저장", key="dart_save_btn", use_container_width=True):
                if new_dart_key.strip():
                    st.session_state["dart_api_key"] = new_dart_key.strip()
                    _cfg = load_config()
                    _cfg["dart_api_key"] = new_dart_key.strip()
                    save_config(_cfg)
                    st.session_state["show_dart_input"] = False
                    st.rerun()
                else:
                    st.warning("키를 입력해주세요.")
        with dc2:
            if st.button("삭제", key="dart_del_btn", use_container_width=True):
                st.session_state.pop("dart_api_key", None)
                st.session_state["show_dart_input"] = False
                _cfg = load_config()
                _cfg.pop("dart_api_key", None)
                save_config(_cfg)
                st.rerun()

    st.markdown("---")

    # ── 이메일(SMTP) 설정 ────────────────────────────────────────────
    st.subheader("📧 이메일 설정")
    email_saved = bool(st.session_state.get("smtp_email") and st.session_state.get("smtp_app_password"))
    if email_saved:
        st.success(f"이메일 저장됨: {st.session_state['smtp_email']}", icon="✅")
        if st.button("이메일 설정 변경 / 삭제", key="email_change_btn"):
            st.session_state["show_email_input"] = True
    else:
        st.session_state["show_email_input"] = True

    if st.session_state.get("show_email_input"):
        smtp_provider = st.selectbox(
            "메일 서비스",
            ["Gmail", "Naver", "Kakao", "Daum", "직접 입력"],
            key="smtp_provider_select",
        )
        if smtp_provider == "직접 입력":
            smtp_host_val = st.text_input("SMTP 서버", placeholder="smtp.example.com", key="smtp_host_custom")
            smtp_port_val = st.number_input("SMTP 포트", value=587, key="smtp_port_custom")
        else:
            smtp_host_val = ""
            smtp_port_val = 0

        em1, em2 = st.columns([1, 1])
        with em1:
            new_smtp_email = st.text_input("계정 (이메일)", placeholder="example@gmail.com", key="smtp_email_input")
        with em2:
            new_smtp_pw = st.text_input("앱 비밀번호", type="password", placeholder="앱 비밀번호 입력", key="smtp_pw_input",
                help="Gmail: Google 계정 → 보안 → 앱 비밀번호 생성")

        eb1, eb2 = st.columns(2)
        with eb1:
            if st.button("저장", key="email_save_btn", use_container_width=True):
                if new_smtp_email.strip() and new_smtp_pw.strip():
                    st.session_state["smtp_email"] = new_smtp_email.strip()
                    st.session_state["smtp_app_password"] = new_smtp_pw.strip()
                    st.session_state["smtp_provider"] = smtp_provider
                    if smtp_provider == "직접 입력":
                        st.session_state["smtp_host_custom"] = smtp_host_val
                        st.session_state["smtp_port_custom"] = int(smtp_port_val)
                    _cfg = load_config()
                    _cfg["smtp_email"] = new_smtp_email.strip()
                    _cfg["smtp_app_password"] = new_smtp_pw.strip()
                    _cfg["smtp_provider"] = smtp_provider
                    if smtp_provider == "직접 입력":
                        _cfg["smtp_host_custom"] = smtp_host_val
                        _cfg["smtp_port_custom"] = int(smtp_port_val)
                    save_config(_cfg)
                    st.session_state["show_email_input"] = False
                    st.rerun()
                else:
                    st.warning("이메일과 앱 비밀번호를 모두 입력해주세요.")
        with eb2:
            if st.button("삭제", key="email_del_btn", use_container_width=True):
                for _k in ("smtp_email", "smtp_app_password", "smtp_provider"):
                    st.session_state.pop(_k, None)
                st.session_state["show_email_input"] = False
                _cfg = load_config()
                for _k in ("smtp_email", "smtp_app_password", "smtp_provider", "smtp_host_custom", "smtp_port_custom"):
                    _cfg.pop(_k, None)
                save_config(_cfg)
                st.rerun()

    st.markdown("---")

    period_map = {
        "1개월": "1mo",
        "3개월": "3mo",
        "6개월": "6mo",
        "1년": "1y",
        "2년": "2y",
    }
    selected_period_label = st.selectbox("조회 기간", list(period_map.keys()), index=2)
    selected_period = period_map[selected_period_label]

    selected_stocks = st.multiselect(
        "종목 선택",
        list(STOCKS.keys()),
        default=list(STOCKS.keys())[:5],
    )

    interval_map = {"일봉": "1d", "주봉": "1wk", "월봉": "1mo"}
    selected_interval_label = st.selectbox("봉 종류", list(interval_map.keys()))
    selected_interval = interval_map[selected_interval_label]

    st.markdown("---")
    st.caption("데이터 출처: Yahoo Finance / Google News")


# ── 데이터 수집 ───────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def fetch_all_stocks(period, interval):
    tickers = list(STOCKS.values())
    data = yf.download(tickers, period=period, interval=interval, auto_adjust=True, progress=False)
    return data


@st.cache_data(ttl=300)
def fetch_ohlcv(ticker, period, interval):
    return yf.download(ticker, period=period, interval=interval, auto_adjust=True, progress=False)


@st.cache_data(ttl=3600)
def load_corpcode_df():
    """corpcode.csv를 로드하고 상장 종목(stock_code 있는 것) 우선 반환."""
    df = pd.read_csv("corpcode.csv", dtype=str).fillna("")
    # stock_code가 있는 상장사 우선 정렬
    df["listed"] = df["stock_code"].apply(lambda x: 0 if x.strip() else 1)
    df = df.sort_values(["listed", "corp_name"]).drop(columns=["listed"])
    return df


def search_corpcode(query: str, df: pd.DataFrame, max_results: int = 50):
    """기업명 또는 종목코드로 검색."""
    q = query.strip()
    if not q:
        return df[df["stock_code"] != ""].head(max_results)
    mask = (
        df["corp_name"].str.contains(q, case=False, na=False) |
        df["stock_code"].str.contains(q, case=False, na=False)
    )
    return df[mask].head(max_results)


@st.cache_data(ttl=1800)
def fetch_dart_disclosures(api_key: str, corp_code: str, bgn_de: str, end_de: str,
                           pblntf_ty: str = "", page_no: int = 1, page_count: int = 20):
    """OpenDART 공시목록 API 호출."""
    url = "https://opendart.fss.or.kr/api/list.json"
    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bgn_de": bgn_de,
        "end_de": end_de,
        "pblntf_ty": pblntf_ty,
        "page_no": page_no,
        "page_count": page_count,
        "sort": "date",
        "sort_mth": "desc",
    }
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


@st.cache_data(ttl=1800)
def fetch_dart_company_info(api_key: str, corp_code: str):
    """OpenDART 기업개황 API 호출."""
    url = "https://opendart.fss.or.kr/api/company.json"
    params = {"crtfc_key": api_key, "corp_code": corp_code}
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


@st.cache_data(ttl=1800)
def fetch_dart_financial(api_key: str, corp_code: str, bsns_year: str, reprt_code: str):
    """OpenDART 단일회사 주요계정 API 호출."""
    url = "https://opendart.fss.or.kr/api/fnlttSinglAcnt.json"
    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bsns_year": bsns_year,
        "reprt_code": reprt_code,
    }
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


@st.cache_data(ttl=600)
def fetch_google_news(query: str, max_items: int = 10):
    """Google News RSS로 한국어 뉴스를 수집합니다."""
    encoded = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=ko&gl=KR&ceid=KR:ko"
    feed = feedparser.parse(url)
    articles = []
    for entry in feed.entries[:max_items]:
        # 발행일 파싱
        try:
            pub = datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d %H:%M")
        except Exception:
            pub = "날짜 불명"
        # Google News RSS는 source를 title에 포함 " - 매체명" 형식
        title = entry.get("title", "제목 없음")
        source = ""
        if " - " in title:
            parts = title.rsplit(" - ", 1)
            title = parts[0].strip()
            source = parts[1].strip()
        articles.append({
            "title": title,
            "source": source,
            "published": pub,
            "link": entry.get("link", "#"),
            "summary": entry.get("summary", ""),
        })
    return articles


@st.cache_data(ttl=600)
def fetch_yfinance_news(ticker: str, max_items: int = 5):
    """yfinance로 영문 뉴스를 수집합니다."""
    try:
        t = yf.Ticker(ticker)
        news_list = t.news or []
        articles = []
        for item in news_list[:max_items]:
            content = item.get("content", {})
            title = content.get("title", item.get("title", "제목 없음"))
            pub_ts = content.get("pubDate", "")
            try:
                if pub_ts:
                    pub = datetime.fromisoformat(pub_ts.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
                else:
                    pub = "날짜 불명"
            except Exception:
                pub = "날짜 불명"
            provider = content.get("provider", {})
            source = provider.get("displayName", "") if isinstance(provider, dict) else ""
            link = ""
            click_through = content.get("clickThroughUrl", {})
            if isinstance(click_through, dict):
                link = click_through.get("url", "")
            if not link:
                canonical = content.get("canonicalUrl", {})
                if isinstance(canonical, dict):
                    link = canonical.get("url", "#")
            articles.append({
                "title": title,
                "source": source,
                "published": pub,
                "link": link or "#",
                "summary": content.get("summary", ""),
            })
        return articles
    except Exception:
        return []


with st.spinner("주식 데이터 불러오는 중..."):
    raw_data = fetch_all_stocks(selected_period, selected_interval)

if raw_data.empty:
    st.error("데이터를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.")
    st.stop()

close_data = raw_data["Close"] if "Close" in raw_data.columns else raw_data.xs("Close", axis=1, level=0)


# ── 챗봇용 주식 컨텍스트 생성 ─────────────────────────────────────────────
def build_stock_context(period_label: str) -> str:
    lines = [
        f"아래는 국내 주요 주식 10종목의 최근 {period_label} 데이터 요약입니다.",
        f"기준일: {datetime.today().strftime('%Y년 %m월 %d일')}",
        "",
        "| 종목 | 최근 종가(원) | 전일 대비 | 기간 수익률 |",
        "|------|-------------|---------|------------|",
    ]
    for name, ticker in STOCKS.items():
        try:
            series = close_data[ticker].dropna()
            if len(series) < 2:
                continue
            current = series.iloc[-1]
            prev = series.iloc[-2]
            day_chg = (current - prev) / prev * 100
            period_ret = (series.iloc[-1] / series.iloc[0] - 1) * 100
            lines.append(f"| {name} | {current:,.0f} | {day_chg:+.2f}% | {period_ret:+.2f}% |")
        except Exception:
            pass

    lines += ["", "[ 기간 내 고가/저가 ]"]
    high_data = raw_data["High"] if "High" in raw_data.columns else raw_data.xs("High", axis=1, level=0)
    low_data = raw_data["Low"] if "Low" in raw_data.columns else raw_data.xs("Low", axis=1, level=0)
    for name, ticker in STOCKS.items():
        try:
            high = high_data[ticker].dropna().max()
            low = low_data[ticker].dropna().min()
            lines.append(f"  {name}: 고가 {high:,.0f}원 / 저가 {low:,.0f}원")
        except Exception:
            pass
    return "\n".join(lines)


SYSTEM_PROMPT = """당신은 국내 주식 전문 AI 어시스턴트입니다.
사용자가 제공한 실제 주식 데이터와 최신 뉴스를 바탕으로 질문에 답변합니다.
- 데이터에 없는 내용은 추측하지 말고 "데이터에 포함되지 않은 정보입니다"라고 답하세요.
- 뉴스 기사 내용을 인용할 때는 출처 매체명을 함께 밝혀주세요.
- 투자 조언은 참고 정보로만 제공하고, 실제 투자 결정은 사용자 본인이 해야 함을 명시하세요.
- 답변은 한국어로 작성하고, 숫자는 쉼표 구분 형식으로 표시하세요.
- 친절하고 명확하게 답변하세요."""


def build_news_context(stock_names: list, max_per_stock: int = 5) -> str:
    """선택된 종목의 최신 뉴스를 텍스트 컨텍스트로 변환합니다."""
    lines = [f"아래는 최신 뉴스 헤드라인입니다. (수집 시각: {datetime.today().strftime('%Y-%m-%d %H:%M')})"]
    for name in stock_names:
        articles = fetch_google_news(NEWS_QUERY[name], max_items=max_per_stock)
        if not articles:
            continue
        lines.append(f"\n### {name} 관련 뉴스")
        for i, a in enumerate(articles, 1):
            source = f"[{a['source']}]" if a["source"] else ""
            lines.append(f"{i}. {a['title']} {source} ({a['published']})")
            lines.append(f"   링크: {a['link']}")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════
# 메인 탭 구성
# ══════════════════════════════════════════════════════════════════════════
tab_dashboard, tab_news, tab_dart, tab_chat, tab_report = st.tabs([
    "📊 대시보드",
    "📰 기업 뉴스",
    "🏛️ 공시 정보 (DART)",
    "🤖 AI 챗봇",
    "📧 보고서 발송",
])

# ────────────────────────────────────────────────────────────────────────
# TAB 1 : 대시보드
# ────────────────────────────────────────────────────────────────────────
with tab_dashboard:
    st.subheader("📊 종목 현황")
    cols = st.columns(5)
    for i, name in enumerate(list(STOCKS.keys())[:10]):
        ticker = STOCKS[name]
        col = cols[i % 5]
        try:
            series = close_data[ticker].dropna()
            if len(series) < 2:
                raise ValueError
            current = series.iloc[-1]
            prev = series.iloc[-2]
            change_pct = (current - prev) / prev * 100
            col.metric(label=name, value=f"{current:,.0f}원", delta=f"{change_pct:+.2f}%")
        except Exception:
            col.metric(label=name, value="N/A", delta=None)

    st.markdown("---")

    if selected_stocks:
        st.subheader("📉 주가 추이 비교")
        ctab1, ctab2 = st.tabs(["원가격", "등락률 (%)"])

        with ctab1:
            fig = go.Figure()
            for name in selected_stocks:
                ticker = STOCKS[name]
                try:
                    series = close_data[ticker].dropna()
                    fig.add_trace(go.Scatter(x=series.index, y=series.values, mode="lines", name=name))
                except Exception:
                    pass
            fig.update_layout(xaxis_title="날짜", yaxis_title="주가 (원)", hovermode="x unified",
                              height=450, legend=dict(orientation="h", y=-0.2))
            st.plotly_chart(fig, use_container_width=True)

        with ctab2:
            fig2 = go.Figure()
            for name in selected_stocks:
                ticker = STOCKS[name]
                try:
                    series = close_data[ticker].dropna()
                    pct = (series / series.iloc[0] - 1) * 100
                    fig2.add_trace(go.Scatter(x=pct.index, y=pct.values, mode="lines", name=name))
                except Exception:
                    pass
            fig2.add_hline(y=0, line_dash="dash", line_color="gray")
            fig2.update_layout(xaxis_title="날짜", yaxis_title="수익률 (%)", hovermode="x unified",
                               height=450, legend=dict(orientation="h", y=-0.2))
            st.plotly_chart(fig2, use_container_width=True)

        st.markdown("---")

        st.subheader("🕯️ 개별 종목 캔들차트")
        stock_choice = st.selectbox("종목 선택", selected_stocks, key="candle_select")
        ticker_choice = STOCKS[stock_choice]
        ohlcv = fetch_ohlcv(ticker_choice, selected_period, selected_interval)

        if not ohlcv.empty:
            if isinstance(ohlcv.columns, pd.MultiIndex):
                ohlcv.columns = ohlcv.columns.get_level_values(0)
            fig3 = go.Figure(data=[go.Candlestick(
                x=ohlcv.index,
                open=ohlcv["Open"], high=ohlcv["High"],
                low=ohlcv["Low"], close=ohlcv["Close"],
                name=stock_choice,
                increasing_line_color="#FF4B4B",
                decreasing_line_color="#1976D2",
            )])
            vol_colors = ["#FF4B4B" if c >= o else "#1976D2"
                          for c, o in zip(ohlcv["Close"], ohlcv["Open"])]
            fig3.add_trace(go.Bar(x=ohlcv.index, y=ohlcv["Volume"], name="거래량",
                                  marker_color=vol_colors, opacity=0.4, yaxis="y2"))
            fig3.update_layout(
                title=f"{stock_choice} ({ticker_choice})",
                xaxis_title="날짜", yaxis_title="주가 (원)",
                yaxis2=dict(title="거래량", overlaying="y", side="right", showgrid=False),
                xaxis_rangeslider_visible=False, height=500,
            )
            st.plotly_chart(fig3, use_container_width=True)

        st.markdown("---")

    st.subheader("🗺️ 수익률 히트맵")
    returns_dict = {}
    for name, ticker in STOCKS.items():
        try:
            series = close_data[ticker].dropna()
            if len(series) >= 2:
                returns_dict[name] = round((series.iloc[-1] / series.iloc[0] - 1) * 100, 2)
        except Exception:
            pass

    if returns_dict:
        ret_df = pd.DataFrame.from_dict(returns_dict, orient="index", columns=["수익률(%)"]).sort_values("수익률(%)", ascending=False)
        colors = ["#FF4B4B" if v >= 0 else "#1976D2" for v in ret_df["수익률(%)"]]
        fig4 = go.Figure(go.Bar(
            x=ret_df.index, y=ret_df["수익률(%)"],
            marker_color=colors,
            text=[f"{v:+.2f}%" for v in ret_df["수익률(%)"]],
            textposition="outside",
        ))
        fig4.add_hline(y=0, line_dash="dash", line_color="gray")
        fig4.update_layout(xaxis_title="종목", yaxis_title="수익률 (%)", height=400)
        st.plotly_chart(fig4, use_container_width=True)

    st.markdown("---")

    st.subheader("📋 종가 데이터 테이블")
    rename_map = {v: k for k, v in STOCKS.items()}
    display_df = close_data.rename(columns=rename_map)
    display_df.index = pd.to_datetime(display_df.index).strftime("%Y-%m-%d")
    display_df = display_df.iloc[::-1]
    st.dataframe(display_df.style.format("{:,.0f}"), use_container_width=True, height=300)

    csv = display_df.to_csv(encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button(
        label="📥 CSV 다운로드",
        data=csv,
        file_name=f"korean_stocks_{datetime.today().strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )


# ────────────────────────────────────────────────────────────────────────
# TAB 2 : 기업 뉴스
# ────────────────────────────────────────────────────────────────────────
with tab_news:
    st.subheader("📰 기업 관련 뉴스")
    st.caption("Google News RSS(한국어) 및 Yahoo Finance 뉴스를 실시간으로 수집합니다. 캐시: 10분")

    news_col1, news_col2 = st.columns([2, 1])
    with news_col1:
        news_stock = st.selectbox("종목 선택", list(STOCKS.keys()), key="news_stock_select")
    with news_col2:
        news_count = st.slider("뉴스 수", min_value=5, max_value=20, value=10, step=5)

    if st.button("🔄 뉴스 새로고침", use_container_width=False):
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")

    ntab_ko, ntab_en = st.tabs(["🇰🇷 한국 뉴스 (Google News)", "🌐 글로벌 뉴스 (Yahoo Finance)"])

    with ntab_ko:
        query = NEWS_QUERY[news_stock]
        with st.spinner(f"'{news_stock}' 관련 한국 뉴스 수집 중..."):
            ko_articles = fetch_google_news(query, max_items=news_count)

        if not ko_articles:
            st.info("뉴스를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.")
        else:
            for i, article in enumerate(ko_articles):
                with st.container():
                    c1, c2 = st.columns([5, 1])
                    with c1:
                        st.markdown(f"#### [{article['title']}]({article['link']})")
                        meta_parts = []
                        if article["source"]:
                            meta_parts.append(f"**{article['source']}**")
                        meta_parts.append(article["published"])
                        st.caption("  |  ".join(meta_parts))
                        if article["summary"]:
                            # summary에 HTML 태그 제거
                            import re
                            clean_summary = re.sub(r"<[^>]+>", "", article["summary"])
                            if clean_summary.strip():
                                st.write(clean_summary[:200] + ("..." if len(clean_summary) > 200 else ""))
                    with c2:
                        st.link_button("기사 보기", article["link"], use_container_width=True)
                if i < len(ko_articles) - 1:
                    st.divider()

    with ntab_en:
        ticker_for_news = STOCKS[news_stock]
        with st.spinner(f"'{news_stock}' 관련 글로벌 뉴스 수집 중..."):
            en_articles = fetch_yfinance_news(ticker_for_news, max_items=news_count)

        if not en_articles:
            st.info("Yahoo Finance 뉴스를 불러오지 못했습니다.")
        else:
            for i, article in enumerate(en_articles):
                with st.container():
                    c1, c2 = st.columns([5, 1])
                    with c1:
                        st.markdown(f"#### [{article['title']}]({article['link']})")
                        meta_parts = []
                        if article["source"]:
                            meta_parts.append(f"**{article['source']}**")
                        meta_parts.append(article["published"])
                        st.caption("  |  ".join(meta_parts))
                        if article["summary"]:
                            st.write(article["summary"][:200] + ("..." if len(article["summary"]) > 200 else ""))
                    with c2:
                        if article["link"] and article["link"] != "#":
                            st.link_button("기사 보기", article["link"], use_container_width=True)
                if i < len(en_articles) - 1:
                    st.divider()

    # ── 전 종목 최신 뉴스 헤드라인 요약 ─────────────────────────────────
    st.markdown("---")
    st.subheader("📋 전 종목 최신 헤드라인")
    st.caption("각 종목의 Google News 최신 뉴스 1건씩 표시합니다.")

    if st.button("전 종목 헤드라인 불러오기", use_container_width=False):
        rows = []
        prog = st.progress(0, text="뉴스 수집 중...")
        total = len(STOCKS)
        for idx, (name, _) in enumerate(STOCKS.items()):
            articles = fetch_google_news(NEWS_QUERY[name], max_items=1)
            if articles:
                a = articles[0]
                rows.append({
                    "종목": name,
                    "헤드라인": a["title"],
                    "매체": a["source"],
                    "일시": a["published"],
                    "링크": a["link"],
                })
            prog.progress((idx + 1) / total, text=f"{name} 수집 완료...")
        prog.empty()

        if rows:
            headline_df = pd.DataFrame(rows)
            st.dataframe(
                headline_df,
                column_config={
                    "링크": st.column_config.LinkColumn("링크", display_text="기사 보기"),
                },
                use_container_width=True,
                hide_index=True,
            )


# ────────────────────────────────────────────────────────────────────────
# TAB 3 : 공시 정보 (OpenDART)
# ────────────────────────────────────────────────────────────────────────
with tab_dart:
    st.subheader("🏛️ OpenDART 공시 정보")
    st.caption("금융감독원 전자공시시스템(DART) API를 통해 기업 공시를 조회합니다.")

    has_dart_key = bool(st.session_state.get("dart_api_key"))

    if not has_dart_key:
        st.warning("사이드바에서 OpenDART API Key를 입력하면 공시 조회가 활성화됩니다.", icon="🏛️")
        st.markdown("""
        **DART API Key 발급 방법**
        1. [DART 오픈API](https://opendart.fss.or.kr/uss/umt/EgovMberInsertView.do) 회원가입
        2. 마이페이지 → API 신청 → 인증키 발급
        3. 발급된 인증키를 사이드바에 입력
        """)
    else:
        dart_key = st.session_state["dart_api_key"]
        dart_subtab_list, dart_subtab_company, dart_subtab_fin = st.tabs([
            "📋 공시 목록", "🏢 기업 개황", "💰 주요 재무"
        ])

        # corpcode.csv 로드
        corpcode_df = load_corpcode_df()

        # ── 공시 목록 ──────────────────────────────────────────────────
        with dart_subtab_list:
            st.markdown("#### 공시 목록 조회")

            # 종목 선택 방식
            search_mode = st.radio(
                "종목 선택 방식",
                ["대시보드 종목 (10개)", "전체 기업 검색"],
                horizontal=True,
                key="dart_search_mode",
            )

            selected_corp_code = None
            selected_corp_name = None

            if search_mode == "대시보드 종목 (10개)":
                dart_stock = st.selectbox("종목", list(DART_CORP_CODE.keys()), key="dart_stock")
                selected_corp_code = DART_CORP_CODE[dart_stock]
                selected_corp_name = dart_stock
            else:
                sc1, sc2 = st.columns([3, 1])
                with sc1:
                    search_query = st.text_input("기업명 또는 종목코드 검색", placeholder="예: 삼성, 035420", key="dart_corp_search")
                with sc2:
                    st.markdown("<br>", unsafe_allow_html=True)

                results = search_corpcode(search_query if search_query else "", corpcode_df)
                if not results.empty:
                    options = [
                        f"{row['corp_name']}  ({row['stock_code'] if row['stock_code'] else '비상장'})  [{row['corp_code']}]"
                        for _, row in results.iterrows()
                    ]
                    chosen = st.selectbox("검색 결과", options, key="dart_corp_result")
                    if chosen:
                        selected_corp_code = chosen.split("[")[-1].rstrip("]").strip()
                        selected_corp_name = chosen.split("  ")[0].strip()
                else:
                    st.info("검색 결과가 없습니다.")

            dc2, dc3, dc4 = st.columns([2, 2, 1])
            with dc2:
                dart_rpt_type = st.selectbox("공시 유형", list(DART_REPORT_TYPE.keys()), key="dart_rpt_type")
            with dc3:
                date_range = st.date_input(
                    "조회 기간",
                    value=(datetime.today() - timedelta(days=90), datetime.today()),
                    max_value=datetime.today(),
                    key="dart_date_range",
                )
            with dc4:
                dart_page_count = st.selectbox("건수", [10, 20, 40], index=1, key="dart_page_count")

            if st.button("🔍 공시 조회", use_container_width=False, key="dart_search_btn"):
                if not selected_corp_code:
                    st.warning("종목을 선택해주세요.")
                    st.stop()
                try:
                    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
                        bgn = date_range[0].strftime("%Y%m%d")
                        end = date_range[1].strftime("%Y%m%d")
                    else:
                        bgn = (datetime.today() - timedelta(days=90)).strftime("%Y%m%d")
                        end = datetime.today().strftime("%Y%m%d")

                    corp_code = selected_corp_code
                    pblntf_ty = DART_REPORT_TYPE[dart_rpt_type]

                    with st.spinner("DART에서 공시 목록을 불러오는 중..."):
                        result = fetch_dart_disclosures(
                            dart_key, corp_code, bgn, end,
                            pblntf_ty=pblntf_ty, page_count=dart_page_count
                        )

                    status = result.get("status", "")
                    if status == "000":
                        items = result.get("list", [])
                        total_count = result.get("total_count", 0)
                        st.success(f"총 **{total_count}건** 공시 조회 완료 (최대 {dart_page_count}건 표시)")

                        if items:
                            rows = []
                            for item in items:
                                rcept_no = item.get("rcept_no", "")
                                dart_link = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
                                rows.append({
                                    "접수일": item.get("rcept_dt", ""),
                                    "공시 제목": item.get("report_nm", ""),
                                    "제출인": item.get("flr_nm", ""),
                                    "비고": item.get("rm", ""),
                                    "링크": dart_link,
                                })
                            disc_df = pd.DataFrame(rows)
                            st.dataframe(
                                disc_df,
                                column_config={
                                    "링크": st.column_config.LinkColumn("원문 보기", display_text="DART 바로가기"),
                                    "접수일": st.column_config.TextColumn("접수일", width="small"),
                                    "공시 제목": st.column_config.TextColumn("공시 제목", width="large"),
                                },
                                use_container_width=True,
                                hide_index=True,
                                height=500,
                            )
                            # CSV 다운로드
                            csv_dart = disc_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
                            st.download_button(
                                "📥 공시 목록 CSV 다운로드", csv_dart,
                                file_name=f"dart_{selected_corp_name}_{bgn}_{end}.csv",
                                mime="text/csv",
                            )
                        else:
                            st.info("조회된 공시가 없습니다.")
                    elif status == "010":
                        st.error("등록되지 않은 API 키입니다. DART API Key를 확인해주세요.")
                    elif status == "020":
                        st.error("요청 건수가 일일 한도를 초과했습니다.")
                    else:
                        msg = result.get("message", "알 수 없는 오류")
                        st.error(f"DART API 오류 [{status}]: {msg}")

                except requests.exceptions.Timeout:
                    st.error("DART 서버 응답 시간이 초과되었습니다. 잠시 후 다시 시도해주세요.")
                except Exception as e:
                    st.error(f"오류 발생: {e}")

        # ── 기업 개황 ──────────────────────────────────────────────────
        with dart_subtab_company:
            st.markdown("#### 기업 개황")
            ci_mode = st.radio("종목 선택 방식", ["대시보드 종목 (10개)", "전체 기업 검색"],
                               horizontal=True, key="dart_ci_mode")
            ci_corp_code = None
            if ci_mode == "대시보드 종목 (10개)":
                ci_col1, ci_col2 = st.columns([3, 1])
                with ci_col1:
                    ci_stock = st.selectbox("종목", list(DART_CORP_CODE.keys()), key="dart_ci_stock")
                ci_corp_code = DART_CORP_CODE[ci_stock]
            else:
                ci_sq = st.text_input("기업명 또는 종목코드 검색", placeholder="예: 카카오, 035720", key="dart_ci_search")
                ci_results = search_corpcode(ci_sq if ci_sq else "", corpcode_df)
                if not ci_results.empty:
                    ci_opts = [
                        f"{r['corp_name']}  ({r['stock_code'] if r['stock_code'] else '비상장'})  [{r['corp_code']}]"
                        for _, r in ci_results.iterrows()
                    ]
                    ci_chosen = st.selectbox("검색 결과", ci_opts, key="dart_ci_result")
                    ci_corp_code = ci_chosen.split("[")[-1].rstrip("]").strip()

            ci_col2, _ = st.columns([1, 3])
            with ci_col2:
                ci_btn = st.button("조회", use_container_width=True, key="dart_ci_btn")

            if ci_btn:
                if not ci_corp_code:
                    st.warning("종목을 선택해주세요.")
                    st.stop()
                corp_code = ci_corp_code
                with st.spinner("기업 개황을 불러오는 중..."):
                    try:
                        ci_result = fetch_dart_company_info(dart_key, corp_code)
                        if ci_result.get("status") == "000":
                            d = ci_result
                            col_l, col_r = st.columns(2)
                            with col_l:
                                st.markdown(f"**회사명:** {d.get('corp_name', '-')}")
                                st.markdown(f"**영문명:** {d.get('corp_name_eng', '-')}")
                                st.markdown(f"**종목코드:** {d.get('stock_code', '-')}")
                                st.markdown(f"**법인구분:** {d.get('corp_cls', '-')}")
                                st.markdown(f"**법인등록번호:** {d.get('jurir_no', '-')}")
                                st.markdown(f"**사업자번호:** {d.get('bizr_no', '-')}")
                            with col_r:
                                st.markdown(f"**대표이사:** {d.get('ceo_nm', '-')}")
                                st.markdown(f"**설립일:** {d.get('est_dt', '-')}")
                                st.markdown(f"**결산월:** {d.get('acc_mt', '-')}월")
                                st.markdown(f"**상장일:** {d.get('list_de', '-')}")
                                st.markdown(f"**주소:** {d.get('adres', '-')}")
                                hm = d.get("hm_url", "")
                                if hm:
                                    st.markdown(f"**홈페이지:** [{hm}]({hm})")
                        else:
                            msg = ci_result.get("message", "오류")
                            st.error(f"조회 실패: {msg}")
                    except Exception as e:
                        st.error(f"오류 발생: {e}")

        # ── 주요 재무 ──────────────────────────────────────────────────
        with dart_subtab_fin:
            st.markdown("#### 주요 재무 항목")
            st.caption("사업보고서(11011) 기준 단일회사 주요 계정을 조회합니다.")

            fn_mode = st.radio("종목 선택 방식", ["대시보드 종목 (10개)", "전체 기업 검색"],
                               horizontal=True, key="dart_fn_mode")
            fn_corp_code = None
            if fn_mode == "대시보드 종목 (10개)":
                fn_c1, fn_c2, fn_c3 = st.columns([2, 1, 1])
                with fn_c1:
                    fn_stock = st.selectbox("종목", list(DART_CORP_CODE.keys()), key="dart_fn_stock")
                fn_corp_code = DART_CORP_CODE[fn_stock]
            else:
                fn_sq = st.text_input("기업명 또는 종목코드 검색", placeholder="예: LG, 373220", key="dart_fn_search")
                fn_results = search_corpcode(fn_sq if fn_sq else "", corpcode_df)
                if not fn_results.empty:
                    fn_opts = [
                        f"{r['corp_name']}  ({r['stock_code'] if r['stock_code'] else '비상장'})  [{r['corp_code']}]"
                        for _, r in fn_results.iterrows()
                    ]
                    fn_chosen = st.selectbox("검색 결과", fn_opts, key="dart_fn_result")
                    fn_corp_code = fn_chosen.split("[")[-1].rstrip("]").strip()
                fn_c2, fn_c3 = st.columns([1, 1])

            with fn_c2:
                current_year = datetime.today().year
                fn_year = st.selectbox("사업연도", [str(y) for y in range(current_year - 1, current_year - 6, -1)], key="dart_fn_year")
            with fn_c3:
                fn_reprt = st.selectbox(
                    "보고서 종류",
                    ["사업보고서", "반기보고서", "1분기보고서", "3분기보고서"],
                    key="dart_fn_reprt",
                )
            reprt_code_map = {
                "사업보고서": "11011",
                "반기보고서": "11012",
                "1분기보고서": "11013",
                "3분기보고서": "11014",
            }

            if st.button("재무 조회", use_container_width=False, key="dart_fn_btn"):
                if not fn_corp_code:
                    st.warning("종목을 선택해주세요.")
                    st.stop()
                corp_code = fn_corp_code
                reprt_code = reprt_code_map[fn_reprt]
                with st.spinner("재무 데이터를 불러오는 중..."):
                    try:
                        fn_result = fetch_dart_financial(dart_key, corp_code, fn_year, reprt_code)
                        if fn_result.get("status") == "000":
                            fn_items = fn_result.get("list", [])
                            if fn_items:
                                fn_df = pd.DataFrame(fn_items)
                                # 필요 컬럼만 선택
                                keep_cols = ["sj_div", "sj_nm", "account_nm", "thstrm_nm",
                                             "thstrm_amount", "frmtrm_nm", "frmtrm_amount",
                                             "bfefrmtrm_nm", "bfefrmtrm_amount", "currency"]
                                fn_df = fn_df[[c for c in keep_cols if c in fn_df.columns]]
                                col_rename = {
                                    "sj_div": "재무제표구분",
                                    "sj_nm": "재무제표명",
                                    "account_nm": "계정명",
                                    "thstrm_nm": "당기",
                                    "thstrm_amount": "당기금액",
                                    "frmtrm_nm": "전기",
                                    "frmtrm_amount": "전기금액",
                                    "bfefrmtrm_nm": "전전기",
                                    "bfefrmtrm_amount": "전전기금액",
                                    "currency": "통화",
                                }
                                fn_df = fn_df.rename(columns=col_rename)
                                st.dataframe(fn_df, use_container_width=True, hide_index=True, height=500)

                                csv_fn = fn_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
                                st.download_button(
                                    "📥 재무 데이터 CSV 다운로드", csv_fn,
                                    file_name=f"dart_finance_{fn_stock}_{fn_year}.csv",
                                    mime="text/csv",
                                )
                            else:
                                st.info("조회된 재무 데이터가 없습니다. 보고서 종류나 사업연도를 변경해보세요.")
                        else:
                            msg = fn_result.get("message", "오류")
                            st.error(f"조회 실패 [{fn_result.get('status')}]: {msg}")
                    except Exception as e:
                        st.error(f"오류 발생: {e}")


# ────────────────────────────────────────────────────────────────────────
# TAB 4 : AI 챗봇
# ────────────────────────────────────────────────────────────────────────
with tab_chat:
    st.subheader("🤖 AI 주식 챗봇")
    st.caption("주식 데이터와 최신 뉴스를 결합해 GPT-4o-mini가 답변합니다.")

    has_api_key = bool(st.session_state.get("openai_api_key"))

    if not has_api_key:
        st.warning("사이드바에서 OpenAI API Key를 입력하면 챗봇을 사용할 수 있습니다.", icon="🔑")
    else:
        if "chat_messages" not in st.session_state:
            st.session_state["chat_messages"] = []

        # ── 컨텍스트 설정 ─────────────────────────────────────────────
        with st.expander("⚙️ AI 컨텍스트 설정", expanded=False):
            ctx_col1, ctx_col2 = st.columns(2)
            with ctx_col1:
                use_stock_ctx = st.checkbox("주식 데이터 포함", value=True,
                    help="수집된 종가·수익률·고가/저가 데이터를 AI에게 전달합니다.")
                use_news_ctx = st.checkbox("뉴스 포함", value=True,
                    help="선택 종목의 최신 Google News 기사 제목을 AI에게 전달합니다.")
            with ctx_col2:
                if use_news_ctx:
                    news_stocks_for_chat = st.multiselect(
                        "뉴스 수집 종목",
                        list(STOCKS.keys()),
                        default=list(STOCKS.keys())[:3],
                        help="AI에게 전달할 뉴스를 수집할 종목을 선택하세요.",
                    )
                    news_per_stock = st.slider("종목당 뉴스 수", 1, 10, 5,
                        help="많을수록 컨텍스트가 풍부해지지만 응답이 느려질 수 있습니다.")
                else:
                    news_stocks_for_chat = []
                    news_per_stock = 5

        # ── 컨텍스트 미리보기 ─────────────────────────────────────────
        if use_news_ctx and news_stocks_for_chat:
            with st.expander("📄 현재 AI에게 전달되는 뉴스 미리보기", expanded=False):
                with st.spinner("뉴스 로딩 중..."):
                    preview_news = build_news_context(news_stocks_for_chat, news_per_stock)
                st.text(preview_news[:3000] + ("\n...(이하 생략)" if len(preview_news) > 3000 else ""))

        st.markdown("---")

        # ── 예시 질문 & 초기화 ────────────────────────────────────────
        col_a, col_b = st.columns([6, 1])
        with col_b:
            if st.button("대화 초기화", use_container_width=True):
                st.session_state["chat_messages"] = []
                st.rerun()

        with col_a:
            st.markdown("**예시 질문:**")
            example_cols = st.columns(4)
            stock_examples = [
                "가장 수익률이 높은 종목은?",
                "삼성전자 최근 흐름 분석해줘",
                "하락폭이 가장 큰 종목은?",
                "포트폴리오 구성 추천해줘",
            ]
            news_examples = [
                "최근 삼성전자 뉴스 요약해줘",
                "SK하이닉스 관련 최신 이슈는?",
                "뉴스 기반으로 투자 유망 종목 추천해줘",
                "오늘 주목할 뉴스는 무엇인가요?",
            ]
            examples = news_examples if use_news_ctx else stock_examples
            for ec, ex in zip(example_cols, examples):
                if ec.button(ex, use_container_width=True, key=f"ex_{ex[:10]}"):
                    st.session_state["chat_messages"].append({"role": "user", "content": ex})
                    st.rerun()

        # ── 채팅 UI ──────────────────────────────────────────────────
        chat_container = st.container(height=400)
        with chat_container:
            if not st.session_state["chat_messages"]:
                st.info("안녕하세요! 주식 데이터와 최신 뉴스에 대해 무엇이든 물어보세요. 😊")
            for msg in st.session_state["chat_messages"]:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

        # ── 입력창 ──────────────────────────────────────────────────
        placeholder = "뉴스나 주식에 대해 질문하세요... (예: 최근 삼성전자 관련 뉴스 요약해줘)"
        user_input = st.chat_input(placeholder)

        if user_input:
            st.session_state["chat_messages"].append({"role": "user", "content": user_input})

            with st.spinner("AI가 답변을 생성 중입니다..."):
                try:
                    client = OpenAI(api_key=st.session_state["openai_api_key"])

                    # 컨텍스트 조립
                    context_blocks = []
                    if use_stock_ctx:
                        context_blocks.append(
                            f"[실시간 주식 데이터]\n{build_stock_context(selected_period_label)}"
                        )
                    if use_news_ctx and news_stocks_for_chat:
                        with st.spinner("뉴스 컨텍스트 준비 중..."):
                            news_ctx = build_news_context(news_stocks_for_chat, news_per_stock)
                        context_blocks.append(f"[최신 뉴스 데이터]\n{news_ctx}")

                    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
                    for block in context_blocks:
                        messages.append({"role": "system", "content": block})

                    # 대화 이력 최대 20턴
                    for m in st.session_state["chat_messages"][-20:]:
                        messages.append({"role": m["role"], "content": m["content"]})

                    response = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=messages,
                        temperature=0.7,
                        max_tokens=1500,
                    )
                    answer = response.choices[0].message.content

                except Exception as e:
                    error_msg = str(e)
                    if "api_key" in error_msg.lower() or "authentication" in error_msg.lower() or "401" in error_msg:
                        answer = "❌ API Key가 유효하지 않습니다. 사이드바에서 올바른 키를 입력해주세요."
                    elif "rate_limit" in error_msg.lower() or "429" in error_msg:
                        answer = "⚠️ API 요청 한도를 초과했습니다. 잠시 후 다시 시도해주세요."
                    elif "context_length" in error_msg.lower():
                        answer = "⚠️ 뉴스 컨텍스트가 너무 깁니다. 뉴스 수집 종목이나 종목당 뉴스 수를 줄여보세요."
                    else:
                        answer = f"⚠️ 오류가 발생했습니다: {error_msg}"

            st.session_state["chat_messages"].append({"role": "assistant", "content": answer})
            st.rerun()


# ────────────────────────────────────────────────────────────────────────
# TAB 5 : 보고서 발송
# ────────────────────────────────────────────────────────────────────────

SMTP_PRESETS = {
    "Gmail":  {"host": "smtp.gmail.com",  "port": 587},
    "Naver":  {"host": "smtp.naver.com",  "port": 587},
    "Kakao":  {"host": "smtp.kakao.com",  "port": 587},
    "Daum":   {"host": "smtp.daum.net",   "port": 465},
}


def get_smtp_config() -> dict:
    provider = st.session_state.get("smtp_provider", "Gmail")
    if provider == "직접 입력":
        return {
            "host": st.session_state.get("smtp_host_custom", ""),
            "port": int(st.session_state.get("smtp_port_custom", 587)),
        }
    return SMTP_PRESETS.get(provider, SMTP_PRESETS["Gmail"])


def send_email(to_addrs: list, subject: str, html_body: str) -> tuple[bool, str]:
    """SMTP로 HTML 메일 발송. (성공여부, 메시지) 반환."""
    email = st.session_state.get("smtp_email", "")
    password = st.session_state.get("smtp_app_password", "")
    cfg = get_smtp_config()

    if not email or not password:
        return False, "이메일 계정 또는 앱 비밀번호가 설정되지 않았습니다."

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email
    msg["To"] = ", ".join(to_addrs)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        provider = st.session_state.get("smtp_provider", "Gmail")
        if provider == "Daum" or cfg["port"] == 465:
            server = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=15)
        else:
            server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=15)
            server.starttls()
        server.login(email, password)
        server.sendmail(email, to_addrs, msg.as_string())
        server.quit()
        return True, "발송 완료"
    except smtplib.SMTPAuthenticationError:
        return False, "인증 실패: 이메일 또는 앱 비밀번호를 확인하세요."
    except smtplib.SMTPException as e:
        return False, f"SMTP 오류: {e}"
    except Exception as e:
        return False, f"오류: {e}"


def generate_report_html(stock_ctx: str, news_ctx: str, gpt_analysis: str, period_label: str) -> str:
    """보고서 HTML 생성."""
    today = datetime.today().strftime("%Y년 %m월 %d일")

    # 종목 요약 테이블 rows
    table_rows = ""
    for name, ticker in STOCKS.items():
        try:
            series = close_data[ticker].dropna()
            if len(series) < 2:
                continue
            current = series.iloc[-1]
            prev = series.iloc[-2]
            day_chg = (current - prev) / prev * 100
            period_ret = (series.iloc[-1] / series.iloc[0] - 1) * 100
            color = "#c0392b" if day_chg >= 0 else "#2471a3"
            arrow = "▲" if day_chg >= 0 else "▼"
            table_rows += f"""
            <tr>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;">{name}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right;">{current:,.0f}원</td>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right;color:{color};">
                {arrow} {abs(day_chg):.2f}%
              </td>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right;color:{'#c0392b' if period_ret>=0 else '#2471a3'};">
                {period_ret:+.2f}%
              </td>
            </tr>"""
        except Exception:
            pass

    # GPT 분석 텍스트 → HTML (줄바꿈 처리)
    analysis_html = gpt_analysis.replace("\n\n", "</p><p>").replace("\n", "<br>")

    return f"""
<!DOCTYPE html>
<html lang="ko">
<head><meta charset="utf-8"><title>주식 시장 보고서</title></head>
<body style="font-family:'Malgun Gothic',Arial,sans-serif;background:#f5f6fa;margin:0;padding:20px;">
  <div style="max-width:700px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">

    <!-- 헤더 -->
    <div style="background:linear-gradient(135deg,#1a237e,#283593);padding:32px 36px;color:#fff;">
      <h1 style="margin:0;font-size:22px;letter-spacing:-0.5px;">📈 국내 주식 시장 보고서</h1>
      <p style="margin:8px 0 0;opacity:0.8;font-size:14px;">기준일: {today} &nbsp;|&nbsp; 조회 기간: {period_label}</p>
    </div>

    <!-- 종목 현황 테이블 -->
    <div style="padding:28px 36px;">
      <h2 style="font-size:16px;color:#1a237e;border-left:4px solid #1a237e;padding-left:10px;margin-top:0;">
        종목 현황
      </h2>
      <table style="width:100%;border-collapse:collapse;font-size:14px;">
        <thead>
          <tr style="background:#f0f4ff;">
            <th style="padding:10px 12px;text-align:left;color:#555;">종목</th>
            <th style="padding:10px 12px;text-align:right;color:#555;">현재가</th>
            <th style="padding:10px 12px;text-align:right;color:#555;">전일대비</th>
            <th style="padding:10px 12px;text-align:right;color:#555;">기간수익률</th>
          </tr>
        </thead>
        <tbody>{table_rows}</tbody>
      </table>
    </div>

    <!-- AI 분석 -->
    <div style="padding:0 36px 28px;">
      <h2 style="font-size:16px;color:#1a237e;border-left:4px solid #1a237e;padding-left:10px;">
        AI 시장 분석 (GPT-4o-mini)
      </h2>
      <div style="background:#f8f9ff;border-radius:8px;padding:20px;font-size:14px;line-height:1.8;color:#333;">
        <p>{analysis_html}</p>
      </div>
    </div>

    <!-- 뉴스 헤드라인 -->
    <div style="padding:0 36px 28px;">
      <h2 style="font-size:16px;color:#1a237e;border-left:4px solid #1a237e;padding-left:10px;">
        주요 뉴스 헤드라인
      </h2>
      <div style="font-size:13px;color:#444;line-height:1.9;">
        <pre style="white-space:pre-wrap;font-family:inherit;margin:0;">{news_ctx}</pre>
      </div>
    </div>

    <!-- 푸터 -->
    <div style="background:#f0f4ff;padding:16px 36px;font-size:12px;color:#888;text-align:center;">
      본 보고서는 AI가 자동 생성한 참고 자료입니다. 투자 판단의 책임은 본인에게 있습니다.<br>
      데이터 출처: Yahoo Finance, Google News | 생성 시각: {today}
    </div>
  </div>
</body>
</html>"""


with tab_report:
    st.subheader("📧 보고서 생성 및 이메일 발송")
    st.caption("주식 데이터와 최신 뉴스를 기반으로 AI 보고서를 생성하고 이메일로 발송합니다.")

    has_openai = bool(st.session_state.get("openai_api_key"))
    has_email = bool(st.session_state.get("smtp_email") and st.session_state.get("smtp_app_password"))

    if not has_openai:
        st.warning("사이드바에서 OpenAI API Key를 입력해주세요.", icon="🤖")
    if not has_email:
        st.warning("사이드바에서 이메일 계정과 앱 비밀번호를 설정해주세요.", icon="📧")

    st.markdown("---")

    # ── 보고서 설정 ───────────────────────────────────────────────────
    rp_col1, rp_col2 = st.columns(2)
    with rp_col1:
        st.markdown("**📋 보고서 옵션**")
        rp_news_stocks = st.multiselect(
            "뉴스 수집 종목",
            list(STOCKS.keys()),
            default=list(STOCKS.keys())[:5],
            key="rp_news_stocks",
        )
        rp_news_count = st.slider("종목당 뉴스 수", 1, 10, 5, key="rp_news_count")
        rp_analysis_focus = st.text_area(
            "분석 포커스 (선택)",
            placeholder="예: 반도체 업황 중심으로 분석해줘, 단기 변동성이 높은 종목 위주로...",
            height=100,
            key="rp_focus",
        )

    with rp_col2:
        st.markdown("**📨 발송 설정**")
        default_email = st.session_state.get("smtp_email", "")
        rp_to = st.text_input(
            "수신자 이메일",
            value=default_email,
            placeholder="받는사람@example.com",
            help="여러 명은 쉼표(,)로 구분",
            key="rp_to_email",
        )
        rp_subject = st.text_input(
            "메일 제목",
            value=f"[주식 보고서] {datetime.today().strftime('%Y-%m-%d')} 시장 분석",
            key="rp_subject",
        )
        if has_email:
            provider = st.session_state.get("smtp_provider", "Gmail")
            cfg = get_smtp_config()
            st.info(f"발신: {st.session_state.get('smtp_email')} ({provider} / {cfg['host']}:{cfg['port']})")

    st.markdown("---")

    # ── 보고서 생성 버튼 ──────────────────────────────────────────────
    btn_col1, btn_col2, btn_col3 = st.columns([2, 2, 4])
    with btn_col1:
        gen_btn = st.button("🔍 보고서 생성", use_container_width=True,
                            disabled=not has_openai, key="rp_gen_btn")
    with btn_col2:
        send_btn = st.button("📤 생성 후 발송", use_container_width=True,
                             disabled=not (has_openai and has_email), key="rp_send_btn")

    if gen_btn or send_btn:
        if not rp_to.strip() and send_btn:
            st.error("수신자 이메일을 입력해주세요.")
            st.stop()

        # 1단계: 뉴스 수집
        with st.spinner("뉴스 수집 중..."):
            news_ctx_rp = build_news_context(rp_news_stocks, rp_news_count) if rp_news_stocks else ""
            stock_ctx_rp = build_stock_context(selected_period_label)

        # 2단계: GPT 분석 생성
        with st.spinner("AI 분석 보고서 생성 중..."):
            try:
                client = OpenAI(api_key=st.session_state["openai_api_key"])
                focus_prompt = f"\n\n추가 분석 요청: {rp_analysis_focus.strip()}" if rp_analysis_focus.strip() else ""

                rp_messages = [
                    {"role": "system", "content": """당신은 국내 주식 시장 전문 리포트 작성 AI입니다.
주식 데이터와 최신 뉴스를 바탕으로 전문적이고 읽기 쉬운 시장 분석 보고서를 작성합니다.
- 보고서 구조: ① 시장 전체 요약 ② 주요 상승/하락 종목 ③ 뉴스 기반 이슈 분석 ④ 단기 전망
- 각 섹션은 명확한 소제목으로 구분하세요.
- 투자 조언 시 반드시 "참고용이며 투자 판단은 본인 책임"임을 명시하세요.
- 한국어로 작성하고 전문적이고 간결하게 서술하세요."""},
                    {"role": "system", "content": f"[주식 데이터]\n{stock_ctx_rp}"},
                    {"role": "system", "content": f"[최신 뉴스]\n{news_ctx_rp}" if news_ctx_rp else "뉴스 데이터 없음"},
                    {"role": "user", "content": f"위 데이터를 바탕으로 오늘({datetime.today().strftime('%Y년 %m월 %d일')}) 기준 주식 시장 분석 보고서를 작성해주세요.{focus_prompt}"},
                ]
                rp_response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=rp_messages,
                    temperature=0.5,
                    max_tokens=2000,
                )
                gpt_analysis = rp_response.choices[0].message.content
                st.session_state["last_report_analysis"] = gpt_analysis
                st.session_state["last_report_news"] = news_ctx_rp
                st.session_state["last_report_stock"] = stock_ctx_rp
            except Exception as e:
                st.error(f"보고서 생성 실패: {e}")
                st.stop()

        # 3단계: 보고서 미리보기
        st.success("보고서 생성 완료!")
        with st.expander("📄 생성된 AI 분석 내용 미리보기", expanded=True):
            st.markdown(gpt_analysis)

        # HTML 보고서 생성
        html_report = generate_report_html(stock_ctx_rp, news_ctx_rp, gpt_analysis, selected_period_label)

        # HTML 다운로드
        st.download_button(
            "📥 HTML 보고서 다운로드",
            data=html_report.encode("utf-8"),
            file_name=f"stock_report_{datetime.today().strftime('%Y%m%d')}.html",
            mime="text/html",
        )

        # 4단계: 이메일 발송
        if send_btn:
            to_list = [e.strip() for e in rp_to.split(",") if e.strip()]
            # 이메일 형식 검증
            invalid = [e for e in to_list if not _re.match(r"[^@]+@[^@]+\.[^@]+", e)]
            if invalid:
                st.error(f"올바르지 않은 이메일 형식: {', '.join(invalid)}")
            else:
                with st.spinner(f"{', '.join(to_list)} 으로 발송 중..."):
                    ok, msg = send_email(to_list, rp_subject, html_report)
                if ok:
                    st.success(f"✅ 이메일 발송 완료 → {', '.join(to_list)}")
                else:
                    st.error(f"❌ 발송 실패: {msg}")

    # ── 이전 보고서 재발송 ────────────────────────────────────────────
    if st.session_state.get("last_report_analysis"):
        st.markdown("---")
        st.markdown("**📨 이전 보고서 재발송**")
        resend_col1, resend_col2 = st.columns([3, 1])
        with resend_col1:
            resend_to = st.text_input("수신자", value=st.session_state.get("smtp_email", ""),
                                      key="resend_to", placeholder="이메일 주소")
        with resend_col2:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("재발송", use_container_width=True, key="resend_btn", disabled=not has_email):
                if resend_to.strip():
                    html_resend = generate_report_html(
                        st.session_state["last_report_stock"],
                        st.session_state["last_report_news"],
                        st.session_state["last_report_analysis"],
                        selected_period_label,
                    )
                    to_list = [e.strip() for e in resend_to.split(",") if e.strip()]
                    with st.spinner("재발송 중..."):
                        ok, msg = send_email(to_list, rp_subject if rp_subject else "주식 보고서", html_resend)
                    if ok:
                        st.success(f"✅ 재발송 완료 → {resend_to}")
                    else:
                        st.error(f"❌ {msg}")
                else:
                    st.warning("수신자 이메일을 입력해주세요.")
