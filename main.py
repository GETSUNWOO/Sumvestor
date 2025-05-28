import streamlit as st
import time
import gc
from datetime import datetime, timedelta, timezone

# 모든 유틸리티 함수 import (수정된 import 경로)
try:
    from youtube_utils import search_channel, get_videos_from_channel
    from transcript_utils import get_transcript, clean_transcript
    from gemini_utils import summarize_transcript
    from notion_utils import save_summary_to_notion, search_summaries_by_keyword, get_recent_summaries, get_database_stats
    from memory_manager import memory_manager, memory_monitor_decorator, display_memory_info
    
    # 수정된 import 경로 (safe_stt_engine.py)
    from safe_stt_engine import (
        get_safe_stt_engine, cleanup_safe_stt_engine, reset_session_costs,
        STTConfig, STTProvider, SafetyLimits
    )
except ImportError as e:
    st.error(f"모듈 import 오류: {e}")
    st.info("누락된 모듈을 설치하거나 파일명을 확인하세요.")
    st.stop()

# Streamlit 페이지 설정
st.set_page_config(
    page_title="YouTube 요약 시스템 v2 (Safe)", 
    layout="wide"
)

# 메모리 모니터링 시작
if "memory_monitoring_started" not in st.session_state:
    memory_manager.start_monitoring(interval=10.0)
    st.session_state["memory_monitoring_started"] = True

st.title("📺 유튜브 요약 시스템 v2.0 (비용 안전 보장)")

# 사이드바 - 시스템 상태 및 STT 설정
with st.sidebar:
    st.subheader("🖥️ 시스템 상태")
    display_memory_info()
    
    # STT 엔진 상태
    st.subheader("🎤 STT 엔진 상태")
    try:
        stt_engine = get_safe_stt_engine()
        stt_status = stt_engine.get_status()
        
        # STT 제공자 상태 표시
        st.write("**사용 가능한 STT:**")
        st.write(f"🤖 로컬 (Whisper): {'✅' if stt_status['providers']['local'] else '❌'}")
        st.write(f"☁️ Google Cloud: {'✅' if stt_status['providers']['google'] else '❌'}")  
        st.write(f"🌐 OpenAI API: {'✅' if stt_status['providers']['openai'] else '❌'}")
        
        # 비용 정보 표시
        st.subheader("💰 비용 정보")
        costs = stt_status['costs']
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("세션 비용", f"${costs['session']['cost']:.3f}")
            st.metric("세션 사용", f"{costs['session']['minutes']:.1f}분")
        with col2:
            st.metric("월간 비용", f"${costs['monthly']['cost']:.2f}")
            st.metric("Google 무료", f"{costs['monthly']['google_free_remaining']:.0f}분")
        
        # 비용 경고
        if costs['session']['cost'] > 0.5:
            st.warning(f"⚠️ 세션 비용 주의: ${costs['session']['cost']:.2f}")
        
        if costs['monthly']['cost'] > 5.0:
            st.error(f"🚨 월간 비용 주의: ${costs['monthly']['cost']:.2f}")
        
    except Exception as e:
        st.error(f"STT 엔진 상태 확인 실패: {e}")
        st.info("STT 환경 설정을 확인하세요.")
    
    # 비용 초기화 버튼
    if st.button("🔄 세션 비용 초기화"):
        try:
            reset_session_costs()
            st.success("세션 비용이 초기화되었습니다.")
            st.rerun()
        except Exception as e:
            st.error(f"비용 초기화 실패: {e}")
    
    # STT 설정
    st.subheader("⚙️ STT 설정")
    
    # STT 사용 가능성 체크
    try:
        stt_engine = get_safe_stt_engine()
        stt_status = stt_engine.get_status()
        
        # Primary STT 선택
        available_providers = []
        if stt_status['providers']['local']:
            available_providers.append("로컬 (Whisper) - 무료")
        if stt_status['providers']['google']:
            available_providers.append("Google Cloud - $0.006/분")
        if stt_status['providers']['openai']:
            available_providers.append("OpenAI API - $0.006/분")
        
        if available_providers:
            primary_choice = st.selectbox(
                "Primary STT", 
                available_providers,
                index=0,
                help="로컬 STT가 가장 안전하고 무료입니다."
            )
            
            # Fallback STT 선택
            fallback_options = ["없음 (안전)"] + available_providers
            fallback_choice = st.selectbox(
                "Fallback STT",
                fallback_options,
                index=0,
                help="Primary 실패시 사용할 백업 STT"
            )
            
            # 자동 백업 설정
            auto_fallback = st.checkbox(
                "자동 백업 사용", 
                value=False,
                help="⚠️ 유료 STT로 자동 전환될 수 있습니다"
            )
            
            if auto_fallback and "무료" not in fallback_choice:
                st.warning("⚠️ 자동 백업이 유료 서비스로 설정되어 있습니다!")
            
            # STT 모델 크기 (로컬인 경우)
            if "로컬" in primary_choice:
                model_size = st.selectbox(
                    "Whisper 모델 크기",
                    ["tiny", "base", "small"],
                    index=1,
                    help="tiny: 빠름/낮은품질, base: 균형, small: 느림/높은품질"
                )
            else:
                model_size = "base"
            
            # 비용 확인 설정
            cost_confirmation = st.checkbox(
                "비용 확인 필수", 
                value=True,
                help="유료 STT 사용 전 반드시 확인"
            )
            
            # 안전 한도 설정
            st.subheader("🛡️ 안전 한도")
            session_limit = st.slider("세션 한도 ($)", 0.5, 5.0, 2.0, 0.5)
            monthly_limit = st.slider("월간 한도 ($)", 5.0, 50.0, 10.0, 5.0)
            
            # STT 설정 세션에 저장
            st.session_state["stt_config"] = {
                "primary": primary_choice,
                "fallback": fallback_choice,
                "auto_fallback": auto_fallback,
                "model_size": model_size,
                "cost_confirmation": cost_confirmation,
                "session_limit": session_limit,
                "monthly_limit": monthly_limit
            }
        else:
            st.error("사용 가능한 STT가 없습니다!")
            st.info("requirements.txt를 확인하고 필요한 라이브러리를 설치하세요.")
            st.code("pip install faster-whisper yt-dlp")
            
    except Exception as e:
        st.error(f"STT 설정 오류: {e}")
        st.info("STT 환경을 확인하세요.")

# 세션 상태 초기화
def init_session_state():
    """세션 상태 초기화"""
    defaults = {
        "selected_channel": None,
        "selected_channel_title": None,
        "video_list": [],
        "selected_videos": [],
        "video_list_loaded": False,
        "search_results": [],
        "processing_complete": False,
        "stt_config": {
            "primary": "로컬 (Whisper) - 무료",
            "fallback": "없음 (안전)",
            "auto_fallback": False,
            "model_size": "base",
            "cost_confirmation": True,
            "session_limit": 2.0,
            "monthly_limit": 10.0
        }
    }
    
    for key, default_value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value

def get_stt_provider_enum(choice: str) -> STTProvider:
    """UI 선택을 STTProvider enum으로 변환"""
    if "로컬" in choice:
        return STTProvider.LOCAL
    elif "Google" in choice:
        return STTProvider.GOOGLE
    elif "OpenAI" in choice:
        return STTProvider.OPENAI
    else:
        return STTProvider.LOCAL

def create_cost_confirmation_callback():
    """비용 확인 콜백 함수 생성"""
    def confirm_cost(safety_check, provider):
        cost_info = safety_check["cost_estimate"]
        
        if cost_info["cost"] == 0:
            return True
        
        # Streamlit UI로 비용 확인
        st.warning(
            f"⚠️ **비용 발생 확인**\n\n"
            f"**STT 제공자**: {provider.value}\n"
            f"**예상 비용**: ${cost_info['cost']:.3f}\n"
            f"**세션 총 비용**: ${cost_info['estimated_total']:.3f}\n"
            f"**무료 할당량 남음**: {cost_info['free_tier_remaining']:.1f}분"
        )
        
        if cost_info["will_exceed_free"]:
            st.error("🚨 무료 할당량을 초과합니다!")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("💰 비용 발생 동의하고 계속", type="primary"):
                return True
        with col2:
            if st.button("❌ 취소 (로컬 STT 사용)", type="secondary"):
                return False
        
        # 버튼 클릭 전까지 대기
        st.stop()
        return False
    
    return confirm_cost

@memory_monitor_decorator
def process_summaries():
    """선택된 영상들을 안전하게 요약 처리합니다."""
    if not st.session_state["selected_videos"]:
        st.error("선택된 영상이 없습니다.")
        return
    
    # STT 설정 적용
    stt_config = st.session_state.get("stt_config", {})
    primary_provider = get_stt_provider_enum(stt_config.get("primary", "로컬"))
    
    fallback_provider = None
    if stt_config.get("fallback", "없음") != "없음 (안전)":
        fallback_provider = get_stt_provider_enum(stt_config.get("fallback"))
    
    # 안전한 STT 설정
    safety_limits = SafetyLimits(
        session_cost_limit=stt_config.get("session_limit", 2.0),
        monthly_cost_limit=stt_config.get("monthly_limit", 10.0),
        require_confirmation_above=0.1,  # $0.1 이상시 확인
        single_video_limit_minutes=120   # 2시간 제한
    )
    
    safe_config = STTConfig(
        primary_provider=primary_provider,
        fallback_provider=fallback_provider,
        auto_fallback=stt_config.get("auto_fallback", False),
        whisper_model_size=stt_config.get("model_size", "base"),
        enable_chunking=True,
        cost_confirmation_required=stt_config.get("cost_confirmation", True),
        safety_limits=safety_limits
    )
    
    # 기존 엔진 정리 후 새 설정으로 재생성
    cleanup_safe_stt_engine()
    stt_engine = get_safe_stt_engine(safe_config)
    
    # 선택된 영상 정보 가져오기
    selected_video_info = []
    total_duration = 0
    for video_id in st.session_state["selected_videos"]:
        for vid in st.session_state["video_list"]:
            if vid["video_id"] == video_id:
                selected_video_info.append(vid)
                total_duration += vid.get("duration_seconds", 0)
                break
    
    # 전체 비용 예상
    total_minutes = total_duration / 60.0
    if primary_provider != STTProvider.LOCAL:
        overall_cost_check = stt_engine.check_safety_limits(total_minutes, primary_provider)
        
        if not overall_cost_check["safe"]:
            st.error("🚨 전체 처리 안전하지 않음:")
            for block in overall_cost_check["blocks"]:
                st.error(f"- {block}")
            st.info("💡 더 적은 영상을 선택하거나 로컬 STT를 사용하세요.")
            return
        
        if overall_cost_check["cost_estimate"]["cost"] > 0:
            st.warning(
                f"⚠️ **전체 예상 비용**: ${overall_cost_check['cost_estimate']['cost']:.3f}\n\n"
                f"처리할 영상: {len(selected_video_info)}개 ({total_minutes:.1f}분)"
            )
    
    # 진행률 표시
    progress_bar = st.progress(0)
    status_text = st.empty()
    results_container = st.container()
    
    total_videos = len(selected_video_info)
    success_count = 0
    total_cost = 0.0
    
    st.info(f"🎤 STT 설정: {stt_config.get('primary', '로컬')} ({stt_config.get('model_size', 'base')})")
    
    try:
        for i, video_info in enumerate(selected_video_info):
            video_id = video_info["video_id"]
            video_title = video_info["title"]
            duration = video_info.get("duration_seconds", 0)
            
            # 진행률 업데이트
            progress = (i + 1) / total_videos
            progress_bar.progress(progress)
            status_text.text(f"처리 중... ({i + 1}/{total_videos}): {video_title[:50]}...")
            
            # 메모리 체크
            current_memory = memory_manager.get_memory_usage()["rss"]
            if current_memory > 3000:  # 3GB 제한
                results_container.warning(f"⚠️ 메모리 부족으로 처리 중단: {video_title}")
                memory_manager.force_cleanup(aggressive=True)
                break
            
            try:
                # 1. 안전한 자막/STT 수집
                with st.spinner(f"자막/STT 수집 중: {video_title[:30]}..."):
                    video_url = f"https://www.youtube.com/watch?v={video_id}"
                    
                    # 비용 확인 콜백 생성
                    if safe_config.cost_confirmation_required:
                        confirmation_callback = create_cost_confirmation_callback()
                    else:
                        confirmation_callback = None
                    
                    # STT 처리
                    stt_result = stt_engine.transcribe_video(video_url, confirmation_callback)
                
                if not stt_result.success:
                    results_container.error(f"❌ STT 실패: {video_title} - {stt_result.error_message}")
                    continue
                
                transcript = stt_result.text
                if len(transcript.strip()) < 100:
                    results_container.warning(f"⚠️ 텍스트가 너무 짧음: {video_title}")
                    continue
                
                # 비용 추적
                if stt_result.cost_incurred > 0:
                    total_cost += stt_result.cost_incurred
                    results_container.info(
                        f"💰 STT 비용 발생: ${stt_result.cost_incurred:.3f} "
                        f"({stt_result.provider.value}, {stt_result.processing_minutes:.1f}분)"
                    )
                
                # 2. AI 요약 (Gemini)
                with st.spinner(f"AI 요약 중: {video_title[:30]}..."):
                    try:
                        summary_data = summarize_transcript(
                            transcript, 
                            video_title, 
                            st.session_state["selected_channel_title"]
                        )
                    except Exception as gemini_error:
                        error_msg = str(gemini_error)
                        if "429" in error_msg or "quota" in error_msg.lower():
                            results_container.error(f"❌ Gemini API 할당량 초과")
                            st.error("⚠️ Gemini API 할당량 초과. 1분 후 다시 시도하거나 내일 사용해주세요.")
                            break
                        else:
                            results_container.error(f"❌ 요약 오류: {error_msg}")
                            continue
                
                if not summary_data:
                    results_container.error(f"❌ 요약 실패: {video_title}")
                    continue
                
                # 3. Notion 저장
                with st.spinner(f"저장 중: {video_title[:30]}..."):
                    save_success = save_summary_to_notion(summary_data, video_id)
                
                if save_success:
                    results_container.success(f"✅ 완료: {video_title}")
                    success_count += 1
                else:
                    results_container.error(f"❌ 저장 실패: {video_title}")
            
            except Exception as e:
                results_container.error(f"❌ 오류 발생: {video_title} - {str(e)}")
            
            finally:
                # 메모리 정리
                for var_name in ['transcript', 'summary_data', 'stt_result']:
                    if var_name in locals():
                        del locals()[var_name]
                
                memory_manager.force_cleanup(aggressive=True)
                
                current_mem = memory_manager.get_memory_usage()["rss"]
                print(f"🧹 {i+1}번째 영상 처리 후 메모리: {current_mem:.1f}MB")
            
            # API 호출 간격
            if i < total_videos - 1:
                time.sleep(3)
    
    finally:
        # 완료 메시지
        progress_bar.progress(1.0)
        status_text.text("처리 완료!")
        
        if success_count > 0:
            st.balloons()
            message = f"🎉 총 {success_count}개 영상 요약 완료!"
            if total_cost > 0:
                message += f" (총 비용: ${total_cost:.3f})"
            st.success(message)
            st.session_state["processing_complete"] = True
        else:
            st.error("요약에 실패했습니다. 설정을 확인해주세요.")
        
        # 최종 정리
        memory_manager.force_cleanup(aggressive=True)
        memory_manager.cleanup_session_state(max_items=10)

# 메인 실행 함수
def main():
    """메인 실행 함수"""
    init_session_state()
    memory_manager.cleanup_session_state(max_items=20)
    
    st.sidebar.title("🎯 메뉴")
    menu = st.sidebar.selectbox(
        "원하는 기능을 선택하세요:",
        ["영상 요약하기", "요약 검색하기", "대시보드", "STT 테스트", "비용 관리", "설정"]
    )
    
    if menu == "영상 요약하기":
        show_summary_page()
    elif menu == "요약 검색하기":
        show_search_page()
    elif menu == "대시보드":
        show_dashboard_page()
    elif menu == "STT 테스트":
        show_stt_test_page()
    elif menu == "비용 관리":
        show_cost_management_page()
    elif menu == "설정":
        show_settings_page()

def show_summary_page():
    """영상 요약하기 페이지 (기존 로직 + 비용 안내)"""
    st.header("🎬 영상 요약하기")
    
    # 비용 안내
    stt_config = st.session_state.get("stt_config", {})
    if "무료" not in stt_config.get("primary", ""):
        st.warning(
            f"⚠️ 현재 Primary STT: {stt_config.get('primary', '')}\n"
            f"비용이 발생할 수 있습니다. 무료 사용을 원하시면 '로컬 (Whisper)'를 선택하세요."
        )
    
    # 기존 채널 선택 로직
    if st.session_state["selected_channel"] is None:
        st.subheader("1️⃣ 유튜버 채널 선택")
        
        with st.form("channel_search_form"):
            query = st.text_input("유튜버 이름을 입력하세요:", placeholder="예: 신사임당, 부읽남")
            search_submitted = st.form_submit_button("🔍 채널 검색")

        if search_submitted and query:
            with st.spinner("검색 중..."):
                try:
                    channels = search_channel(query)
                    st.session_state["search_results"] = channels
                    gc.collect()
                except Exception as e:
                    st.error(f"검색 중 오류 발생: {e}")
                    st.session_state["search_results"] = []
        
        # 검색 결과 표시
        if st.session_state.get("search_results"):
            channels = st.session_state["search_results"]
            if channels:
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
                                st.session_state["search_results"] = []
                                gc.collect()
                                st.rerun()
    else:
        # 채널 선택 후 로직
        col1, col2 = st.columns([3, 1])
        with col1:
            st.success(f"✅ 선택된 채널: **{st.session_state['selected_channel_title']}**")
        with col2:
            if st.button("🔄 채널 변경"):
                for key in ["selected_channel", "selected_channel_title", "video_list_loaded", 
                           "video_list", "selected_videos", "search_results", "processing_complete"]:
                    st.session_state[key] = None if "selected" in key else False if "loaded" in key or "complete" in key else []
                memory_manager.force_cleanup(aggressive=True)
                st.rerun()

        st.markdown("---")
        st.subheader("2️⃣ 영상 목록 필터링")
        
        col1, col2 = st.columns(2)
        with col1:
            date_option = st.selectbox("📅 기간 선택", ["전체", "최근 7일", "최근 30일"])
        with col2:
            max_results = st.selectbox("📊 최대 영상 수", [3, 5, 10], index=1)
            st.info("💡 비용 절약을 위해 적은 수를 권장합니다.")

        # 날짜 설정
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
                    
                    del videos
                    gc.collect()
                    
                    st.success(f"✅ {len(st.session_state['video_list'])}개 영상을 불러왔습니다!")
                except Exception as e:
                    st.error(f"영상 목록 불러오기 실패: {e}")

        # 영상 선택
        if st.session_state["video_list_loaded"]:
            st.markdown("---")
            st.subheader("3️⃣ 요약할 영상 선택")
            
            if not st.session_state["video_list"]:
                st.warning("해당 기간에 업로드된 영상이 없습니다.")
            else:
                # 전체 선택/해제
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

                # 비용 예상 표시
                if st.session_state["selected_videos"] and "무료" not in stt_config.get("primary", ""):
                    selected_duration = sum([
                        vid.get('duration_seconds', 0) for vid in st.session_state['video_list'] 
                        if vid['video_id'] in st.session_state['selected_videos']
                    ])
                    estimated_minutes = selected_duration / 60.0
                    estimated_cost = estimated_minutes * 0.006  # $0.006/분
                    
                    if estimated_cost > 0:
                        st.warning(
                            f"💰 **예상 STT 비용**: ${estimated_cost:.3f} "
                            f"({estimated_minutes:.1f}분)\n\n"
                            f"💡 비용 절약: 사이드바에서 Primary STT를 '로컬 (Whisper)'로 변경"
                        )

                # 영상 목록 표시
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
                            duration_info = vid.get('duration_formatted', 'N/A')
                            duration_seconds = vid.get('duration_seconds', 0)
                            
                            # 비용 정보 표시
                            if "무료" not in stt_config.get("primary", "") and duration_seconds > 0:
                                cost_estimate = (duration_seconds / 60.0) * 0.006
                                cost_info = f"💰 예상 비용: ${cost_estimate:.3f}"
                                st.caption(f"🕒 {vid['published_at'][:10]} | ⏱️ {duration_info} | {cost_info}")
                            else:
                                st.caption(f"🕒 {vid['published_at'][:10]} | ⏱️ {duration_info}")
                            
                            current_selected = vid["video_id"] in st.session_state["selected_videos"]
                            is_selected = st.checkbox(
                                "선택", 
                                value=current_selected,
                                key=f"video_{vid['video_id']}"
                            )
                            
                            if is_selected != current_selected:
                                if is_selected:
                                    if vid["video_id"] not in st.session_state["selected_videos"]:
                                        st.session_state["selected_videos"].append(vid["video_id"])
                                else:
                                    if vid["video_id"] in st.session_state["selected_videos"]:
                                        st.session_state["selected_videos"].remove(vid["video_id"])
                    
                    if i < len(st.session_state["video_list"]) - 1:
                        st.divider()

                # 요약 실행
                if st.session_state["selected_videos"]:
                    st.markdown("---")
                    st.subheader("4️⃣ 요약 실행")
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.success(f"✅ {len(st.session_state['selected_videos'])}개 영상 선택됨")
                    with col2:
                        if st.session_state.get("processing_complete"):
                            st.success("🎉 처리 완료!")
                    
                    # STT 설정 표시
                    st.info(
                        f"🎤 STT 설정: {stt_config.get('primary', '로컬')} | "
                        f"모델: {stt_config.get('model_size', 'base')} | "
                        f"백업: {stt_config.get('fallback', '없음')}"
                    )
                    
                    # 안전성 체크
                    current_memory = memory_manager.get_memory_usage()["rss"]
                    selected_count = len(st.session_state['selected_videos'])
                    
                    if current_memory > 1500:  # 1.5GB 제한
                        st.warning(f"⚠️ 현재 메모리: {current_memory:.0f}MB. 메모리 정리를 권장합니다.")
                        if st.button("🗑️ 메모리 정리 후 계속"):
                            memory_manager.force_cleanup(aggressive=True)
                            cleanup_safe_stt_engine()
                            st.rerun()
                    
                    if selected_count > 3:
                        st.warning(f"⚠️ {selected_count}개 영상 선택됨. 안정성을 위해 3개 이하를 권장합니다.")
                    
                    st.info("💡 API 제한: Gemini 분당 250K 토큰, 할당량 초과시 처리가 중단됩니다.")
                    
                    if st.button("🧠 선택한 영상 요약 시작", type="primary"):
                        st.session_state["processing_complete"] = False
                        process_summaries()

def show_search_page():
    """검색 페이지"""
    st.header("🔍 요약 검색하기")
    
    col1, col2 = st.columns([2, 1])
    with col1:
        search_keyword = st.text_input("🔍 키워드 검색:", placeholder="예: 삼성전자, 부동산, AI")
    with col2:
        if st.button("검색", type="primary"):
            if search_keyword:
                with st.spinner("검색 중..."):
                    try:
                        results = search_summaries_by_keyword(search_keyword)
                        st.session_state["search_results_data"] = results
                    except Exception as e:
                        st.error(f"검색 실패: {e}")
                        st.session_state["search_results_data"] = []
    
    # 검색 결과 표시
    if "search_results_data" in st.session_state and st.session_state["search_results_data"]:
        results = st.session_state["search_results_data"]
        st.subheader(f"🎯 검색 결과: {len(results)}개 발견")
        
        for i, result in enumerate(results):
            with st.expander(f"📺 {result['title']}", expanded=(i < 3)):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**채널:** {result['channel']}")
                    st.markdown(f"**키워드:** {', '.join(result['keywords'])}")
                    st.markdown(f"**감성:** {result['sentiment']}")
                    st.markdown(f"**작성일:** {result['created_time'][:10]}")
                with col2:
                    if st.button("🔗 Notion에서 보기", key=f"notion_{i}"):
                        st.markdown(f"[Notion 페이지 열기]({result['notion_url']})")

def show_dashboard_page():
    """대시보드 페이지"""
    st.header("📊 요약 대시보드")
    
    try:
        # 통계 데이터 가져오기
        stats = get_database_stats()
        
        # 메트릭 표시
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("📝 총 요약 수", stats["total_summaries"])
        with col2:
            positive_count = stats["sentiment_distribution"].get("긍정적", 0)
            st.metric("😊 긍정적", positive_count)
        with col3:
            neutral_count = stats["sentiment_distribution"].get("중립적", 0)
            st.metric("😐 중립적", neutral_count)
        with col4:
            negative_count = stats["sentiment_distribution"].get("부정적", 0)
            st.metric("😞 부정적", negative_count)
        
        # 감성 분포 차트
        st.subheader("📈 감성 분포")
        sentiment_data = stats["sentiment_distribution"]
        if sentiment_data:
            import matplotlib.pyplot as plt
            
            labels = list(sentiment_data.keys())
            values = list(sentiment_data.values())
            
            fig, ax = plt.subplots()
            ax.pie(values, labels=labels, autopct='%1.1f%%')
            ax.set_title("감성 분포")
            st.pyplot(fig)
        
        # 상위 채널 표시
        st.subheader("🏆 상위 채널")
        top_channels = stats["top_channels"]
        if top_channels:
            for i, (channel, count) in enumerate(top_channels[:5]):
                st.write(f"{i+1}. **{channel}**: {count}개 요약")
        
        # 최근 요약 목록
        st.subheader("🕒 최근 요약 (7일)")
        recent_summaries = get_recent_summaries(7)
        
        if recent_summaries:
            for summary in recent_summaries[:10]:
                with st.expander(f"📺 {summary['title']}", expanded=False):
                    st.write(f"**채널:** {summary['channel']}")
                    st.write(f"**키워드:** {', '.join(summary['keywords'])}")
                    st.write(f"**감성:** {summary['sentiment']}")
                    st.write(f"**날짜:** {summary['created_time'][:10]}")
        else:
            st.info("최근 7일간 요약된 데이터가 없습니다.")
            
    except Exception as e:
        st.error(f"대시보드 데이터 로드 실패: {e}")
        st.info("Notion 연결을 확인하세요.")

def show_cost_management_page():
    """비용 관리 페이지"""
    st.header("💰 비용 관리")
    
    try:
        stt_engine = get_safe_stt_engine()
        cost_summary = stt_engine.get_cost_summary()
        
        # 비용 현황
        st.subheader("📊 비용 현황")
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("세션 비용", f"${cost_summary['session']['cost']:.3f}")
        with col2:
            st.metric("세션 사용량", f"{cost_summary['session']['minutes']:.1f}분")
        with col3:
            st.metric("월간 비용", f"${cost_summary['monthly']['cost']:.2f}")
        with col4:
            st.metric("월간 사용량", f"{cost_summary['monthly']['minutes']:.1f}분")
        
        # Google Cloud 무료 할당량
        st.subheader("🆓 Google Cloud 무료 할당량")
        free_remaining = cost_summary['monthly']['google_free_remaining']
        free_used = 60 - free_remaining
        
        progress_value = free_used / 60 if free_used >= 0 else 0
        st.progress(progress_value)
        st.write(f"사용: {free_used:.1f}분 / 60분 (남은 무료: {free_remaining:.1f}분)")
        
        if free_remaining < 10:
            st.warning("⚠️ 무료 할당량이 부족합니다. 로컬 STT 사용을 권장합니다.")
        
        # 안전 한도 현황
        st.subheader("🛡️ 안전 한도 현황")
        limits = cost_summary['limits']
        
        col1, col2 = st.columns(2)
        with col1:
            session_usage = cost_summary['session']['cost'] / limits['session_limit'] * 100
            st.metric("세션 한도 사용률", f"{session_usage:.1f}%")
            if session_usage > 80:
                st.error("🚨 세션 한도 임박!")
        
        with col2:
            monthly_usage = cost_summary['monthly']['cost'] / limits['monthly_limit'] * 100
            st.metric("월간 한도 사용률", f"{monthly_usage:.1f}%")
            if monthly_usage > 80:
                st.error("🚨 월간 한도 임박!")
        
        # 비용 절약 팁
        st.subheader("💡 비용 절약 팁")
        with st.expander("📋 무료로 사용하는 방법"):
            st.markdown("""
            **완전 무료 사용법:**
            1. Primary STT: "로컬 (Whisper)" 선택
            2. Fallback STT: "없음 (안전)" 선택
            3. 자동 백업: 비활성화
            4. 비용 확인: 활성화 (안전장치)
            
            **하이브리드 사용법 (Google 무료 할당량 활용):**
            1. Primary: "로컬 (Whisper)"
            2. Fallback: "Google Cloud" (60분/월 무료)
            3. 자동 백업: 활성화
            4. 월 60분까지는 무료로 백업 STT 사용
            
            **주의사항:**
            - 긴 영상(30분+)은 로컬 STT만 사용 권장
            - 클라우드 STT는 자막 없는 영상에만 사용
            - 정기적으로 무료 할당량 확인
            """)
        
        # 비용 초기화
        st.subheader("🔄 비용 초기화")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 세션 비용 초기화"):
                reset_session_costs()
                st.success("세션 비용이 초기화되었습니다.")
                st.rerun()
        
        with col2:
            if st.button("⚠️ 월간 비용 초기화", help="새 달이 시작되었을 때만 사용"):
                if st.checkbox("월간 초기화 확인 (신중히!)"):
                    stt_engine.cost_tracker.reset_monthly()
                    stt_engine._save_cost_tracker()
                    st.success("월간 비용이 초기화되었습니다.")
                    st.rerun()
                    
    except Exception as e:
        st.error(f"비용 관리 데이터 로드 실패: {e}")

def show_stt_test_page():
    """STT 테스트 페이지"""
    st.header("🧪 STT 시스템 테스트")
    
    st.info("새로운 STT 시스템의 성능을 안전하게 테스트합니다.")
    
    # 테스트 영상 URL 입력
    test_url = st.text_input(
        "테스트할 YouTube 영상 URL:",
        placeholder="https://www.youtube.com/watch?v=...",
        help="짧은 영상(5분 이하)으로 테스트하는 것을 권장합니다."
    )
    
    if test_url and st.button("🎤 안전한 STT 테스트 실행"):
        if "youtube.com/watch" not in test_url and "youtu.be/" not in test_url:
            st.error("올바른 YouTube URL을 입력하세요.")
            return
        
        # 안전한 테스트 설정 (로컬 우선)
        test_config = STTConfig(
            primary_provider=STTProvider.LOCAL,
            fallback_provider=None,  # 테스트에서는 백업 비활성화
            whisper_model_size="tiny",  # 테스트용 빠른 모델
            enable_chunking=False,  # 테스트에서는 비활성화
            auto_fallback=False,
            cost_confirmation_required=True
        )
        
        # 테스트 실행
        with st.spinner("안전한 STT 테스트 실행 중..."):
            start_time = time.time()
            
            try:
                stt_engine = get_safe_stt_engine(test_config)
                result = stt_engine.transcribe_video(test_url)
                
                end_time = time.time()
                processing_time = end_time - start_time
                
                # 결과 표시
                if result.success:
                    st.success(f"✅ STT 성공! ({result.provider.value})")
                    
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("처리 시간", f"{processing_time:.1f}초")
                    with col2:
                        st.metric("텍스트 길이", f"{len(result.text)}자")
                    with col3:
                        if result.confidence:
                            st.metric("신뢰도", f"{result.confidence:.2f}")
                    with col4:
                        st.metric("비용", f"${result.cost_incurred:.3f}")
                    
                    # 결과 텍스트 표시
                    st.subheader("📝 STT 결과:")
                    st.text_area("변환된 텍스트", result.text, height=300)
                    
                    # 청크 정보
                    if result.chunks_processed > 1:
                        st.info(f"📊 {result.chunks_processed}개 청크로 분할 처리됨")
                else:
                    st.error(f"❌ STT 실패: {result.error_message}")
                    st.info("다른 STT 제공자를 시도해보거나 영상 길이를 확인하세요.")
                    
            except Exception as e:
                st.error(f"테스트 실행 중 오류: {e}")

def show_settings_page():
    """설정 페이지"""
    st.header("⚙️ 설정")
    
    # 비용 안전장치 상태
    st.subheader("🛡️ 비용 안전장치 상태")
    try:
        stt_engine = get_safe_stt_engine()
        status = stt_engine.get_status()
        
        col1, col2 = st.columns(2)
        with col1:
            st.write("**안전 설정:**")
            st.write(f"✅ 비용 확인 필수: {status['config']['cost_confirmation']}")
            st.write(f"✅ 자동 백업: {status['config']['auto_fallback']}")
            st.write(f"✅ Primary STT: {status['config']['primary']}")
        
        with col2:
            st.write("**안전 한도:**")
            limits = status['costs']['limits']
            st.write(f"세션 한도: ${limits['session_limit']}")
            st.write(f"월간 한도: ${limits['monthly_limit']}")
            
    except Exception as e:
        st.error(f"안전장치 상태 확인 실패: {e}")
    
    # API 키 설정
    st.subheader("🔑 API 키 설정")
    st.info("환경변수 파일(.env)에서 API 키를 설정해주세요.")
    
    import os
    from dotenv import load_dotenv
    load_dotenv()
    
    api_status = {
        "YouTube API": "✅" if os.getenv("YOUTUBE_API_KEY") else "❌",
        "Gemini API": "✅" if os.getenv("GEMINI_API_KEY") else "❌",
        "Notion Token": "✅" if os.getenv("NOTION_TOKEN") else "❌",
        "Notion Database ID": "✅" if os.getenv("NOTION_DATABASE_ID") else "❌",
        "Google Cloud STT": "✅" if os.getenv("GOOGLE_APPLICATION_CREDENTIALS") else "❌ (선택사항)",
        "OpenAI API": "✅" if os.getenv("OPENAI_API_KEY") else "❌ (선택사항)"
    }
    
    st.subheader("📋 API 키 상태")
    for api_name, status in api_status.items():
        st.write(f"{status} {api_name}")
    
    # 시스템 관리
    st.subheader("🖥️ 시스템 관리")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("🗑️ 전체 메모리 정리"):
            memory_manager.force_cleanup(aggressive=True)
            memory_manager.cleanup_session_state(max_items=10)
            cleanup_safe_stt_engine()
            
            large_keys = ["video_list", "search_results", "search_results_data"]
            for key in large_keys:
                if key in st.session_state:
                    st.session_state[key] = []
            gc.collect()
            st.success("메모리 정리 완료!")
            st.rerun()
    
    with col2:
        if st.button("🎤 STT 엔진 초기화"):
            cleanup_safe_stt_engine()
            st.success("STT 엔진 초기화 완료!")
            st.rerun()
    
    with col3:
        if st.button("🧪 환경 진단"):
            st.info("환경 진단을 실행합니다...")
            
            # 간단한 환경 진단
            diagnostic_results = []
            
            # Python 라이브러리 체크
            try:
                import faster_whisper
                diagnostic_results.append("✅ faster-whisper 설치됨")
            except ImportError:
                diagnostic_results.append("❌ faster-whisper 설치 필요")
            
            try:
                import yt_dlp
                diagnostic_results.append("✅ yt-dlp 설치됨")
            except ImportError:
                diagnostic_results.append("❌ yt-dlp 설치 필요")
            
            try:
                import torch
                diagnostic_results.append("✅ PyTorch 설치됨")
            except ImportError:
                diagnostic_results.append("❌ PyTorch 설치 필요")
            
            for result in diagnostic_results:
                st.write(result)
    
    # 비용 안전 가이드
    st.subheader("💡 비용 안전 사용 가이드")
    with st.expander("🆓 완전 무료 사용법"):
        st.markdown("""
        **100% 무료로 사용하는 방법:**
        
        1. **STT 설정:**
           - Primary STT: "로컬 (Whisper) - 무료"
           - Fallback STT: "없음 (안전)"
           - 자동 백업: 비활성화
        
        2. **영상 선택:**
           - 한 번에 1-3개 영상만 처리
           - 30분 이하 영상 권장
           - 자막 있는 영상 우선 선택
        
        3. **시스템 관리:**
           - 정기적 메모리 정리
           - 처리 후 STT 엔진 초기화
        """)
    
    with st.expander("⚠️ 비용 발생 시나리오"):
        st.markdown("""
        **주의: 다음 경우 비용이 발생합니다**
        
        1. **설정 실수:**
           - Primary STT를 Google/OpenAI로 설정
           - 자동 백업을 유료 서비스로 설정
        
        2. **대량 처리:**
           - 한 번에 많은 영상 처리
           - 긴 영상(1시간+) 처리
        
        3. **백업 사용:**
           - 로컬 STT 실패시 클라우드 STT 사용
           - Google 무료 할당량(60분/월) 초과
        
        **예방법:** 항상 비용 확인 필수 활성화
        """)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        st.error(f"애플리케이션 실행 중 오류: {e}")
        st.info("페이지를 새로고침하거나 설정을 확인하세요.")