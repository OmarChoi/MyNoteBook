import json

import streamlit as st
from pytrends.request import TrendReq

# ──────────────────────────────────────────────
# 설정 및 상수
# ──────────────────────────────────────────────

# ★ 이 값만 바꾸면 AI 프로바이더가 전환됩니다 ("openai" 또는 "gemini")
AI_PROVIDER = "openai"

if AI_PROVIDER == "openai":
    from openai import OpenAI

    if (
        "API_KEY" not in st.secrets
        or not st.secrets["API_KEY"]
        or st.secrets["API_KEY"] == "your-openai-api-key"
    ):
        st.error(
            "🔑 API_KEY가 설정되지 않았습니다. "
            "`.streamlit/secrets.toml`에 OpenAI API 키를 입력해주세요."
        )
        st.stop()

    client = OpenAI(api_key=st.secrets["API_KEY"])
    MODEL = "gpt-4o-mini"

elif AI_PROVIDER == "gemini":
    from google import genai

    if (
        "GEMINI_API_KEY" not in st.secrets
        or not st.secrets["GEMINI_API_KEY"]
        or st.secrets["GEMINI_API_KEY"] == "your-gemini-api-key"
    ):
        st.error(
            "🔑 GEMINI_API_KEY가 설정되지 않았습니다. "
            "`.streamlit/secrets.toml`에 Gemini API 키를 입력해주세요."
        )
        st.stop()

    client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
    MODEL = "gemini-2.0-flash"

else:
    st.error(f"지원하지 않는 AI_PROVIDER: {AI_PROVIDER}")
    st.stop()

REGIONS = {
    "한국":  "KR",
    "미국":  "US",
    "일본":  "JP",
    "글로벌": "",
}

ENGINES = ["Unity", "Unreal Engine", "Godot", "RPG Maker", "기타"]

SESSION_KEYS = [
    "step", "trend_data", "trend_keywords",
    "game_ideas", "selected_idea", "design_doc",
]

SEED_KEYWORDS = {
    "KR": [
        "모바일게임", "RPG", "생존게임", "로그라이크", "오픈월드",
        "인디게임", "멀티플레이", "방치형게임", "소울라이크", "메타버스",
        "하이퍼캐주얼", "덱빌딩", "타워디펜스", "배틀로얄", "수집형RPG",
        "액션로그라이크", "코옵게임", "시뮬레이션", "리듬게임", "공포게임",
    ],
    "US": [
        "mobile game", "RPG", "survival game", "roguelike", "open world",
        "indie game", "multiplayer", "idle game", "soulslike", "metaverse",
        "hyper casual", "deck builder", "tower defense", "battle royale", "gacha RPG",
        "action roguelite", "co-op game", "simulation", "horror game", "city builder",
    ],
    "JP": [
        "モバイルゲーム", "RPG", "サバイバルゲーム", "ローグライク", "オープンワールド",
        "インディーゲーム", "マルチプレイ", "放置ゲーム", "ソウルライク", "メタバース",
        "ハイパーカジュアル", "デッキ構築", "タワーディフェンス", "バトルロイヤル", "ガチャRPG",
        "アクションローグライト", "協力プレイ", "シミュレーション", "ホラーゲーム", "箱庭ゲーム",
    ],
    "": [
        "mobile game", "RPG", "survival", "roguelike", "open world",
        "indie game", "multiplayer", "idle game", "soulslike", "metaverse",
        "hyper casual", "deck builder", "tower defense", "battle royale", "gacha",
        "action roguelite", "co-op", "simulation", "horror game", "city builder",
    ],
}


# ──────────────────────────────────────────────
# 트렌드 수집 함수
# ──────────────────────────────────────────────

@st.cache_data(ttl=3600)
def fetch_trends(region_code: str):
    """pytrends로 12개월 게임 카테고리(cat=41) 트렌드 데이터를 수집합니다."""
    try:
        pytrends = TrendReq(hl="ko", tz=540)
        kws = SEED_KEYWORDS.get(region_code, SEED_KEYWORDS[""])[:5]
        geo = region_code if region_code else ""

        pytrends.build_payload(kws, cat=41, timeframe="today 12-m", geo=geo)
        interest_over_time = pytrends.interest_over_time()

        pytrends.build_payload(kws[:1], cat=41, timeframe="today 12-m", geo=geo)
        related_queries = pytrends.related_queries()

        return {
            "interest_over_time": interest_over_time,
            "related_queries":   related_queries,
            "keywords_used":     kws,
        }
    except Exception as e:
        return f"트렌드 수집 실패: {e}"


def extract_trend_keywords(trend_data) -> list[str]:
    """연관/인기 검색어에서 최대 20개 키워드를 추출합니다."""
    if isinstance(trend_data, str):
        return []

    keywords = set()
    related = trend_data.get("related_queries", {})

    for _key, queries in related.items():
        if queries is None:
            continue
        for query_type in ["top", "rising"]:
            df = queries.get(query_type)
            if df is not None and not df.empty:
                keywords.update(df["query"].tolist())

    return list(keywords)[:20]


# ──────────────────────────────────────────────
# AI API 함수 (OpenAI / Gemini 공용)
# ──────────────────────────────────────────────

IDEA_SYSTEM_PROMPT = (
    "당신은 게임 기획 전문가입니다. "
    "반드시 JSON 배열로만 응답하세요. "
    "마크다운 코드 펜스 없이 순수 JSON만 출력하세요."
)

IDEA_USER_TEMPLATE = """아래 트렌드 키워드와 조건을 참고하여 혁신적인 게임 아이디어 5개를 제안해주세요.

[트렌드 키워드]
{keywords}

[조건]
- 게임 엔진: {engine}
- 타겟 지역: {region}
- 현재 트렌드를 반영할 것
- 차별화 요소가 명확할 것

아래 JSON 형식으로 응답:
[
  {{
    "title": "게임 제목",
    "genre": "장르",
    "core_system": "핵심 시스템 설명 (2-3문장)",
    "target_users": "타겟 유저층",
    "differentiation": "차별화 포인트",
    "references": "레퍼런스 게임 2-3개와 각각에서 어떤 요소를 참고했는지 설명"
  }}
]"""

DOC_SYSTEM_PROMPT = (
    "당신은 시니어 게임 기획자입니다. "
    "상세하고 전문적인 게임 기획 문서를 마크다운 형식으로 작성합니다."
)

DOC_USER_TEMPLATE = """아래 게임 아이디어를 바탕으로 상세한 게임 기획 문서를 작성해주세요.

[게임 아이디어]
- 제목: {title}
- 장르: {genre}
- 핵심 시스템: {core_system}
- 타겟 유저: {target_users}
- 차별화 포인트: {differentiation}
- 게임 엔진: {engine}

아래 항목을 포함하여 마크다운 형식으로 작성해주세요:

# {title} - 게임 기획 문서

## 1. 게임 개요
(장르, 플랫폼, 타겟 유저, 게임 콘셉트 설명)

## 2. 재미 요소
(핵심 재미, 플레이어 동기부여, 리텐션 요소)

## 3. 핵심 시스템
(메인 게임플레이 루프, 주요 시스템 3-5개 상세 설명)

## 4. 콘텐츠 구성
(스테이지/맵/월드 구성, 캐릭터/아이템 시스템, 진행 구조)

## 5. 수익 모델
(BM 전략, 과금 요소, 예상 ARPU 범위)

## 6. 개발 난이도
(기술적 도전 과제, 예상 개발 기간, 필요 인력 규모)"""


def _call_ai(system_prompt: str, user_content: str) -> str:
    """AI_PROVIDER에 따라 OpenAI 또는 Gemini API를 호출합니다."""
    if AI_PROVIDER == "openai":
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_content},
            ],
        )
        return response.choices[0].message.content

    else:  # gemini
        prompt = f"{system_prompt}\n\n{user_content}"
        response = client.models.generate_content(model=MODEL, contents=prompt)
        return response.text


def generate_game_ideas(keywords: list[str], engine: str, region: str) -> list[dict]:
    """트렌드 키워드 기반으로 게임 아이디어 5개를 생성합니다."""
    user_content = IDEA_USER_TEMPLATE.format(
        keywords=", ".join(keywords),
        engine=engine,
        region=region,
    )
    text = _call_ai(IDEA_SYSTEM_PROMPT, user_content).strip()

    # 마크다운 코드 펜스 제거
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        text = "\n".join(lines)

    return json.loads(text)


def generate_design_document(idea: dict, engine: str) -> str:
    """선택된 아이디어로 상세 기획 문서를 생성합니다."""
    user_content = DOC_USER_TEMPLATE.format(
        title=idea["title"],
        genre=idea["genre"],
        core_system=idea["core_system"],
        target_users=idea["target_users"],
        differentiation=idea["differentiation"],
        engine=engine,
    )
    return _call_ai(DOC_SYSTEM_PROMPT, user_content)


# ──────────────────────────────────────────────
# Streamlit UI
# ──────────────────────────────────────────────

PROVIDER_LABEL = "OpenAI" if AI_PROVIDER == "openai" else "Gemini"

st.set_page_config(
    page_title="트렌드 기반 게임 기획서 생성기",
    page_icon="🎮",
    layout="wide",
)
st.title("🎮 트렌드 기반 게임 기획서 생성기")
st.caption(
    f"Google Trends 데이터와 {PROVIDER_LABEL}를 활용하여 "
    "게임 아이디어를 생성하고 기획 문서를 자동 생성합니다."
)

# 세션 상태 초기화
for key in SESSION_KEYS:
    if key not in st.session_state:
        st.session_state[key] = None
if st.session_state["step"] is None:
    st.session_state["step"] = 1

# ── 사이드바 ──
with st.sidebar:
    st.header("설정")
    st.caption(f"AI: **{PROVIDER_LABEL}** ({MODEL})")
    selected_region = st.selectbox("지역 선택", list(REGIONS.keys()))
    selected_engine = st.selectbox("게임 엔진 선택", ENGINES)

    st.divider()
    if st.button("🔄 초기화", use_container_width=True):
        for key in SESSION_KEYS:
            st.session_state[key] = None
        st.session_state["step"] = 1
        st.rerun()

region_code = REGIONS[selected_region]

# ── Step 1: 트렌드 분석 및 아이디어 생성 ──
st.header("Step 1: 트렌드 분석 및 아이디어 생성")

if st.session_state["step"] == 1:
    if st.button("🔍 트렌드 분석 및 아이디어 생성", type="primary", use_container_width=True):

        with st.spinner("Google Trends 데이터를 수집하고 있습니다..."):
            trend_data = fetch_trends(region_code)

            if isinstance(trend_data, str):
                st.warning(f"⚠️ {trend_data}")
                st.info("시드 키워드로 대체하여 진행합니다.")
                keywords = SEED_KEYWORDS.get(region_code, SEED_KEYWORDS[""])
                st.session_state["trend_data"] = None
            else:
                st.session_state["trend_data"] = trend_data
                extracted = extract_trend_keywords(trend_data)
                seed = SEED_KEYWORDS.get(region_code, SEED_KEYWORDS[""])
                keywords = list(set(extracted + seed))[:20] if extracted else seed

            st.session_state["trend_keywords"] = keywords

        with st.spinner("AI가 게임 아이디어를 생성하고 있습니다..."):
            try:
                ideas = generate_game_ideas(keywords, selected_engine, selected_region)
                st.session_state["game_ideas"] = ideas
                st.session_state["step"] = 2
                st.rerun()
            except Exception as e:
                st.error(f"아이디어 생성 실패: {e}")

# ── 트렌드 데이터 표시 (Step 2 이상) ──
if st.session_state["step"] >= 2:
    if st.session_state["trend_data"] is not None:
        with st.expander("📊 트렌드 데이터 보기", expanded=False):
            iot = st.session_state["trend_data"].get("interest_over_time")
            if iot is not None and not iot.empty:
                chart_data = iot.drop(columns=["isPartial"], errors="ignore")
                st.line_chart(chart_data)

    if st.session_state["trend_keywords"]:
        with st.expander("🔑 사용된 키워드", expanded=False):
            st.write(", ".join(st.session_state["trend_keywords"]))

# ── Step 2: 아이디어 선택 ──
if st.session_state["step"] >= 2 and st.session_state["game_ideas"]:
    st.header("Step 2: 게임 아이디어 선택")

    for i, idea in enumerate(st.session_state["game_ideas"]):
        with st.container(border=True):
            col1, col2 = st.columns([4, 1])

            with col1:
                st.subheader(f"{i + 1}. {idea['title']}")
                st.write(f"**장르:** {idea['genre']}")
                st.write(f"**핵심 시스템:** {idea['core_system']}")
                st.write(f"**타겟 유저:** {idea['target_users']}")
                st.write(f"**차별화:** {idea['differentiation']}")
                if idea.get("references"):
                    st.write(f"**레퍼런스:** {idea['references']}")

            with col2:
                if st.session_state["step"] == 2:
                    if st.button("선택 ✅", key=f"select_{i}", use_container_width=True):
                        st.session_state["selected_idea"] = idea
                        st.session_state["step"] = 3
                        st.rerun()
                elif st.session_state["selected_idea"] == idea:
                    st.success("선택됨")

# ── Step 3: 기획 문서 생성 ──
if st.session_state["step"] >= 3 and st.session_state["selected_idea"]:
    st.header("Step 3: 기획 문서 생성")

    idea = st.session_state["selected_idea"]
    st.info(f"선택된 아이디어: **{idea['title']}** ({idea['genre']})")

    if st.session_state["design_doc"] is None:
        with st.spinner("AI가 기획 문서를 작성하고 있습니다..."):
            try:
                doc = generate_design_document(idea, selected_engine)
                st.session_state["design_doc"] = doc
                st.rerun()
            except Exception as e:
                st.error(f"기획 문서 생성 실패: {e}")

    if st.session_state["design_doc"]:
        st.markdown(st.session_state["design_doc"])

        st.divider()
        st.download_button(
            label="📥 기획 문서 다운로드 (.md)",
            data=st.session_state["design_doc"],
            file_name=f"{idea['title']}_기획문서.md",
            mime="text/markdown",
            use_container_width=True,
        )
