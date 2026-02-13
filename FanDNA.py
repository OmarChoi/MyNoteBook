import streamlit as st
import json
from openai import OpenAI

# ──────────────────────────────────────────────
# 1. 설정 및 디자인 (Custom CSS)
# ──────────────────────────────────────────────

st.set_page_config(
    page_title="FanDNA | 스포츠 팀 매칭",
    page_icon="⚾",
    layout="centered",
)

def inject_custom_css():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Noto Sans KR', sans-serif;
    }
    
    [data-testid="stAppViewContainer"] {
        background: linear-gradient(135deg, #f0f4f8 0%, #d9e2ec 100%);
    }
    
    [data-testid="stHeader"] {
        background: rgba(0,0,0,0);
    }
    
    .main {
        background: transparent;
    }
    
    .stButton>button {
        width: 100%;
        border-radius: 12px;
        height: 3.5em;
        background: linear-gradient(135deg, #102a43 0%, #243b53 100%);
        color: white;
        font-weight: bold;
        border: none;
        box-shadow: 0 4px 14px 0 rgba(0,118,255,0.39);
        transition: all 0.3s ease;
    }
    
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }
    
    .match-card {
        background-color: white;
        padding: 24px;
        border-radius: 20px;
        box-shadow: 0 10px 25px rgba(0,0,0,0.05);
        margin-bottom: 20px;
        border-left: 8px solid #1e3c72;
    }
    
    .league-badge {
        background-color: #e9ecef;
        padding: 4px 12px;
        border-radius: 50px;
        font-size: 0.8em;
        font-weight: bold;
        color: #495057;
        margin-bottom: 10px;
        display: inline-block;
    }
    
    .match-rate {
        font-size: 2.5em;
        font-weight: bold;
        color: #1e3c72;
    }
    
    .hero-section {
        text-align: center;
        padding: 60px 20px;
        background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
        border-radius: 30px;
        color: white;
        margin-bottom: 40px;
    }
    
    .survey-container {
        background: white;
        padding: 30px;
        border-radius: 20px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.05);
    }
    
    h1, h2, h3 {
        color: #1e3c72;
    }
    </style>
    """, unsafe_allow_html=True)

inject_custom_css()

# OpenAI 클라이언트 설정 (game_planner.py 스타일 유지)
if "API_KEY" not in st.secrets or not st.secrets["API_KEY"] or st.secrets["API_KEY"] == "your-openai-api-key":
    st.error("🔑 API_KEY가 설정되지 않았습니다. `.streamlit/secrets.toml`에 OpenAI API 키를 입력해주세요.")
    st.stop()

client = OpenAI(api_key=st.secrets["API_KEY"])
MODEL = "gpt-4o-mini"

# ──────────────────────────────────────────────
# 2. 비즈니스 로직 (AI 기반 질문 및 추천 생성)
# ──────────────────────────────────────────────

DIMENSIONS = ["성취 지향성", "경기 스타일", "팬 경험", "회복 탄력성", "가치관"]

def generate_survey_questions():
    """OpenAI를 통해 매번 새로운 심리 테스트 질문 5개를 생성"""
    system_prompt = f"""
    당신은 대한민국 스포츠 팬들의 심리를 꿰뚫어 보는 재치 있는 분석가입니다. 
    사용자의 팬 성향을 분석하기 위한 '심리 테스트 질문' 5개를 생성하세요.
    
    [질문 생성 가이드라인]
    1. 다음 5가지 차원을 각각 하나씩 다루세요: {', '.join(DIMENSIONS)}.
    2. 질문은 '번역투'를 완전히 배제하고, 한국 스포츠 팬들이 커뮤니티(엠팍, 에펨코리아, 더쿠 등)나 경기장에서 실제로 쓸 법한 자연스러운 구어체를 사용하세요.
    3. 상황극 형태를 취하되, 문장이 딱딱하지 않고 몰입감 있게 작성하세요. (예: "당신은 ~합니다" 대신 "친구가 ~하자고 한다면?" 또는 "경기장에 갔는데 ~한 상황이라면?")
    4. 선택지(A, B, C)는 팬들의 '진심'이 느껴지는 말투여야 합니다. (예: "나는 승리를 원한다" -> "무조건 승리! 우승 아니면 의미 없죠")
    5. 한국 프로스포츠(KBO, K리그, KBL) 특유의 문화(직관, 먹거리, 응원가, 연고지 애착 등)를 적극 반영하세요.
    
    반드시 아래 JSON 배열 형식으로만 응답하십시오:
    [
      {{
        "id": "q1",
        "dimension": "차원명",
        "question": "자연스러운 한국어 질문 내용",
        "options": [
          {{"label": "실제 팬 같은 답변1", "value": "성향키워드1"}},
          {{"label": "실제 팬 같은 답변2", "value": "성향키워드2"}},
          {{"label": "실제 팬 같은 답변3", "value": "성향키워드3"}}
        ]
      }},
      ... (5개 반복)
    ]
    """
    
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": system_prompt}],
            response_format={"type": "json_object"}
        )
        # JSON 객체 내에 배열이 있을 수 있으므로 처리
        data = json.loads(response.choices[0].message.content)
        return data if isinstance(data, list) else data.get("questions", data.get("survey", []))
    except Exception as e:
        st.error(f"질문 생성 중 오류가 발생했습니다: {e}")
        return []

# ──────────────────────────────────────────────
# 2. 비즈니스 로직 (AI 기반 질문 및 추천 생성)
# ──────────────────────────────────────────────

def generate_survey_questions():
    """OpenAI를 통해 매번 새로운 심리 테스트 질문 10개를 생성"""
    system_prompt = """
    당신은 대한민국 스포츠 팬들의 심리를 꿰뚫어 보는 재치 있는 분석가입니다. 
    사용자의 팬 성향을 분석하기 위한 '심리 테스트 질문' 10개를 생성하세요.
    
    [질문 생성 가이드라인]
    1. 총 10개의 질문을 생성하며, 각 질문은 서로 다른 성향 차원을 다룹니다.
    2. 각 질문의 제목은 '1️⃣ 응원 스타일', '2️⃣ 플레이 스타일' 처럼 숫지 이모지와 카테고리 명칭을 사용하세요.
    3. 각 질문은 반드시 A, B, C, D 4개의 선택지를 가집니다.
    4. 선택지는 매우 짧고 명확하며, 팬들의 실제 말투를 반영하세요.
       (예: A. 전통과 역사 / B. 요즘 대세 / C. 몰아치기 / D. 낭만 서사)
    5. 한국 프로스포츠(KBO, K리그, KBL) 전반에 적용 가능한 보편적이고 흥미로운 질문으로 구성하세요.
    
    반드시 아래 JSON 배열 형식으로만 응답하십시오:
    [
      {
        "id": "q1",
        "category": "응원 스타일",
        "question_title": "1️⃣ 응원 스타일",
        "question": "당신이 팀을 선택할 때 가장 중요하게 생각하는 것은?",
        "options": [
          {"label": "A. 전통·역사·팬덤이 탄탄한 팀", "value": "tradition"},
          {"label": "B. 요즘 잘 나가고 트렌디한 팀", "value": "trendy"},
          {"label": "C. 한 번씩 미친 듯이 터지는 팀", "value": "explosion"},
          {"label": "D. 약해도 서사가 있는 팀", "value": "story"}
        ]
      },
      ... (10개 반복)
    ]
    """
    
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": system_prompt}],
            response_format={"type": "json_object"}
        )
        data = json.loads(response.choices[0].message.content)
        return data if isinstance(data, list) else data.get("questions", data.get("survey", []))
    except Exception as e:
        st.error(f"질문 생성 중 오류가 발생했습니다: {e}")
        return []
    """OpenAI API를 통해 팀 추천 결과 생성"""
    
    system_prompt = """
    당신은 대한민국 프로스포츠(KBO, K리그, KBL) 전문가입니다.
    사용자의 성향 분석 데이터를 바탕으로 각 리그별(야구, 축구, 농구) 최적의 팀을 추천하십시오.
    
    [추천 원칙]
    1. KBO(야구), K League(축구), KBL(농구)에서 각각 1팀씩 추천한다.
    2. 사용자의 답변 성향(공격/수비, 강팀/언더독 등)과 팀의 실제 역사, 팀 컬러를 매칭한다.
    3. 추천 사유는 사용자에게 직접 말을 거는 듯한 친절하고 전문적인 말투로 작성한다.
    
    반드시 아래 JSON 형식으로만 응답하십시오:
    {
      "personality_type": "사용자의 성향을 한 단어로 정의 (예: 뜨거운 심장의 전술가)",
      "summary": "사용자 성향에 대한 전체적인 분석 요약",
      "recommendations": [
        {
          "league": "KBO",
          "team": "팀명",
          "reason": "구체적인 매칭 사유",
          "match_rate": 0~100 사이 정수
        },
        ... (K리그, KBL 반복)
      ]
    }
    """
    
    user_content = f"사용자의 성향 데이터: {json.dumps(user_answers, ensure_ascii=False)}"
    
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        st.error(f"AI 분석 중 오류가 발생했습니다: {e}")
        return None

# ──────────────────────────────────────────────
# 4. UI 구성
# ──────────────────────────────────────────────

# 세션 상태 초기화
if "step" not in st.session_state:
    st.session_state.step = "start"
if "answers" not in st.session_state:
    st.session_state.answers = {}
if "selected_questions" not in st.session_state:
    st.session_state.selected_questions = []

# 메인 화면
if st.session_state.step == "start":
    st.markdown("""
        <div class="hero-section">
            <h1 style='color: white; margin-bottom: 0;'>🧬 FanDNA</h1>
            <p style='font-size: 1.2em; opacity: 0.9;'>스포츠 팬의 유전자를 분석하여 당신의 팀을 찾아드립니다</p>
        </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 6, 1])
    with col2:
        st.write("### 🏟️ 당신은 어떤 팬인가요?")
        st.write("""
        어떤 서사에 가슴이 뛰는지, 어떤 경기 방식에 열광하는지 분석합니다.
        KBO, K리그, KBL을 아우르는 당신만의 스포츠 포트폴리오를 완성해보세요.
        """)
        
        st.divider()
        if st.button("내 팬 DNA 분석 시작하기", type="primary"):
            with st.spinner("당신을 위한 맞춤형 질문을 생성하고 있습니다..."):
                questions = generate_survey_questions()
                if questions:
                    st.session_state.selected_questions = questions
                    st.session_state.step = "survey"
                    st.rerun()
                else:
                    st.error("질문을 생성하는 데 실패했습니다. 잠시 후 다시 시도해주세요.")

elif st.session_state.step == "survey":
    st.markdown("<h2 style='text-align: center; margin-bottom: 40px;'>📊 FanDNA 성향 분석</h2>", unsafe_allow_html=True)
    
    with st.container():
        with st.form("survey_form"):
            temp_answers = {}
            for i, q in enumerate(st.session_state.selected_questions):
                st.markdown(f"### {q.get('question_title', f'질문 {i+1}')}")
                st.write(f"{q['question']}")
                choice = st.radio(
                    label=q.get('category', f"cat_{i}"),
                    options=[opt['label'] for opt in q['options']],
                    index=0,
                    key=q['id'],
                    label_visibility="collapsed"
                )
                val = next(opt['value'] for opt in q['options'] if opt['label'] == choice)
                temp_answers[q.get('category', f"cat_{i}")] = val
                st.markdown("<br>", unsafe_allow_html=True)
            
            st.divider()
            submitted = st.form_submit_button("나의 결과 분석하기", type="primary", use_container_width=True)
            if submitted:
                st.session_state.answers = temp_answers
                st.session_state.step = "analyzing"
                st.rerun()

elif st.session_state.step == "analyzing":
    st.markdown("<div style='height: 200px;'></div>", unsafe_allow_html=True)
    st.markdown("<h2 style='text-align: center;'>🧠 당신의 DNA를 해독 중...</h2>", unsafe_allow_html=True)
    with st.spinner("10개의 답변을 바탕으로 당신의 팀을 정밀 분석하고 있습니다."):
        result = get_recommendation(st.session_state.answers)
        if result:
            st.session_state.result = result
            st.session_state.step = "result"
            st.rerun()

elif st.session_state.step == "result":
    result = st.session_state.result
    st.balloons()
    
    st.markdown(f"""
        <div style='text-align: center; margin-bottom: 50px;'>
            <p style='font-size: 1.5em; color: #666; margin-bottom: 0;'>분석 완료! 당신은</p>
            <h1 style='font-size: 3.5em; margin-top: 0;'>'{result['personality_type']}'</h1>
            <div style='background: #eef2f7; padding: 20px; border-radius: 15px; margin-top: 20px;'>
                {result['summary']}
            </div>
        </div>
    """, unsafe_allow_html=True)
        <div style='text-align: center; margin-bottom: 50px;'>
            <p style='font-size: 1.5em; color: #666; margin-bottom: 0;'>분석 완료! 당신은</p>
            <h1 style='font-size: 3.5em; margin-top: 0;'>'{result['personality_type']}'</h1>
            <div style='background: #eef2f7; padding: 20px; border-radius: 15px; margin-top: 20px;'>
                {result['summary']}
            </div>
        </div>
    """, unsafe_allow_html=True)
    
    st.subheader("🏟️ 리그별 추천 팀")
    
    for rec in result['recommendations']:
        st.markdown(f"""
            <div class="match-card">
                <div class="league-badge">{rec['league']}</div>
                <div style='display: flex; justify-content: space-between; align-items: center;'>
                    <div>
                        <h2 style='margin: 0; color: #1e3c72;'>{rec['team']}</h2>
                        <p style='margin-top: 10px; color: #444; line-height: 1.6;'>{rec['reason']}</p>
                    </div>
                    <div style='text-align: right; min-width: 120px;'>
                        <div style='font-size: 0.8em; color: #888;'>MATCH RATE</div>
                        <div class="match-rate">{rec['match_rate']}%</div>
                    </div>
                </div>
            </div>
        """, unsafe_allow_html=True)
    
    st.divider()
    if st.button("테스트 다시 하기", use_container_width=True):
        st.session_state.step = "start"
        st.session_state.answers = {}
        st.rerun()
