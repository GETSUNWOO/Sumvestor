import streamlit as st
import time
import gc
from datetime import datetime, timedelta, timezone

# 모든 유틸리티 함수 import
try:
    from youtube_utils import search_channel, get_videos_from_channel
    from transcript_utils import get_transcript, clean_transcript
    from gemini_utils import summarize_transcript
    from notion_utils import save_summary_to_notion, search_summaries_by_keyword, get_recent_summaries, get_database_stats
    from memory_manager import memory_manager, whisper_manager, memory_monitor_decorator, display_memory_info
except ImportError as e:
    st.error(f"모듈 import 오류: {e}")
    st.stop()

# Streamlit 페이지 설정
st.set_page_config(page_title="YouTube 요약 시스템", layout="wide")

# 메모리 모니터링 시작
if "memory_monitoring_started" not in st.session_state:
    memory_manager.start_monitoring(interval=10.0)  # 10초마다 체크
    st.session_state["memory_monitoring_started"] = True

st.title("📺 유튜브 요약 시스템 MVP")

# 메모리 정보 표시 (사이드바)
with st.sidebar:
    st.subheader("🖥️ 시스템 상태")
    display_memory_info()
    
    # Whisper 모델 상태
    if whisper_manager.is_loaded():
        model_info = whisper_manager.get_model_info()
        st.success(f"🤖 Whisper 모델: {model_info['size']}")
        if st.button("🗑️ 모델 해제"):
            whisper_manager.clear_model()
            st.rerun()
    else:
        st.info("🤖 Whisper 모델: 미로딩")

# 세션 상태 초기화
def init_session_state():
    defaults = {
        "selected_channel": None,
        "selected_channel_title": None,
        "video_list": [],
        "selected_videos": [],
        "video_list_loaded": False,
        "search_results": [],
        "processing_complete": False
    }
    
    for key, default_value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value

@memory_monitor_decorator
def process_summaries():
    """선택된 영상들을 요약 처리합니다. (메모리 누수 핫픽스 버전)"""
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
    
    # 메모리 안전을 위해 한 번에 1개씩만 처리
    st.warning(f"⚠️ 메모리 안정성을 위해 영상을 하나씩 처리합니다.")
    
    try:
        for i, video_info in enumerate(selected_video_info):
            video_id = video_info["video_id"]
            video_title = video_info["title"]
            
            # 진행률 업데이트
            progress = (i + 1) / total_videos
            progress_bar.progress(progress)
            status_text.text(f"처리 중... ({i + 1}/{total_videos}): {video_title[:50]}...")
            
            # 메모리 체크 (더 엄격하게)
            current_memory = memory_manager.get_memory_usage()["rss"]
            if current_memory > 800:  # 800MB 초과시
                results_container.warning(f"⚠️ 메모리 부족으로 처리 중단: {video_title}")
                memory_manager.force_cleanup(aggressive=True)
                break
            
            # 변수들을 None으로 명시적 초기화
            transcript = None
            clean_text = None
            summary_data = None
            
            try:
                # 1. 자막 수집
                with st.spinner(f"자막 수집 중: {video_title[:30]}..."):
                    transcript = get_transcript(video_id)
                
                if not transcript:
                    results_container.error(f"❌ 자막 수집 실패: {video_title}")
                    continue
                
                # 2. 자막 정리
                clean_text = clean_transcript(transcript)
                
                # 🔥 핵심: 원본 자막 즉시 해제
                del transcript
                transcript = None
                gc.collect()
                
                if len(clean_text.strip()) < 100:
                    results_container.warning(f"⚠️ 자막이 너무 짧음: {video_title}")
                    del clean_text
                    continue
                
                # 3. AI 요약 (Gemini 할당량 체크 추가)
                with st.spinner(f"AI 요약 중: {video_title[:30]}..."):
                    try:
                        summary_data = summarize_transcript(
                            clean_text, 
                            video_title, 
                            st.session_state["selected_channel_title"]
                        )
                    except Exception as gemini_error:
                        error_msg = str(gemini_error)
                        if "429" in error_msg or "quota" in error_msg.lower():
                            results_container.error(f"❌ Gemini API 할당량 초과")
                            st.error("⚠️ Gemini API 할당량 초과. 1분 후 다시 시도하거나 내일 사용해주세요.")
                            del clean_text
                            break  # 할당량 초과시 전체 처리 중단
                        else:
                            results_container.error(f"❌ 요약 오류: {error_msg}")
                            del clean_text
                            continue
                
                # 🔥 핵심: 정리된 자막 즉시 해제
                del clean_text
                clean_text = None
                gc.collect()
                
                if not summary_data:
                    results_container.error(f"❌ 요약 실패: {video_title}")
                    continue
                
                # 4. Notion 저장
                with st.spinner(f"저장 중: {video_title[:30]}..."):
                    save_success = save_summary_to_notion(summary_data, video_id)
                
                # 🔥 핵심: 요약 데이터 즉시 해제
                del summary_data
                summary_data = None
                gc.collect()
                
                if save_success:
                    results_container.success(f"✅ 완료: {video_title}")
                    success_count += 1
                else:
                    results_container.error(f"❌ 저장 실패: {video_title}")
            
            except Exception as e:
                results_container.error(f"❌ 오류 발생: {video_title} - {str(e)}")
            
            finally:
                # 🔥 핵심: 확실한 메모리 정리
                for var_name in ['transcript', 'clean_text', 'summary_data']:
                    if var_name in locals() and locals()[var_name] is not None:
                        del locals()[var_name]
                
                # 적극적 메모리 정리
                memory_manager.force_cleanup(aggressive=True)
                
                # 메모리 현황 출력
                current_mem = memory_manager.get_memory_usage()["rss"]
                print(f"🧹 {i+1}번째 영상 처리 후 메모리: {current_mem:.1f}MB")
            
            # API 호출 간격 (부하 방지 + 메모리 안정화)
            if i < total_videos - 1:  # 마지막이 아니면 대기
                time.sleep(5)  # 5초 대기
    
    finally:
        # 완료 메시지
        progress_bar.progress(1.0)
        status_text.text("처리 완료!")
        
        if success_count > 0:
            st.balloons()
            st.success(f"🎉 총 {success_count}개 영상 요약 완료!")
            st.session_state["processing_complete"] = True
        else:
            st.error("요약에 실패했습니다. 설정을 확인해주세요.")
        
        # 🔥 핵심: 최종 대청소
        memory_manager.force_cleanup(aggressive=True)
        memory_manager.cleanup_session_state(max_items=10)
        
        # 세션 상태에서 큰 데이터 정리
        if "video_list" in st.session_state and len(st.session_state["video_list"]) > 20:
            st.session_state["video_list"] = st.session_state["video_list"][-10:]
        
        if "search_results" in st.session_state:
            st.session_state["search_results"] = []
        
        # 최종 가비지 컬렉션
        for _ in range(3):
            gc.collect()
        
        final_mem = memory_manager.get_memory_usage()["rss"]
        print(f"🏁 최종 메모리 사용량: {final_mem:.1f}MB")


# 메인 실행 함수
def main():
    # 세션 상태 초기화
    init_session_state()
    
    # 주기적으로 세션 상태 정리 (더 자주)
    memory_manager.cleanup_session_state(max_items=20)
    
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
        
        # 폼을 사용하여 상태 관리 개선
        with st.form("channel_search_form"):
            query = st.text_input("유튜버 이름을 입력하세요:", placeholder="예: 신사임당, 부읽남")
            search_submitted = st.form_submit_button("🔍 채널 검색")

        if search_submitted and query:
            with st.spinner("검색 중..."):
                try:
                    channels = search_channel(query)
                    st.session_state["search_results"] = channels
                    # 검색 후 메모리 정리
                    gc.collect()
                except Exception as e:
                    st.error(f"검색 중 오류 발생: {e}")
                    st.session_state["search_results"] = []
        
        # 검색 결과 표시
        if st.session_state.get("search_results"):
            channels = st.session_state["search_results"]
            if not channels:
                st.warning("채널을 찾을 수 없습니다.")
            else:
                st.markdown("---")
                st.subheader("검색 결과")
                for i, ch in enumerate(channels):
                    with st.container():
                        col1, col2, col3 = st.columns([1, 4, 1])
                        with col1:
                            try:
                                st.image(ch["thumbnail_url"], width=100)
                            except:
                                st.write("🖼️")
                        with col2:
                            st.markdown(f"**{ch['channel_title']}**")
                            description = ch.get("description", "")
                            st.caption(description[:200] + "..." if len(description) > 200 else description)
                        with col3:
                            if st.button(f"선택", key=f"select_channel_{i}"):
                                st.session_state["selected_channel"] = ch["channel_id"]
                                st.session_state["selected_channel_title"] = ch["channel_title"]
                                st.session_state["search_results"] = []  # 검색 결과 초기화
                                gc.collect()  # 메모리 정리
                                st.rerun()

    # STEP 2: 채널 선택 이후 영상 목록
    else:
        col1, col2 = st.columns([3, 1])
        with col1:
            st.success(f"✅ 선택된 채널: **{st.session_state['selected_channel_title']}**")
        with col2:
            if st.button("🔄 채널 변경"):
                # 모든 관련 상태 초기화
                for key in ["selected_channel", "selected_channel_title", "video_list_loaded", 
                           "video_list", "selected_videos", "search_results", "processing_complete"]:
                    st.session_state[key] = None if "selected" in key else False if "loaded" in key or "complete" in key else []
                
                # 메모리 정리
                memory_manager.force_cleanup(aggressive=True)
                st.rerun()

        st.markdown("---")
        st.subheader("2️⃣ 영상 목록 필터링")
        
        col1, col2 = st.columns(2)
        with col1:
            date_option = st.selectbox("📅 기간 선택", ["전체", "최근 7일", "최근 30일"])
        with col2:
            # 메모리 안정성을 위해 적은 수로 제한
            max_results = st.selectbox("📊 최대 영상 수", [3, 5, 10], index=1)
            st.info("💡 메모리 안정성을 위해 적은 수를 권장합니다.")

        # datetime 경고 수정
        if date_option == "최근 7일":
            since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat("T").replace("+00:00", "Z")
        elif date_option == "최근 30일":
            since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat("T").replace("+00:00", "Z")
        else:
            since = None

        if st.button("📂 영상 목록 불러오기"):
            with st.spinner("영상 불러오는 중..."):
                try:
                    videos = get_videos_from_channel(
                        st.session_state["selected_channel"], 
                        published_after=since
                    )
                    st.session_state["video_list"] = videos[:max_results]
                    st.session_state["video_list_loaded"] = True
                    st.session_state["selected_videos"] = []
                    
                    # 메모리 정리
                    del videos
                    gc.collect()
                    
                    st.success(f"✅ {len(st.session_state['video_list'])}개 영상을 불러왔습니다!")
                except Exception as e:
                    st.error(f"영상 목록 불러오기 실패: {e}")

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
                        st.rerun()
                with col2:
                    if st.button("❌ 전체 해제"):
                        st.session_state["selected_videos"] = []
                        st.rerun()
                with col3:
                    st.info(f"📊 총 {len(st.session_state['video_list'])}개 영상, {len(st.session_state['selected_videos'])}개 선택됨")

                # 영상 목록 표시 (페이지네이션은 제거하고 단순화)
                for i, vid in enumerate(st.session_state["video_list"]):
                    with st.container():
                        col1, col2 = st.columns([1, 4])
                        
                        with col1:
                            try:
                                st.image(vid["thumbnail_url"], width=120)
                            except:
                                st.write("🖼️ 썸네일")
                        
                        with col2:
                            st.markdown(f"**{vid['title']}**")
                            st.caption(f"🕒 {vid['published_at'][:10]} | ⏱️ {vid.get('duration_formatted', 'N/A')}")
                            
                            # 체크박스 상태 동기화
                            current_selected = vid["video_id"] in st.session_state["selected_videos"]
                            is_selected = st.checkbox(
                                "선택", 
                                value=current_selected,
                                key=f"video_{vid['video_id']}"
                            )
                            
                            # 상태 업데이트
                            if is_selected != current_selected:
                                if is_selected:
                                    if vid["video_id"] not in st.session_state["selected_videos"]:
                                        st.session_state["selected_videos"].append(vid["video_id"])
                                else:
                                    if vid["video_id"] in st.session_state["selected_videos"]:
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
                    with col2:
                        if st.session_state.get("processing_complete"):
                            st.success("🎉 처리 완료!")
                    
                    # 메모리 상태 및 권장사항
                    current_memory = memory_manager.get_memory_usage()["rss"]
                    selected_count = len(st.session_state['selected_videos'])
                    
                    if current_memory > 500:
                        st.warning(f"⚠️ 현재 메모리: {current_memory:.0f}MB. 메모리 정리를 권장합니다.")
                        if st.button("🗑️ 메모리 정리 후 계속"):
                            memory_manager.force_cleanup(aggressive=True)
                            whisper_manager.clear_model()
                            st.rerun()
                    
                    if selected_count > 3:
                        st.warning(f"⚠️ {selected_count}개 영상 선택됨. 메모리 안정성을 위해 3개 이하를 권장합니다.")
                    
                    # Gemini API 할당량 주의사항
                    st.info("💡 Gemini API 할당량: 분당 250K 토큰 제한. 할당량 초과시 처리가 중단됩니다.")
                    
                    if st.button("🧠 선택한 영상 요약 시작", type="primary"):
                        st.session_state["processing_complete"] = False
                        process_summaries()

def show_search_page():
    st.header("🔍 요약 검색하기")
    
    # 검색 옵션
    search_type = st.radio("검색 방법:", ["키워드 검색", "최근 요약 보기"])
    
    if search_type == "키워드 검색":
        with st.form("keyword_search_form"):
            keyword = st.text_input("검색할 키워드를 입력하세요:", placeholder="예: 삼성전자, 반도체, 금리")
            search_submitted = st.form_submit_button("🔍 검색")
        
        if search_submitted and keyword:
            with st.spinner("검색 중..."):
                try:
                    results = search_summaries_by_keyword(keyword)
                    # 검색 후 메모리 정리
                    gc.collect()
                except Exception as e:
                    st.error(f"검색 중 오류 발생: {e}")
                    results = []
                
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
                            if result.get('notion_url'):
                                st.link_button("📝 Notion에서 보기", result['notion_url'])
                            if result.get('video_id'):
                                st.link_button("🎬 YouTube에서 보기", f"https://youtube.com/watch?v={result['video_id']}")
    
    else:  # 최근 요약 보기
        days = st.selectbox("기간 선택:", [7, 14, 30], format_func=lambda x: f"최근 {x}일")
        
        if st.button("📂 최근 요약 불러오기"):
            with st.spinner("불러오는 중..."):
                try:
                    results = get_recent_summaries(days)
                    gc.collect()  # 메모리 정리
                except Exception as e:
                    st.error(f"불러오기 중 오류 발생: {e}")
                    results = []
            
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
                            if result.get('notion_url'):
                                st.link_button("📝 Notion에서 보기", result['notion_url'])

def show_dashboard_page():
    st.header("📊 요약 대시보드")
    
    # 통계 불러오기
    with st.spinner("통계 불러오는 중..."):
        try:
            stats = get_database_stats()
            gc.collect()  # 메모리 정리
        except Exception as e:
            st.error(f"통계 불러오기 실패: {e}")
            stats = {"total_summaries": 0, "sentiment_distribution": {}, "top_channels": []}
    
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
            import pandas as pd
            sentiment_df = pd.DataFrame(
                list(stats["sentiment_distribution"].items()),
                columns=['감성', '개수']
            )
            st.bar_chart(sentiment_df.set_index('감성'))
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
    
    # API 키 상태 확인
    import os
    from dotenv import load_dotenv
    load_dotenv()
    
    api_status = {
        "YouTube API": "✅" if os.getenv("YOUTUBE_API_KEY") else "❌",
        "Gemini API": "✅" if os.getenv("GEMINI_API_KEY") else "❌",
        "Notion Token": "✅" if os.getenv("NOTION_TOKEN") else "❌",
        "Notion Database ID": "✅" if os.getenv("NOTION_DATABASE_ID") else "❌"
    }
    
    st.subheader("📋 API 키 상태")
    for api_name, status in api_status.items():
        st.write(f"{status} {api_name}")
    
    # 메모리 관리 설정
    st.subheader("🖥️ 메모리 관리 설정")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🗑️ 전체 메모리 정리"):
            memory_manager.force_cleanup(aggressive=True)
            memory_manager.cleanup_session_state(max_items=10)
            # 세션 상태 대청소
            large_keys = ["video_list", "search_results"]
            for key in large_keys:
                if key in st.session_state:
                    st.session_state[key] = []
            gc.collect()
            st.success("메모리 정리 완료!")
            st.rerun()
    
    with col2:
        if st.button("🤖 Whisper 모델 해제"):
            whisper_manager.clear_model()
            st.success("모델 해제 완료!")
            st.rerun()
    
    # 메모리 사용량 임계값 설정
    st.subheader("⚙️ 메모리 임계값 설정")
    threshold = st.slider("메모리 경고 임계값 (MB)", 300, 1000, 500, 50)
    st.info(f"메모리 사용량이 {threshold}MB를 초과하면 경고가 표시됩니다.")
    
    # Gemini API 사용량 정보
    st.subheader("🤖 Gemini API 정보")
    st.info("""
    **무료 할당량:** 분당 250,000 토큰
    **권장사항:** 
    - 한 번에 3개 이하 영상 처리
    - 할당량 초과시 1분 대기 후 재시도
    - 긴 영상(1시간+)은 주의
    """)
    
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
    
    st.subheader("📚 메모리 최적화 가이드")
    with st.expander("🎯 메모리 절약 팁"):
        st.markdown("""
        **메모리 사용량 최적화 방법:**
        
        1. **영상 처리 개수 조절**
           - 한 번에 1-3개씩 처리 권장
           - 메모리 500MB 초과시 정리 실행
        
        2. **자동 정리 활용**
           - 각 영상 처리 후 자동 메모리 정리
           - 큰 데이터는 즉시 삭제
        
        3. **브라우저 관리**
           - 장시간 사용시 새로고침 권장
           - 다른 탭들도 메모리 영향
        
        4. **STT 사용 최적화**
           - 긴 영상(30분+)은 주의
           - 모델은 필요시에만 로딩
        """)
    
    with st.expander("🔧 문제 해결"):
        st.markdown("""
        **발생 가능한 문제들:**
        
        1. **메모리 부족 오류**
           - "전체 메모리 정리" 버튼 클릭
           - 처리할 영상 수 줄이기 (1-2개)
           - 브라우저 새로고침
        
        2. **Gemini API 할당량 초과**
           - 1분 대기 후 재시도
           - 영상 수 줄이기
           - 내일 다시 시도
        
        3. **시스템 응답 느림**
           - 메모리 사용량 확인
           - Whisper 모델 해제
           - 브라우저 재시작
        
        4. **STT 처리 실패**
           - 메모리 부족 가능성
           - 더 짧은 영상으로 테스트
           - 모델 해제 후 재시도
        """)

if __name__ == "__main__":
    main()