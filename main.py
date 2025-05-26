import streamlit as st
import time
from datetime import datetime, timedelta

# 모든 유틸리티 함수 import
try:
    from youtube_utils import search_channel, get_videos_from_channel
    from transcript_utils import get_transcript, clean_transcript
    from gemini_utils import summarize_transcript
    from notion_utils import save_summary_to_notion, search_summaries_by_keyword, get_recent_summaries, get_database_stats
except ImportError as e:
    st.error(f"모듈 import 오류: {e}")
    st.stop()

# Streamlit 페이지 설정
st.set_page_config(page_title="YouTube 요약 시스템", layout="wide")
st.title("📺 유튜브 요약 시스템 MVP")

# 세션 상태 초기화
def init_session_state():
    if "selected_channel" not in st.session_state:
        st.session_state["selected_channel"] = None
        st.session_state["selected_channel_title"] = None
    if "video_list" not in st.session_state:
        st.session_state["video_list"] = []
    if "selected_videos" not in st.session_state:
        st.session_state["selected_videos"] = []
    if "video_list_loaded" not in st.session_state:
        st.session_state["video_list_loaded"] = False

# 요약 처리 함수
def process_summaries():
    """선택된 영상들을 요약 처리합니다."""
    if not st.session_state["selected_videos"]:
        st.error("선택된 영상이 없습니다.")
        return
    
    # 선택된 영상 정보 가져오기
    selected_video_info = []
    for video_id in st.session_state["selected_videos"]:
        for vid in st.session_state["video_list"]:
            if vid["video_id"] == video_id:
                selected_video_info.append(vid)
                break
    
    # 진행률 표시
    progress_bar = st.progress(0)
    status_text = st.empty()
    results_container = st.container()
    
    total_videos = len(selected_video_info)
    success_count = 0
    
    for i, video_info in enumerate(selected_video_info):
        video_id = video_info["video_id"]
        video_title = video_info["title"]
        
        # 진행률 업데이트
        progress = (i + 1) / total_videos
        progress_bar.progress(progress)
        status_text.text(f"처리 중... ({i + 1}/{total_videos}): {video_title[:50]}...")
        
        try:
            # 1. 자막 수집
            transcript = get_transcript(video_id)
            
            if not transcript:
                results_container.error(f"❌ 자막 수집 실패: {video_title}")
                continue
            
            # 2. 자막 정리
            clean_text = clean_transcript(transcript)
            
            # 3. AI 요약
            summary_data = summarize_transcript(
                clean_text, 
                video_title, 
                st.session_state["selected_channel_title"]
            )
            
            if not summary_data:
                results_container.error(f"❌ 요약 실패: {video_title}")
                continue
            
            # 4. Notion 저장
            save_success = save_summary_to_notion(summary_data, video_id)
            
            if save_success:
                results_container.success(f"✅ 완료: {video_title}")
                success_count += 1
            else:
                results_container.error(f"❌ 저장 실패: {video_title}")
        
        except Exception as e:
            results_container.error(f"❌ 오류 발생: {video_title} - {str(e)}")
        
        # API 호출 간격
        time.sleep(1)
    
    # 완료 메시지
    progress_bar.progress(1.0)
    status_text.text("처리 완료!")
    
    if success_count > 0:
        st.balloons()
        st.success(f"🎉 총 {success_count}개 영상 요약 완료!")
    else:
        st.error("요약에 실패했습니다. 설정을 확인해주세요.")

# 메인 실행 함수
def main():
    # 세션 상태 초기화
    init_session_state()
    
    # 사이드바 메뉴
    st.sidebar.title("🎯 메뉴")
    menu = st.sidebar.selectbox(
        "원하는 기능을 선택하세요:",
        ["영상 요약하기", "요약 검색하기", "대시보드", "설정"]
    )
    
    if menu == "영상 요약하기":
        show_summary_page()
    elif menu == "요약 검색하기":
        show_search_page()
    elif menu == "대시보드":
        show_dashboard_page()
    elif menu == "설정":
        show_settings_page()

def show_summary_page():
    st.header("🎬 영상 요약하기")
    
    # STEP 1: 채널 검색 및 선택
    if st.session_state["selected_channel"] is None:
        st.subheader("1️⃣ 유튜버 채널 선택")
        query = st.text_input("유튜버 이름을 입력하세요:", placeholder="예: 신사임당, 부읽남")

        if st.button("🔍 채널 검색") and query:
            with st.spinner("검색 중..."):
                channels = search_channel(query)
                if not channels:
                    st.warning("채널을 찾을 수 없습니다.")
                else:
                    st.markdown("---")
                    st.subheader("검색 결과")
                    for ch in channels:
                        col1, col2 = st.columns([1, 4])
                        with col1:
                            st.image(ch["thumbnail_url"], width=100)
                        with col2:
                            st.markdown(f"**{ch['channel_title']}**")
                            st.caption(ch["description"][:200] + "..." if len(ch["description"]) > 200 else ch["description"])
                            if st.button(f"✅ 이 채널 선택", key=ch["channel_id"]):
                                st.session_state["selected_channel"] = ch["channel_id"]
                                st.session_state["selected_channel_title"] = ch["channel_title"]
                                st.success(f"채널 선택됨: {ch['channel_title']}")
                                # st.rerun() 제거 - 자동으로 다음 단계로 진행됨

    # STEP 2: 채널 선택 이후 영상 목록
    else:
        col1, col2 = st.columns([3, 1])
        with col1:
            st.success(f"✅ 선택된 채널: **{st.session_state['selected_channel_title']}**")
        with col2:
            if st.button("🔄 채널 변경"):
                st.session_state["selected_channel"] = None
                st.session_state["selected_channel_title"] = None
                st.session_state["video_list_loaded"] = False
                st.session_state["video_list"] = []
                st.session_state["selected_videos"] = []
                st.success("채널 선택이 초기화되었습니다.")

        st.markdown("---")
        st.subheader("2️⃣ 영상 목록 필터링")
        
        col1, col2 = st.columns(2)
        with col1:
            date_option = st.selectbox("📅 기간 선택", ["전체", "최근 7일", "최근 30일"])
        with col2:
            max_results = st.selectbox("📊 최대 영상 수", [10, 20, 50], index=1)

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
                )[:max_results]
                st.session_state["video_list_loaded"] = True
                st.session_state["selected_videos"] = []
                st.success(f"✅ {len(st.session_state['video_list'])}개 영상을 불러왔습니다!")

        # STEP 3: 영상 선택
        if st.session_state["video_list_loaded"]:
            st.markdown("---")
            st.subheader("3️⃣ 요약할 영상 선택")
            
            if not st.session_state["video_list"]:
                st.warning("해당 기간에 업로드된 영상이 없습니다.")
            else:
                # 전체 선택/해제 버튼
                col1, col2, col3 = st.columns([1, 1, 2])
                with col1:
                    if st.button("✅ 전체 선택"):
                        st.session_state["selected_videos"] = [vid["video_id"] for vid in st.session_state["video_list"]]
                        st.success("모든 영상이 선택되었습니다!")
                with col2:
                    if st.button("❌ 전체 해제"):
                        st.session_state["selected_videos"] = []
                        st.success("선택이 해제되었습니다!")
                with col3:
                    st.info(f"📊 총 {len(st.session_state['video_list'])}개 영상, {len(st.session_state['selected_videos'])}개 선택됨")

                # 영상 목록 표시
                for i, vid in enumerate(st.session_state["video_list"]):
                    with st.container():
                        col1, col2 = st.columns([1, 4])
                        
                        with col1:
                            st.image(vid["thumbnail_url"], width=120)
                        
                        with col2:
                            st.markdown(f"**{vid['title']}**")
                            st.caption(f"🕒 {vid['published_at'][:10]}")
                            
                            # 체크박스
                            is_selected = st.checkbox(
                                "선택", key=f"video_{vid['video_id']}"
                            )
                            
                            if is_selected and vid["video_id"] not in st.session_state["selected_videos"]:
                                st.session_state["selected_videos"].append(vid["video_id"])
                            elif not is_selected and vid["video_id"] in st.session_state["selected_videos"]:
                                st.session_state["selected_videos"].remove(vid["video_id"])
                    
                    if i < len(st.session_state["video_list"]) - 1:
                        st.divider()

                # STEP 4: 요약 실행
                if st.session_state["selected_videos"]:
                    st.markdown("---")
                    st.subheader("4️⃣ 요약 실행")
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.success(f"✅ {len(st.session_state['selected_videos'])}개 영상 선택됨")
                    
                    if st.button("🧠 선택한 영상 요약 시작", type="primary"):
                        process_summaries()

def show_search_page():
    st.header("🔍 요약 검색하기")
    
    # 검색 옵션
    search_type = st.radio("검색 방법:", ["키워드 검색", "최근 요약 보기"])
    
    if search_type == "키워드 검색":
        keyword = st.text_input("검색할 키워드를 입력하세요:", placeholder="예: 삼성전자, 반도체, 금리")
        
        if st.button("🔍 검색") and keyword:
            with st.spinner("검색 중..."):
                results = search_summaries_by_keyword(keyword)
                
            if not results:
                st.warning("검색 결과가 없습니다.")
            else:
                st.success(f"🎯 {len(results)}개의 결과를 찾았습니다.")
                
                for result in results:
                    with st.expander(f"📺 {result['title']} - {result['channel']}"):
                        col1, col2 = st.columns([3, 1])
                        with col1:
                            st.write(f"**채널:** {result['channel']}")
                            st.write(f"**키워드:** {', '.join(result['keywords'])}")
                            st.write(f"**감성:** {result['sentiment']}")
                            st.write(f"**요약 일시:** {result['created_time'][:10]}")
                        with col2:
                            st.link_button("📝 Notion에서 보기", result['notion_url'])
                            st.link_button("🎬 YouTube에서 보기", f"https://youtube.com/watch?v={result['video_id']}")
    
    else:  # 최근 요약 보기
        days = st.selectbox("기간 선택:", [7, 14, 30], format_func=lambda x: f"최근 {x}일")
        
        if st.button("📂 최근 요약 불러오기"):
            with st.spinner("불러오는 중..."):
                results = get_recent_summaries(days)
            
            if not results:
                st.warning("해당 기간의 요약이 없습니다.")
            else:
                st.success(f"📊 최근 {days}일간 {len(results)}개의 요약을 찾았습니다.")
                
                for result in results:
                    with st.expander(f"📺 {result['title']} - {result['channel']}"):
                        col1, col2 = st.columns([3, 1])
                        with col1:
                            st.write(f"**채널:** {result['channel']}")
                            st.write(f"**키워드:** {', '.join(result['keywords'])}")
                            st.write(f"**감성:** {result['sentiment']}")
                            st.write(f"**요약 일시:** {result['created_time'][:10]}")
                        with col2:
                            st.link_button("📝 Notion에서 보기", result['notion_url'])

def show_dashboard_page():
    st.header("📊 요약 대시보드")
    
    # 통계 불러오기
    with st.spinner("통계 불러오는 중..."):
        stats = get_database_stats()
    
    # 전체 통계
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("전체 요약 수", stats["total_summaries"])
    with col2:
        positive_ratio = (stats["sentiment_distribution"].get("긍정적", 0) / max(stats["total_summaries"], 1)) * 100
        st.metric("긍정적 비율", f"{positive_ratio:.1f}%")
    with col3:
        negative_ratio = (stats["sentiment_distribution"].get("부정적", 0) / max(stats["total_summaries"], 1)) * 100
        st.metric("부정적 비율", f"{negative_ratio:.1f}%")
    with col4:
        neutral_ratio = (stats["sentiment_distribution"].get("중립적", 0) / max(stats["total_summaries"], 1)) * 100
        st.metric("중립적 비율", f"{neutral_ratio:.1f}%")
    
    st.markdown("---")
    
    # 감성 분포 차트
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📈 감성 분포")
        if stats["sentiment_distribution"]:
            sentiment_data = list(stats["sentiment_distribution"].items())
            st.bar_chart({item[0]: item[1] for item in sentiment_data})
        else:
            st.info("데이터가 없습니다.")
    
    with col2:
        st.subheader("🏆 TOP 채널")
        if stats["top_channels"]:
            for i, (channel, count) in enumerate(stats["top_channels"], 1):
                st.write(f"{i}. **{channel}** ({count}개)")
        else:
            st.info("데이터가 없습니다.")

def show_settings_page():
    st.header("⚙️ 설정")
    
    st.subheader("🔑 API 키 설정")
    st.info("환경변수 파일(.env)에서 API 키를 설정해주세요.")
    
    with st.expander("📋 필요한 환경변수 목록"):
        st.code("""
# YouTube API
YOUTUBE_API_KEY=your_youtube_api_key

# Gemini API  
GEMINI_API_KEY=your_gemini_api_key

# Notion API
NOTION_TOKEN=your_notion_token
NOTION_DATABASE_ID=your_database_id
        """)
    
    st.subheader("📚 사용 가이드")
    with st.expander("🎯 Notion 데이터베이스 설정 방법"):
        st.markdown("""
        1. Notion에서 새 데이터베이스 생성
        2. 다음 속성들을 추가:
           - 제목 (Title)
           - 채널 (Text)
           - Video ID (Text)  
           - 키워드 (Multi-select)
           - 감성 (Select: 긍정적, 중립적, 부정적)
           - 요약 일시 (Date)
           - YouTube URL (URL)
        3. 데이터베이스 ID를 .env 파일에 추가
        """)

if __name__ == "__main__":
    main()