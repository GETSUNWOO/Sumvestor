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

if "search_results" not in st.session_state:
    st.session_state["search_results"] = []

# STEP 1: 채널 검색 및 선택
if st.session_state["selected_channel"] is None:
    st.markdown("### 🔍 채널 검색")
    query = st.text_input("유튜버 이름을 입력하세요:")

    if st.button("🔍 채널 검색") and query:
        with st.spinner("검색 중..."):
            channels = search_channel(query)
            if not channels:
                st.warning("채널을 찾을 수 없습니다.")
            else:
                st.session_state["search_results"] = channels

    # 검색 결과 표시
    if st.session_state["search_results"]:
        st.markdown("---")
        st.markdown("### 📺 검색된 채널 목록")
        
        for i, ch in enumerate(st.session_state["search_results"]):
            col1, col2, col3 = st.columns([1, 4, 1])
            
            with col1:
                st.image(ch["thumbnail_url"], width=80)
            
            with col2:
                st.markdown(f"**{ch['channel_title']}**")
                st.caption(ch["description"][:100] + "..." if len(ch["description"]) > 100 else ch["description"])
            
            with col3:
                if st.button("✅ 선택", key=f"select_{ch['channel_id']}"):
                    st.session_state["selected_channel"] = ch["channel_id"]
                    st.session_state["selected_channel_title"] = ch["channel_title"]
                    st.session_state["search_results"] = []  # 검색 결과 초기화
                    st.rerun()

# STEP 2: 채널 선택 이후
else:
    # 선택된 채널 정보 표시
    st.success(f"✅ 선택된 채널: **{st.session_state['selected_channel_title']}**")
    
    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("🔄 채널 다시 선택"):
            # 모든 상태 초기화
            st.session_state["selected_channel"] = None
            st.session_state["selected_channel_title"] = None
            st.session_state["video_list_loaded"] = False
            st.session_state["video_list"] = []
            st.session_state["selected_videos"] = []
            st.session_state["search_results"] = []
            st.rerun()

    st.markdown("---")
    st.markdown("### 🎞️ 영상 목록 필터링")
    
    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        date_option = st.selectbox("📅 기간 선택", ["전체", "최근 7일", "최근 30일"])
    
    with col2:
        exclude_shorts = st.checkbox("🚫 쇼츠 제외", value=True)
    
    with col3:
        st.write("")  # 빈 공간
        if st.button("📂 영상 목록 불러오기"):
            with st.spinner("영상 목록을 불러오는 중..."):
                # 날짜 필터 설정
                if date_option == "최근 7일":
                    since = (datetime.utcnow() - timedelta(days=7)).isoformat("T") + "Z"
                elif date_option == "최근 30일":
                    since = (datetime.utcnow() - timedelta(days=30)).isoformat("T") + "Z"
                else:
                    since = None
                
                # 영상 목록 가져오기
                video_list = get_videos_from_channel(
                    st.session_state["selected_channel"], 
                    published_after=since,
                    exclude_shorts=exclude_shorts
                )
                
                st.session_state["video_list"] = video_list
                st.session_state["video_list_loaded"] = True
                st.session_state["selected_videos"] = []  # 선택된 영상 초기화
                
                st.success(f"✅ {len(video_list)}개의 영상을 불러왔습니다!")

    # 영상 목록이 로딩된 경우
    if st.session_state["video_list_loaded"] and st.session_state["video_list"]:
        st.markdown("---")
        st.markdown("### 🎥 영상 목록")
        st.caption(f"총 {len(st.session_state['video_list'])}개의 영상")
        
        # 선택된 영상 수 표시
        if st.session_state["selected_videos"]:
            st.info(f"🎯 {len(st.session_state['selected_videos'])}개 영상이 선택되었습니다.")
        
        # 영상 목록 표시
        for i, vid in enumerate(st.session_state["video_list"]):
            with st.container():
                col1, col2, col3 = st.columns([1, 4, 1])
                
                with col1:
                    st.image(vid["thumbnail_url"], width=120)
                
                with col2:
                    st.markdown(f"**{vid['title']}**")
                    # 날짜 포맷 개선
                    pub_date = datetime.fromisoformat(vid['published_at'].replace('Z', '+00:00'))
                    formatted_date = pub_date.strftime("%Y-%m-%d %H:%M")
                    
                    # 지속시간 표시
                    duration_info = f"⏱️ {vid.get('duration_formatted', 'N/A')}"
                    st.caption(f"🕒 {formatted_date} | {duration_info}")
                
                with col3:
                    # 체크박스의 고유한 키 생성
                    checkbox_key = f"select_video_{i}_{vid['video_id']}"
                    
                    # 현재 선택 상태 확인
                    is_currently_selected = vid["video_id"] in st.session_state["selected_videos"]
                    
                    # 체크박스 (on_change 콜백 사용)
                    def toggle_video_selection():
                        video_id = vid["video_id"]
                        if st.session_state[checkbox_key]:
                            # 체크박스가 선택됨
                            if video_id not in st.session_state["selected_videos"]:
                                st.session_state["selected_videos"].append(video_id)
                        else:
                            # 체크박스가 해제됨
                            if video_id in st.session_state["selected_videos"]:
                                st.session_state["selected_videos"].remove(video_id)
                    
                    st.checkbox(
                        "요약 선택", 
                        value=is_currently_selected,
                        key=checkbox_key,
                        on_change=toggle_video_selection
                    )
                
                st.markdown("---")

        # 선택된 영상이 있으면 요약 버튼 표시
        if st.session_state["selected_videos"]:
            st.markdown("### 🧠 요약 실행")
            
            col1, col2 = st.columns([1, 1])
            with col1:
                st.metric("선택된 영상", f"{len(st.session_state['selected_videos'])}개")
            
            with col2:
                if st.button("🚀 선택한 영상 요약하기", type="primary"):
                    st.write("### 📋 선택된 영상 목록:")
                    for vid_id in st.session_state["selected_videos"]:
                        # 선택된 영상의 제목 찾기
                        selected_video = next(
                            (v for v in st.session_state["video_list"] if v["video_id"] == vid_id), 
                            None
                        )
                        if selected_video:
                            st.write(f"- {selected_video['title']}")
                    
                    st.info("🔧 요약 기능은 아직 개발 중입니다!")
                    # TODO: 여기에 요약 API 호출 로직 추가
    
    elif st.session_state["video_list_loaded"] and not st.session_state["video_list"]:
        st.warning("⚠️ 해당 기간에 업로드된 영상이 없습니다. 다른 기간을 선택해보세요.")