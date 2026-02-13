import json
import time
from collections import Counter
from datetime import datetime

import markdown
import pandas as pd
import requests
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

STEAMSPY_BASE_URL = "https://steamspy.com/api.php"
STEAM_STORE_API_URL = "https://store.steampowered.com/api/appdetails"
STEAMSPY_TOP_DETAIL_COUNT = 15

SESSION_KEYS = [
    "step", "trend_data", "trend_keywords",
    "game_ideas", "selected_idea", "design_doc",
    "market_analysis",
]

# steam_data는 별도 캐싱 (초기화 시에도 유지)
STEAM_CACHE_KEYS = ["steam_data", "steam_data_recent_years", "steam_data_time"]
STEAM_CACHE_TTL = 3600  # 1시간

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
# Steam 인기 게임 데이터 수집
# ──────────────────────────────────────────────

def _parse_owners(owners_str: str) -> int:
    """SteamSpy owners 범위 문자열(예: '10,000,000 .. 20,000,000')을 중간값으로 변환합니다."""
    try:
        parts = owners_str.replace(",", "").split("..")
        low = int(parts[0].strip())
        high = int(parts[1].strip()) if len(parts) > 1 else low
        return (low + high) // 2
    except (ValueError, IndexError):
        return 0


def _format_owners(count: int) -> str:
    """소유자 수를 읽기 쉬운 형식으로 변환합니다 (예: 1,500,000 → '1,500만')."""
    if count >= 10_000:
        return f"{count // 10_000:,}만"
    return f"{count:,}"


def _format_playtime(minutes: int) -> str:
    """플레이 시간(분)을 읽기 쉬운 형식으로 변환합니다."""
    if minutes >= 60:
        h, m = divmod(minutes, 60)
        return f"{h}시간 {m}분" if m else f"{h}시간"
    return f"{minutes}분"


def _get_release_year(appid: str) -> int | None:
    """Steam Store API에서 게임의 출시 연도를 가져옵니다."""
    try:
        resp = requests.get(
            STEAM_STORE_API_URL,
            params={"appids": appid, "filters": "release_date"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        app_data = data.get(str(appid), {})
        if not app_data.get("success"):
            return None
        release_info = app_data.get("data", {}).get("release_date", {})
        if release_info.get("coming_soon"):
            return None
        date_str = release_info.get("date", "")
        for part in date_str.replace(",", " ").split():
            if len(part) == 4 and part.isdigit():
                return int(part)
        return None
    except Exception:
        return None


def fetch_steam_top100(recent_years: int, progress_bar=None, status_text=None):
    """SteamSpy Top100(최근 2주)에서 최근 출시 게임만 필터링하여 장르/태그를 집계합니다."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    try:
        # ── Phase 1: SteamSpy Top100 리스트 가져오기 ──
        if status_text is not None:
            status_text.caption("Top 100 리스트를 가져오는 중...")
        resp = requests.get(
            STEAMSPY_BASE_URL,
            params={"request": "top100in2weeks"},
            timeout=10,
        )
        resp.raise_for_status()
        top100 = resp.json()

        # ── Phase 2: 출시일 병렬 확인 ──
        cutoff_year = datetime.now().year - recent_years
        checked = 0
        total = len(top100)

        def _check_release(item):
            appid, basic_info = item
            release_year = _get_release_year(appid)
            return appid, basic_info, release_year

        recent_games = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {
                executor.submit(_check_release, item): item
                for item in top100.items()
            }
            for future in as_completed(futures):
                checked += 1
                if progress_bar is not None:
                    progress_bar.progress(
                        checked / total * 0.5,  # 전체의 50%를 Phase 2에 할당
                        text=f"출시일 확인 중... {checked}/{total}",
                    )
                appid, basic_info, release_year = future.result()
                if release_year is not None and release_year >= cutoff_year:
                    recent_games.append((appid, basic_info, release_year))

        # 최근 2주 평균 플레이 시간 기준 정렬
        recent_games.sort(
            key=lambda x: x[1].get("average_2weeks", 0),
            reverse=True,
        )

        # ── Phase 3: 필터된 게임 상세 정보 수집 (SteamSpy, 순차) ──
        games = []
        genre_counter = Counter()
        tag_counter = Counter()
        checked_detail = 0

        for appid, basic_info, release_year in recent_games:
            if len(games) >= STEAMSPY_TOP_DETAIL_COUNT:
                break

            checked_detail += 1
            if progress_bar is not None:
                progress_bar.progress(
                    0.5 + (len(games) / STEAMSPY_TOP_DETAIL_COUNT) * 0.5,
                    text=f"상세 정보 수집 중... {len(games)}/{STEAMSPY_TOP_DETAIL_COUNT} (확인 {checked_detail}개)",
                )

            time.sleep(1)  # SteamSpy rate limit
            try:
                detail_resp = requests.get(
                    STEAMSPY_BASE_URL,
                    params={"request": "appdetails", "appid": appid},
                    timeout=10,
                )
                detail_resp.raise_for_status()
                detail = detail_resp.json()

                avg_2weeks = detail.get("average_2weeks", 0)
                if avg_2weeks == 0:
                    continue

                genre_list = [
                    g.strip()
                    for g in detail.get("genre", "").split(",")
                    if g.strip()
                ]
                tags = detail.get("tags", {})
                tag_names = list(tags.keys())[:10] if isinstance(tags, dict) else []

                for g in genre_list:
                    genre_counter[g] += 1
                for t in tag_names:
                    tag_counter[t] += 1

                owners = _parse_owners(
                    detail.get("owners", basic_info.get("owners", "0"))
                )
                name = detail.get("name", basic_info.get("name", "Unknown"))
            except Exception:
                continue

            games.append({
                "name": name,
                "owners": owners,
                "average_2weeks": avg_2weeks,
                "release_year": release_year,
                "genre": genre_list,
                "tags": tag_names,
            })

            if status_text is not None:
                status_text.caption(f"수집 완료: {name} ({release_year}년, 평균 {_format_playtime(avg_2weeks)})")

        return {
            "games": games,
            "top_genres": genre_counter.most_common(10),
            "top_tags": tag_counter.most_common(15),
        }
    except Exception as e:
        return f"Steam 데이터 수집 실패: {e}"


def format_steam_summary(steam_data, recent_years: int) -> str:
    """Steam 데이터를 AI 프롬프트용 텍스트로 포맷합니다."""
    if isinstance(steam_data, str) or steam_data is None:
        return ""

    lines = []
    lines.append(f"Steam 인기 게임 (최근 2주 인기 + 최근 {recent_years}년 이내 출시):")
    for g in steam_data["games"][:10]:
        genres = ", ".join(g["genre"]) if g["genre"] else "N/A"
        year = g.get("release_year", "?")
        playtime = _format_playtime(g.get("average_2weeks", 0))
        lines.append(f"- {g['name']} ({year}년, 장르: {genres}, 최근 2주 평균 플레이: {playtime})")

    lines.append("\nSteam 인기 장르 TOP 10:")
    for genre, count in steam_data["top_genres"]:
        lines.append(f"- {genre} ({count}개 게임)")

    lines.append("\nSteam 인기 태그 TOP 15:")
    tag_strs = [f"{tag}({cnt})" for tag, cnt in steam_data["top_tags"]]
    lines.append(", ".join(tag_strs))

    return "\n".join(lines)


def format_market_patterns(steam_data, recent_years: int) -> str:
    """Steam 데이터에서 게임 이름을 제거하고 시장 패턴만 추출합니다. (AI 프롬프트용)"""
    if isinstance(steam_data, str) or steam_data is None:
        return ""

    lines = []

    # 장르 조합 빈도
    genre_combos = Counter()
    playtime_by_genre = {}
    owner_by_genre = {}
    for g in steam_data["games"]:
        combo = tuple(sorted(g["genre"])) if g["genre"] else ("Unknown",)
        genre_combos[combo] += 1
        avg_play = g.get("average_2weeks", 0)
        owners = g.get("owners", 0)
        for genre in combo:
            playtime_by_genre.setdefault(genre, []).append(avg_play)
            owner_by_genre.setdefault(genre, []).append(owners)

    lines.append(f"[시장 패턴 분석 - 최근 {recent_years}년 이내 출시, Steam Top100 기준]")
    lines.append("")

    lines.append("장르 조합 빈도:")
    for combo, count in genre_combos.most_common(10):
        lines.append(f"- {' + '.join(combo)}: {count}개")

    lines.append("")
    lines.append("장르별 평균 플레이타임 (최근 2주):")
    for genre, times in sorted(playtime_by_genre.items(), key=lambda x: sum(x[1]) / len(x[1]), reverse=True):
        avg = sum(times) // len(times)
        lines.append(f"- {genre}: {_format_playtime(avg)} (게임 {len(times)}개)")

    lines.append("")
    lines.append("장르별 평균 소유자 수:")
    for genre, owners in sorted(owner_by_genre.items(), key=lambda x: sum(x[1]) / len(x[1]), reverse=True):
        avg = sum(owners) // len(owners)
        lines.append(f"- {genre}: {_format_owners(avg)} (게임 {len(owners)}개)")

    # 태그 클러스터
    lines.append("")
    lines.append("인기 태그 분포:")
    for tag, cnt in steam_data["top_tags"]:
        lines.append(f"- {tag}: {cnt}개 게임")

    # 시장 포화도
    lines.append("")
    lines.append("시장 포화도 (장르별 게임 수):")
    for genre, count in steam_data["top_genres"]:
        saturation = "높음" if count >= 5 else "보통" if count >= 3 else "낮음"
        lines.append(f"- {genre}: {count}개 (포화도: {saturation})")

    # 플레이타임 분포
    all_playtimes = [g.get("average_2weeks", 0) for g in steam_data["games"] if g.get("average_2weeks", 0) > 0]
    if all_playtimes:
        lines.append("")
        lines.append("전체 플레이타임 분포:")
        lines.append(f"- 최소: {_format_playtime(min(all_playtimes))}")
        lines.append(f"- 최대: {_format_playtime(max(all_playtimes))}")
        lines.append(f"- 평균: {_format_playtime(sum(all_playtimes) // len(all_playtimes))}")

    return "\n".join(lines)


# ──────────────────────────────────────────────
# AI API 함수 (OpenAI / Gemini 공용)
# ──────────────────────────────────────────────

MARKET_ANALYSIS_SYSTEM_PROMPT = (
    "당신은 게임 시장 분석 전문가입니다. "
    "데이터 기반으로 시장의 공백과 혁신 기회를 발견하는 것이 전문입니다. "
    "반드시 JSON 객체로만 응답하세요. "
    "마크다운 코드 펜스 없이 순수 JSON만 출력하세요."
)

MARKET_ANALYSIS_USER_TEMPLATE = """아래 시장 데이터와 트렌드를 분석하여 혁신적인 게임 기회를 도출해주세요.

[트렌드 키워드]
{keywords}

[시장 패턴 데이터]
{market_patterns}

다음 관점으로 분석해주세요:

1. 사용자 잠재 니즈: 트렌드 키워드에서 드러나지만 현재 시장이 충족시키지 못하는 플레이어 욕구 3-5개
2. 시장 공백: 인기 있는 장르/태그 조합에서 누락된 영역, 또는 포화도가 낮은 블루오션 3-5개
3. 혁신 축: 기존 게임들이 시도하지 않은 새로운 방향성 3-5개 (메커니즘, 내러티브, 인터랙션 등)
4. 안티패턴: 시장에 이미 넘쳐나서 피해야 할 뻔한 조합이나 클리셰 3-5개

아래 JSON 형식으로 응답:
{{
    "player_needs": ["니즈1: 설명", "니즈2: 설명", ...],
    "market_gaps": ["공백1: 설명", "공백2: 설명", ...],
    "innovation_axes": ["혁신축1: 설명", "혁신축2: 설명", ...],
    "anti_patterns": ["안티패턴1: 설명", "안티패턴2: 설명", ...]
}}"""

IDEA_SYSTEM_PROMPT = (
    "당신은 혁신적인 게임 디자이너입니다. "
    "'이런 게임은 본 적 없다'는 반응을 이끌어내는 것이 목표입니다. "
    "반드시 JSON 배열로만 응답하세요. "
    "마크다운 코드 펜스 없이 순수 JSON만 출력하세요."
)

IDEA_USER_TEMPLATE = """아래 시장 분석 결과를 기반으로 혁신적인 게임 아이디어 5개를 제안해주세요.

[시장 분석 결과]
- 사용자 잠재 니즈: {player_needs}
- 시장 공백: {market_gaps}
- 혁신 축: {innovation_axes}
- 피해야 할 안티패턴: {anti_patterns}

[트렌드 키워드]
{keywords}

{market_patterns_section}[조건]
- 게임 엔진: {engine}
- 타겟 지역: {region}
{genre_filter}
[필수 창의성 규칙]
- 기존 게임의 시스템을 그대로 가져오지 말 것
- "A게임 + B게임"식 단순 조합을 하지 말 것
- 핵심 메커니즘이 기존에 없던 새로운 것이어야 함
- 시장 공백을 메우되, 공백이 존재하는 이유(기술적 한계 등)도 고려할 것
- 플레이어가 경험할 새로운 감정이나 판타지를 명확히 할 것

아래 JSON 형식으로 응답:
[
  {{
    "title": "게임 제목",
    "genre": "장르",
    "core_system": "핵심 시스템 설명 (2-3문장)",
    "target_users": "타겟 유저층",
    "differentiation": "차별화 포인트",
    "core_mechanic": "이 게임만의 독창적 핵심 메커니즘 (기존에 없던 새로운 인터랙션/시스템)",
    "market_gap": "이 게임이 메우는 시장 공백",
    "player_fantasy": "플레이어가 경험하게 될 새로운 판타지/감정"
  }}
]"""

DOC_SYSTEM_PROMPT = (
    "당신은 시니어 게임 기획자입니다. "
    "독창적인 핵심 메커니즘을 중심으로 모든 시스템이 유기적으로 연결된 "
    "상세하고 전문적인 게임 기획 문서를 마크다운 형식으로 작성합니다."
)

DOC_USER_TEMPLATE = """아래 게임 아이디어를 바탕으로 상세한 게임 기획 문서를 작성해주세요.

[게임 아이디어]
- 제목: {title}
- 장르: {genre}
- 핵심 시스템: {core_system}
- 타겟 유저: {target_users}
- 차별화 포인트: {differentiation}
- 핵심 메커니즘: {core_mechanic}
- 시장 공백: {market_gap}
- 플레이어 판타지: {player_fantasy}
- 게임 엔진: {engine}

{market_section}[기획 원칙]
- 모든 하위 시스템은 핵심 메커니즘에서 파생되어야 합니다
- 기존 게임의 시스템을 그대로 차용하지 마세요
- 핵심 메커니즘이 만들어내는 독특한 플레이 경험에 집중하세요

아래 항목을 포함하여 마크다운 형식으로 작성해주세요:

# {title} - 게임 기획 문서

## 1. 게임 개요
(장르, 플랫폼, 타겟 유저, 게임 콘셉트 설명, 플레이어 판타지)

## 2. 핵심 메커니즘 상세 설계
(독창적 핵심 메커니즘의 구체적 작동 방식, 플레이어 인터랙션 흐름, 이 메커니즘이 만드는 독특한 경험, 기존 게임과의 차이점)

## 3. 게임플레이 루프
(코어 루프: 1분/10분/1시간 단위 플레이 사이클, 각 루프가 핵심 메커니즘과 어떻게 연결되는지, 장기 진행 루프와 리텐션 구조)

## 4. 재미 요소
(핵심 재미, 플레이어 동기부여, 리텐션 요소)

## 5. 시스템 설계
(핵심 메커니즘에서 파생된 주요 시스템 3-5개, 각 시스템 간 상호작용)

## 6. 콘텐츠 구성
(스테이지/맵/월드 구성, 캐릭터/아이템 시스템, 진행 구조)

## 7. 수익 모델
(BM 전략, 과금 요소, 예상 ARPU 범위)

## 8. 시장 포지셔닝
(타겟 시장 세그먼트, 이 게임이 메우는 시장 공백, 포지셔닝 전략, 차별화 방향 - 특정 게임과 비교하지 말고 시장 내 위치를 설명)

## 9. 개발 난이도
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


def generate_market_analysis(
    keywords: list[str],
    market_patterns: str,
) -> dict:
    """시장 데이터를 분석하여 니즈, 공백, 혁신축, 안티패턴을 도출합니다."""
    user_content = MARKET_ANALYSIS_USER_TEMPLATE.format(
        keywords=", ".join(keywords),
        market_patterns=market_patterns if market_patterns else "시장 데이터 없음",
    )
    text = _call_ai(MARKET_ANALYSIS_SYSTEM_PROMPT, user_content).strip()

    # 마크다운 코드 펜스 제거
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        text = "\n".join(lines)

    return json.loads(text)


def generate_game_ideas(
    keywords: list[str],
    engine: str,
    region: str,
    market_patterns: str = "",
    market_analysis: dict | None = None,
    genres: list[str] | None = None,
) -> list[dict]:
    """시장 분석 결과 기반으로 혁신적인 게임 아이디어 5개를 생성합니다."""
    analysis = market_analysis or {}
    player_needs = "\n".join(f"  - {n}" for n in analysis.get("player_needs", ["데이터 없음"]))
    market_gaps = "\n".join(f"  - {g}" for g in analysis.get("market_gaps", ["데이터 없음"]))
    innovation_axes = "\n".join(f"  - {a}" for a in analysis.get("innovation_axes", ["데이터 없음"]))
    anti_patterns = "\n".join(f"  - {p}" for p in analysis.get("anti_patterns", ["데이터 없음"]))

    market_patterns_section = (
        f"[시장 패턴 데이터]\n{market_patterns}\n\n" if market_patterns else ""
    )
    genre_filter = (
        f"- 선호 장르: {', '.join(genres)} (이 장르를 중심으로 아이디어 생성)\n"
        if genres else ""
    )
    user_content = IDEA_USER_TEMPLATE.format(
        keywords=", ".join(keywords),
        engine=engine,
        region=region,
        player_needs=player_needs,
        market_gaps=market_gaps,
        innovation_axes=innovation_axes,
        anti_patterns=anti_patterns,
        market_patterns_section=market_patterns_section,
        genre_filter=genre_filter,
    )
    text = _call_ai(IDEA_SYSTEM_PROMPT, user_content).strip()

    # 마크다운 코드 펜스 제거
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        text = "\n".join(lines)

    return json.loads(text)


def convert_md_to_html(md_text: str, title: str = "게임 기획 문서") -> str:
    """마크다운 텍스트를 스타일이 적용된 HTML 문서로 변환합니다."""
    body = markdown.markdown(md_text, extensions=["tables", "fenced_code"])
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>
  body {{ font-family: 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif;
         max-width: 900px; margin: 40px auto; padding: 0 20px;
         line-height: 1.8; color: #333; }}
  h1 {{ border-bottom: 3px solid #2c3e50; padding-bottom: 10px; color: #2c3e50; }}
  h2 {{ border-bottom: 1px solid #bdc3c7; padding-bottom: 6px; margin-top: 2em; color: #34495e; }}
  h3 {{ color: #7f8c8d; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
  th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
  th {{ background: #f5f5f5; }}
  code {{ background: #f4f4f4; padding: 2px 6px; border-radius: 3px; }}
  @media print {{ body {{ margin: 0; }} }}
</style>
</head>
<body>{body}</body>
</html>"""


def generate_design_document(
    idea: dict, engine: str, market_patterns: str = "",
) -> str:
    """선택된 아이디어로 핵심 메커니즘 중심의 상세 기획 문서를 생성합니다."""
    market_section = (
        f"[시장 패턴 데이터 - 포지셔닝 참고용]\n{market_patterns}\n\n"
        if market_patterns else ""
    )
    user_content = DOC_USER_TEMPLATE.format(
        title=idea["title"],
        genre=idea["genre"],
        core_system=idea["core_system"],
        target_users=idea["target_users"],
        differentiation=idea["differentiation"],
        core_mechanic=idea.get("core_mechanic", ""),
        market_gap=idea.get("market_gap", ""),
        player_fantasy=idea.get("player_fantasy", ""),
        engine=engine,
        market_section=market_section,
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

# ── 커스텀 CSS ──
st.markdown("""
<style>
/* ─── 다크 게이밍 테마 ─── */
:root {
    --accent-purple: #7c3aed;
    --accent-cyan: #06b6d4;
    --accent-gradient: linear-gradient(135deg, #7c3aed, #06b6d4);
    --card-bg: rgba(30, 30, 60, 0.05);
    --card-border: rgba(124, 58, 237, 0.2);
}

/* ─── 사이드바 스타일링 ─── */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
}
section[data-testid="stSidebar"] * {
    color: #e0e0ff !important;
}
section[data-testid="stSidebar"] .stSelectbox label,
section[data-testid="stSidebar"] .stMultiSelect label,
section[data-testid="stSidebar"] .stSlider label {
    color: #a78bfa !important;
    font-weight: 600;
}
section[data-testid="stSidebar"] hr {
    border-color: rgba(124, 58, 237, 0.3);
}
section[data-testid="stSidebar"] .stButton > button {
    background: linear-gradient(135deg, #7c3aed, #06b6d4) !important;
    color: white !important;
    border: none !important;
    font-weight: 600;
}

/* ─── Step 진행 표시기 ─── */
.step-indicator {
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 0;
    margin: 1rem 0 2rem 0;
    padding: 1rem;
    background: linear-gradient(135deg, rgba(124,58,237,0.05), rgba(6,182,212,0.05));
    border-radius: 12px;
    border: 1px solid rgba(124,58,237,0.1);
}
.step-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 20px;
    border-radius: 25px;
    font-size: 0.9rem;
    font-weight: 500;
    color: #888;
    background: transparent;
    transition: all 0.3s ease;
}
.step-item.active {
    background: linear-gradient(135deg, #7c3aed, #06b6d4);
    color: white;
    font-weight: 700;
    box-shadow: 0 4px 15px rgba(124, 58, 237, 0.3);
}
.step-item.completed {
    background: rgba(16, 185, 129, 0.15);
    color: #10b981;
    font-weight: 600;
}
.step-arrow {
    font-size: 1.2rem;
    color: #ccc;
    margin: 0 4px;
}

/* ─── Primary 버튼 그라디언트 ─── */
.stButton > button[kind="primary"],
div[data-testid="stFormSubmitButton"] > button {
    background: linear-gradient(135deg, #7c3aed, #06b6d4) !important;
    color: white !important;
    border: none !important;
    font-weight: 700;
    letter-spacing: 0.5px;
    transition: all 0.3s ease;
    box-shadow: 0 4px 15px rgba(124, 58, 237, 0.2);
}
.stButton > button[kind="primary"]:hover,
div[data-testid="stFormSubmitButton"] > button:hover {
    box-shadow: 0 6px 25px rgba(124, 58, 237, 0.4);
    transform: translateY(-1px);
}

/* ─── 아이디어 카드 hover 효과 ─── */
div[data-testid="stVerticalBlock"] > div[data-testid="stContainer"] {
    transition: all 0.3s ease;
    border-color: rgba(124, 58, 237, 0.15) !important;
}
div[data-testid="stVerticalBlock"] > div[data-testid="stContainer"]:hover {
    transform: translateY(-2px);
    border-color: rgba(124, 58, 237, 0.5) !important;
    box-shadow: 0 8px 25px rgba(124, 58, 237, 0.15);
}

/* ─── Expander 스타일 ─── */
details[data-testid="stExpander"] {
    border: 1px solid rgba(124, 58, 237, 0.15) !important;
    border-radius: 10px !important;
    background: rgba(124, 58, 237, 0.02);
}
details[data-testid="stExpander"] summary {
    font-weight: 600;
}

/* ─── Metric 카드 스타일 ─── */
div[data-testid="stMetric"] {
    background: linear-gradient(135deg, rgba(124,58,237,0.08), rgba(6,182,212,0.08));
    padding: 16px;
    border-radius: 12px;
    border: 1px solid rgba(124, 58, 237, 0.15);
}
div[data-testid="stMetric"] label {
    color: #7c3aed !important;
    font-weight: 600;
}

/* ─── 장르 뱃지 ─── */
.genre-badge {
    display: inline-block;
    padding: 3px 12px;
    border-radius: 15px;
    font-size: 0.8rem;
    font-weight: 600;
    background: linear-gradient(135deg, #7c3aed, #6d28d9);
    color: white;
    margin-right: 6px;
    margin-bottom: 4px;
}

/* ─── 아이디어 카드 내 아이콘 라벨 ─── */
.idea-label {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 0.85rem;
    font-weight: 600;
    padding: 2px 10px;
    border-radius: 6px;
    margin-bottom: 4px;
}
.idea-label.mechanic {
    background: rgba(124, 58, 237, 0.1);
    color: #7c3aed;
}
.idea-label.market {
    background: rgba(6, 182, 212, 0.1);
    color: #0891b2;
}
.idea-label.fantasy {
    background: rgba(236, 72, 153, 0.1);
    color: #db2777;
}

/* ─── 기획 문서 카드 프레임 ─── */
.doc-frame {
    background: white;
    border: 2px solid rgba(124, 58, 237, 0.15);
    border-radius: 16px;
    padding: 2rem;
    margin: 1rem 0;
    box-shadow: 0 4px 20px rgba(124, 58, 237, 0.08);
}
.doc-frame h1 {
    color: #7c3aed;
    border-bottom: 3px solid;
    border-image: linear-gradient(135deg, #7c3aed, #06b6d4) 1;
    padding-bottom: 10px;
}
.doc-frame h2 {
    color: #4c1d95;
    border-bottom: 1px solid rgba(124, 58, 237, 0.2);
    padding-bottom: 6px;
}

/* ─── 사이드바 로고 영역 ─── */
.sidebar-logo {
    text-align: center;
    padding: 1rem 0 1.5rem 0;
    border-bottom: 1px solid rgba(124, 58, 237, 0.3);
    margin-bottom: 1rem;
}
.sidebar-logo .logo-icon {
    font-size: 2.5rem;
    display: block;
    margin-bottom: 4px;
}
.sidebar-logo .logo-title {
    font-size: 1.1rem;
    font-weight: 700;
    background: linear-gradient(135deg, #a78bfa, #06b6d4);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}
.sidebar-logo .logo-subtitle {
    font-size: 0.75rem;
    color: #8888bb !important;
    margin-top: 2px;
}

/* ─── 사이드바 섹션 제목 ─── */
.sidebar-section-title {
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: #a78bfa !important;
    margin: 1rem 0 0.5rem 0;
    font-weight: 700;
}
</style>
""", unsafe_allow_html=True)

st.title("🎮 트렌드 기반 게임 기획서 생성기")
st.caption(
    f"Google Trends + Steam 인기 게임 데이터와 {PROVIDER_LABEL}를 활용하여 "
    "게임 아이디어를 생성하고 기획 문서를 자동 생성합니다."
)

# 세션 상태 초기화 (step indicator보다 먼저 필요)
for key in SESSION_KEYS:
    if key not in st.session_state:
        st.session_state[key] = None
if st.session_state["step"] is None:
    st.session_state["step"] = 1


def render_step_indicator(current_step: int):
    """3단계 프로그레스 바 UI를 렌더링합니다."""
    steps = [
        ("1", "트렌드 분석", "📊"),
        ("2", "아이디어 선택", "💡"),
        ("3", "기획서 생성", "📝"),
    ]
    items = []
    for num, label, icon in steps:
        step_num = int(num)
        if step_num < current_step:
            cls = "completed"
            marker = "✅"
        elif step_num == current_step:
            cls = "active"
            marker = icon
        else:
            cls = ""
            marker = icon
        items.append(f'<div class="step-item {cls}">{marker} {num}. {label}</div>')

    html = '<div class="step-indicator">' + '<span class="step-arrow">→</span>'.join(items) + '</div>'
    st.markdown(html, unsafe_allow_html=True)


render_step_indicator(st.session_state["step"])

# ── 사이드바 ──
with st.sidebar:
    st.markdown("""
    <div class="sidebar-logo">
        <span class="logo-icon">🎮</span>
        <div class="logo-title">Game Planner AI</div>
        <div class="logo-subtitle">트렌드 기반 게임 기획 도구</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="sidebar-section-title">⚙️ 기본 설정</div>', unsafe_allow_html=True)
    st.caption(f"AI: **{PROVIDER_LABEL}** ({MODEL})")
    selected_region = st.selectbox("🌍 지역 선택", list(REGIONS.keys()))
    selected_engine = st.selectbox("🛠️ 게임 엔진 선택", ENGINES)

    st.markdown('<div class="sidebar-section-title">🎯 필터 옵션</div>', unsafe_allow_html=True)
    GENRE_OPTIONS = [
        "Action", "Adventure", "RPG", "Strategy", "Simulation",
        "Casual", "Indie", "Racing", "Sports", "Puzzle",
        "Platformer", "Shooter", "Horror", "Roguelike",
    ]
    selected_genres = st.multiselect(
        "🏷️ 선호 장르 필터 (선택사항)",
        options=GENRE_OPTIONS,
        default=[],
        help="선택하면 해당 장르 중심으로 아이디어를 생성합니다.",
    )

    recent_years = st.slider(
        "📅 출시 연도 필터 (최근 N년 이내)",
        min_value=1,
        max_value=20,
        value=5,
        help="최근 N년 이내에 출시된 게임 중에서만 분석합니다."
    )

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

        # Steam 데이터 캐시 확인: 같은 연도 필터 + TTL 이내면 재사용
        cached = st.session_state.get("steam_data")
        cached_years = st.session_state.get("steam_data_recent_years")
        cached_time = st.session_state.get("steam_data_time", 0)
        cache_valid = (
            cached is not None
            and not isinstance(cached, str)
            and cached_years == recent_years
            and (time.time() - cached_time) < STEAM_CACHE_TTL
        )

        if cache_valid:
            st.success(f"Steam 데이터 캐시 사용 (최근 {recent_years}년 필터, {len(cached['games'])}개 게임)")
            steam_data = cached
            market_patterns = format_market_patterns(steam_data, recent_years)
        else:
            st.subheader("Steam 데이터 수집 중...")
            st.caption(f"최근 {recent_years}년 이내 출시 게임을 필터링합니다.")
            progress_bar = st.progress(0.0, text="준비 중...")
            status_text = st.empty()
            steam_data = fetch_steam_top100(recent_years=recent_years, progress_bar=progress_bar, status_text=status_text)
            progress_bar.empty()
            status_text.empty()
            if isinstance(steam_data, str):
                st.warning(f"⚠️ {steam_data}")
                st.info("Steam 데이터 없이 진행합니다.")
                st.session_state["steam_data"] = None
                market_patterns = ""
            else:
                st.session_state["steam_data"] = steam_data
                st.session_state["steam_data_recent_years"] = recent_years
                st.session_state["steam_data_time"] = time.time()
                market_patterns = format_market_patterns(steam_data, recent_years)

        # 시장 분석 단계 (AI 호출)
        with st.spinner("AI가 시장 패턴을 분석하고 있습니다..."):
            try:
                market_analysis = generate_market_analysis(keywords, market_patterns)
                st.session_state["market_analysis"] = market_analysis
            except Exception as e:
                st.warning(f"시장 분석 실패: {e}")
                st.info("시장 분석 없이 아이디어를 생성합니다.")
                market_analysis = None
                st.session_state["market_analysis"] = None

        with st.spinner("AI가 혁신적인 게임 아이디어를 생성하고 있습니다..."):
            try:
                ideas = generate_game_ideas(
                    keywords, selected_engine, selected_region,
                    market_patterns=market_patterns,
                    market_analysis=market_analysis,
                    genres=selected_genres or None,
                )
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

    if st.session_state.get("steam_data") is not None and not isinstance(
        st.session_state["steam_data"], str
    ):
        steam = st.session_state["steam_data"]
        with st.expander("🎮 Steam 인기 게임 분석", expanded=False):
            st.subheader(f"인기 게임 TOP 15 (최근 {recent_years}년 이내 출시)")
            game_df = pd.DataFrame([
                {
                    "게임": g["name"],
                    "출시": g.get("release_year", "?"),
                    "최근 2주 평균 플레이": _format_playtime(g.get("average_2weeks", 0)),
                    "장르": ", ".join(g["genre"]),
                }
                for g in steam["games"]
            ])
            st.dataframe(game_df, use_container_width=True, hide_index=True)

            st.subheader("인기 장르 분포")
            genre_df = pd.DataFrame(
                steam["top_genres"], columns=["장르", "게임 수"],
            )
            st.bar_chart(genre_df, x="장르", y="게임 수")

            st.subheader("인기 태그")
            tag_strs = [f"`{tag}` ({cnt})" for tag, cnt in steam["top_tags"]]
            st.write(" / ".join(tag_strs))

    # 교차 분석
    has_steam = (
        st.session_state.get("steam_data") is not None
        and not isinstance(st.session_state["steam_data"], str)
    )
    has_trends = bool(st.session_state.get("trend_keywords"))
    if has_steam and has_trends:
        with st.expander("🔀 트렌드 × Steam 교차 분석", expanded=False):
            trend_kws = {kw.lower() for kw in st.session_state["trend_keywords"]}
            steam_tags = {
                tag.lower()
                for tag, _ in st.session_state["steam_data"]["top_tags"]
            }

            overlap = trend_kws & steam_tags
            trend_only = trend_kws - steam_tags
            steam_only = steam_tags - trend_kws

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("겹치는 키워드", len(overlap))
                if overlap:
                    st.write(", ".join(f"`{k}`" for k in sorted(overlap)))
                else:
                    st.caption("없음")
            with col2:
                st.metric("트렌드에만 있는 키워드", len(trend_only))
                st.caption("검색은 많지만 Steam에 부족 → 블루오션 가능성")
                if trend_only:
                    st.write(", ".join(f"`{k}`" for k in sorted(list(trend_only)[:10])))
            with col3:
                st.metric("Steam에만 있는 태그", len(steam_only))
                st.caption("이미 시장에 존재 → 레드오션 주의")
                if steam_only:
                    st.write(", ".join(f"`{k}`" for k in sorted(list(steam_only)[:10])))

    # AI 시장 분석 결과
    if st.session_state.get("market_analysis"):
        analysis = st.session_state["market_analysis"]
        with st.expander("🧠 AI 시장 분석 결과", expanded=False):
            ma_col1, ma_col2 = st.columns(2)
            with ma_col1:
                st.markdown("**사용자 잠재 니즈**")
                for need in analysis.get("player_needs", []):
                    st.markdown(f"- {need}")
                st.markdown("**시장 공백**")
                for gap in analysis.get("market_gaps", []):
                    st.markdown(f"- {gap}")
            with ma_col2:
                st.markdown("**혁신 축**")
                for axis in analysis.get("innovation_axes", []):
                    st.markdown(f"- {axis}")
                st.markdown("**피해야 할 안티패턴**")
                for anti in analysis.get("anti_patterns", []):
                    st.markdown(f"- {anti}")

# ── Step 2: 아이디어 선택 ──
if st.session_state["step"] >= 2 and st.session_state["game_ideas"]:
    st.header("Step 2: 게임 아이디어 선택")

    for i, idea in enumerate(st.session_state["game_ideas"]):
        with st.container(border=True):
            col1, col2 = st.columns([4, 1])

            with col1:
                st.subheader(f"{i + 1}. {idea['title']}")
                # 장르 뱃지
                genres_html = " ".join(
                    f'<span class="genre-badge">{g.strip()}</span>'
                    for g in idea["genre"].split(",")
                )
                st.markdown(genres_html, unsafe_allow_html=True)
                st.write(f"**핵심 시스템:** {idea['core_system']}")
                st.write(f"**타겟 유저:** {idea['target_users']}")
                st.write(f"**차별화:** {idea['differentiation']}")
                if idea.get("core_mechanic"):
                    st.markdown(
                        f'<div class="idea-label mechanic">⚙️ 핵심 메커니즘</div>',
                        unsafe_allow_html=True,
                    )
                    st.write(idea["core_mechanic"])
                if idea.get("market_gap"):
                    st.markdown(
                        f'<div class="idea-label market">📍 시장 공백</div>',
                        unsafe_allow_html=True,
                    )
                    st.write(idea["market_gap"])
                if idea.get("player_fantasy"):
                    st.markdown(
                        f'<div class="idea-label fantasy">✨ 플레이어 판타지</div>',
                        unsafe_allow_html=True,
                    )
                    st.write(idea["player_fantasy"])

            with col2:
                if st.session_state["step"] == 2:
                    if st.button("선택 ✅", key=f"select_{i}", use_container_width=True):
                        st.session_state["selected_idea"] = idea
                        st.session_state["step"] = 3
                        st.rerun()
                elif st.session_state["selected_idea"] == idea:
                    st.success("선택됨")

    if st.session_state["step"] == 2:
        if st.button("🔄 아이디어 재생성", use_container_width=True):
            st.session_state["game_ideas"] = None
            st.session_state["selected_idea"] = None
            st.session_state["design_doc"] = None
            st.session_state["market_analysis"] = None
            st.session_state["step"] = 1
            st.rerun()

# ── Step 3: 기획 문서 생성 ──
if st.session_state["step"] >= 3 and st.session_state["selected_idea"]:
    st.header("Step 3: 기획 문서 생성")

    idea = st.session_state["selected_idea"]
    st.info(f"선택된 아이디어: **{idea['title']}** ({idea['genre']})")

    if st.session_state["design_doc"] is None:
        with st.spinner("AI가 핵심 메커니즘 중심의 기획 문서를 작성하고 있습니다..."):
            try:
                steam_data = st.session_state.get("steam_data")
                doc_market_patterns = (
                    format_market_patterns(steam_data, recent_years)
                    if steam_data and not isinstance(steam_data, str)
                    else ""
                )
                doc = generate_design_document(
                    idea, selected_engine, doc_market_patterns,
                )
                st.session_state["design_doc"] = doc
                st.rerun()
            except Exception as e:
                st.error(f"기획 문서 생성 실패: {e}")

    if st.session_state["design_doc"]:
        doc_html = markdown.markdown(
            st.session_state["design_doc"],
            extensions=["tables", "fenced_code"],
        )
        st.markdown(
            f'<div class="doc-frame">{doc_html}</div>',
            unsafe_allow_html=True,
        )

        st.divider()
        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            st.download_button(
                label="📥 마크다운 다운로드 (.md)",
                data=st.session_state["design_doc"],
                file_name=f"{idea['title']}_기획문서.md",
                mime="text/markdown",
                use_container_width=True,
            )
        with dl_col2:
            html_doc = convert_md_to_html(
                st.session_state["design_doc"], idea["title"],
            )
            st.download_button(
                label="📄 HTML 다운로드 (.html)",
                data=html_doc,
                file_name=f"{idea['title']}_기획문서.html",
                mime="text/html",
                use_container_width=True,
                help="브라우저에서 열고 Ctrl+P로 PDF 인쇄할 수 있습니다.",
            )
