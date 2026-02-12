import streamlit as st

st.title("안녕하세요")
if st.button("노크하기"):
    st.write("사람 있습니다~.")

st.write("동의하시면 아래 내용에 체크해주세요.")
agree = st.checkbox("동의합니다")
if agree:
    st.write("당신은 동의햤습니다.")

option = st.selectbox("연락을 어떻게 받을래요?", ("이메일", "전화", "문자"))
st.write("선택한 방식: " + option)

age = st.slider("당신은 몇 살인가요?", 0, 100)
st.write("저는 " + str(age) + "살 입니다!")

text_name = st.text_input("이름을 입력해주세요.")
text_intro = st.text_area("자기소개 해주세요.")

st.image("https://picsum.photos/1280/720")

# streamlit run app.py