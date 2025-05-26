import streamlit as st
from youtube_utils import search_channel, get_videos_from_channel
from datetime import datetime, timedelta

st.set_page_config(page_title="YouTube 요약 시스템", layout="wide")
st.title("📺 유튜브 요약 시스템 MVP")

# 초기 세션 상태 설정
if "selected_channel" not in st.session_state:
    st.session_state["selected_channel"] = None
    st.session_state["selected_channel_title"] = None

if "video_list" not in st.session_state:
    st.session_state["video_list"] = []

if "selected_videos" not in st.session_state:
    st.session_state["selected_videos"] = []

if "video_list_loaded" not in st.session_state:
    st.session_state["video_list_loaded"] = False

# STEP 1: 채널 검색 및 선택
if st.session_state["selected_channel"] is None:
    query = st.text_input("유튜버 이름을 입력하세요:")

    if st.button("🔍 채널 검색") and query:
        with st.spinner("검색 중..."):
            channels = search_channel(query)
            if not channels:
                st.warning("채널을 찾을 수 없습니다.")
            else:
                st.markdown("---")
                for ch in channels:
                    st.image(ch["thumbnail_url"], width=100)
                    st.markdown(f"**{ch['channel_title']}**")
                    st.caption(ch["description"])
                    if st.button(f"✅ 이 채널 선택", key=ch["channel_id"]):
                        st.session_state["selected_channel"] = ch["channel_id"]
                        st.session_state["selected_channel_title"] = ch["channel_title"]
                        st.experimental_rerun()

# STEP 2: 채널 선택 이후
else:
    st.success(f"선택된 채널: {st.session_state['selected_channel_title']}")

    if st.button("🔁 채널 다시 선택"):
        st.session_state["selected_channel"] = None
        st.session_state["selected_channel_title"] = None
        st.session_state["video_list_loaded"] = False
        st.session_state["video_list"] = []
        st.session_state["selected_videos"] = []
        st.experimental_rerun()

    st.markdown("### 🎞 영상 목록 필터링")
    date_option = st.selectbox("기간 선택", ["전체", "최근 7일", "최근 30일"])

    if date_option == "최근 7일":
        since = (datetime.utcnow() - timedelta(days=7)).isoformat("T") + "Z"
    elif date_option == "최근 30일":
        since = (datetime.utcnow() - timedelta(days=30)).isoformat("T") + "Z"
    else:
        since = None

    if st.button("📂 영상 목록 불러오기"):
        with st.spinner("영상 불러오는 중..."):
            st.session_state["video_list"] = get_videos_from_channel(
                st.session_state["selected_channel"], published_after=since
            )
            st.session_state["video_list_loaded"] = True
            st.session_state["selected_videos"] = []  # 초기화
            st.experimental_rerun()

    # 영상 목록이 로딩된 경우
    if st.session_state["video_list_loaded"]:
        st.markdown("---")
        for vid in st.session_state["video_list"]:
            st.image(vid["thumbnail_url"], width=120)
            st.write(f"📌 **{vid['title']}**")
            st.write(f"🕒 {vid['published_at']}")
            is_selected = st.checkbox(
                "이 영상 요약할래요", key=vid["video_id"]
            )
            if is_selected and vid["video_id"] not in st.session_state["selected_videos"]:
                st.session_state["selected_videos"].append(vid["video_id"])
            elif not is_selected and vid["video_id"] in st.session_state["selected_videos"]:
                st.session_state["selected_videos"].remove(vid["video_id"])
            st.markdown("---")

        if st.session_state["selected_videos"]:
            st.success(f"✅ {len(st.session_state['selected_videos'])}개 영상 선택됨")
            if st.button("🧠 선택한 영상 요약하기"):
                st.write("선택된 영상 ID 목록:")
                st.json(st.session_state["selected_videos"])
                # TODO: 요약 API 호출
