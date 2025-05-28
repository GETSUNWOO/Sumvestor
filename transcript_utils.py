# transcript_utils.py - 안전한 STT 엔진 연동 버전
import yt_dlp
import os
import requests
import re
import gc
from typing import Optional

# 안전한 STT 엔진 import
from safe_stt_engine import get_safe_stt_engine, STTConfig, STTProvider
from memory_manager import memory_manager, memory_monitor_decorator

@memory_monitor_decorator
def get_transcript(video_id: str, use_safe_stt: bool = True) -> Optional[str]:
    """
    YouTube 영상의 자막을 안전하게 가져옵니다.
    
    Args:
        video_id: YouTube 영상 ID
        use_safe_stt: 안전한 STT 엔진 사용 여부 (기본값: True)
    
    Processing Order:
    1순위: YouTube 자동생성/수동 자막 (한국어/영어) - 무료, 빠름
    2순위: 안전한 STT 엔진 (비용 통제 포함) - 설정에 따라 무료/유료
    """
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    
    # 1. YouTube 자막 추출 시도 (항상 먼저 시도)
    print(f"📝 YouTube 자막 수집 시도: {video_id}")
    transcript = extract_subtitles_with_ytdlp(video_url)
    
    if transcript and len(transcript.strip()) > 50:
        print(f"✅ YouTube 자막 수집 성공: {len(transcript)}자")
        return clean_transcript(transcript)
    
    # 2. 안전한 STT 엔진 사용 (자막이 없거나 너무 짧은 경우)
    if use_safe_stt:
        print(f"🎤 안전한 STT 엔진 사용: {video_id}")
        
        # 현재 설정된 STT 엔진 사용 (main.py에서 설정됨)
        stt_engine = get_safe_stt_engine()
        
        # STT 처리 (비용 안전장치 포함)
        try:
            stt_result = stt_engine.transcribe_video(video_url)
            
            if stt_result.success and len(stt_result.text.strip()) > 50:
                print(f"✅ 안전한 STT 성공 ({stt_result.provider.value}): {len(stt_result.text)}자")
                
                # 비용 발생 시 로그
                if stt_result.cost_incurred > 0:
                    print(f"💰 STT 비용 발생: ${stt_result.cost_incurred:.3f} ({stt_result.processing_minutes:.1f}분)")
                
                return clean_transcript(stt_result.text)
            else:
                print(f"❌ 안전한 STT 실패: {stt_result.error_message}")
                return None
                
        except Exception as e:
            print(f"❌ 안전한 STT 처리 중 오류: {e}")
            return None
    else:
        print(f"⚠️ STT 사용 비활성화: {video_id}")
        return None

def get_transcript_with_custom_stt(video_id: str, stt_config: STTConfig) -> Optional[str]:
    """
    사용자 정의 STT 설정으로 자막을 가져옵니다.
    
    Args:
        video_id: YouTube 영상 ID
        stt_config: 사용자 정의 STT 설정
    """
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    
    # 1. YouTube 자막 시도
    transcript = extract_subtitles_with_ytdlp(video_url)
    if transcript and len(transcript.strip()) > 50:
        return clean_transcript(transcript)
    
    # 2. 사용자 정의 STT 설정으로 처리
    from safe_stt_engine import SafeSTTEngine
    
    custom_stt_engine = SafeSTTEngine(stt_config)
    try:
        stt_result = custom_stt_engine.transcribe_video(video_url)
        
        if stt_result.success:
            return clean_transcript(stt_result.text)
        else:
            return None
    finally:
        custom_stt_engine.cleanup()

def get_transcript_local_only(video_id: str, model_size: str = "base") -> Optional[str]:
    """
    로컬 STT만 사용하여 자막을 가져옵니다 (완전 무료).
    
    Args:
        video_id: YouTube 영상 ID
        model_size: Whisper 모델 크기 (tiny, base, small)
    """
    local_config = STTConfig(
        primary_provider=STTProvider.LOCAL,
        fallback_provider=None,
        whisper_model_size=model_size,
        enable_chunking=True,
        auto_fallback=False,
        cost_confirmation_required=False  # 로컬은 무료이므로 확인 불필요
    )
    
    return get_transcript_with_custom_stt(video_id, local_config)

def extract_subtitles_with_ytdlp(video_url: str) -> Optional[str]:
    """
    yt-dlp를 사용하여 YouTube 자막을 추출합니다.
    기존 로직 유지하되 에러 처리 강화
    """
    try:
        ydl_opts = {
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitleslangs': ['ko', 'en'],  # 한국어, 영어 우선
            'skip_download': True,
            'subtitlesformat': 'srt',
            'quiet': True,
            'no_warnings': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            
            # 자동 생성 자막 확인 (우선순위: 한국어 → 영어)
            if 'automatic_captions' in info and info['automatic_captions']:
                auto_captions = info['automatic_captions']
                
                # 한국어 자막 시도
                if 'ko' in auto_captions:
                    for caption in auto_captions['ko']:
                        if 'url' in caption:
                            subtitle_text = download_subtitle_content(caption['url'])
                            if subtitle_text and len(subtitle_text) > 50:
                                return subtitle_text
                
                # 영어 자막 시도
                if 'en' in auto_captions:
                    for caption in auto_captions['en']:
                        if 'url' in caption:
                            subtitle_text = download_subtitle_content(caption['url'])
                            if subtitle_text and len(subtitle_text) > 50:
                                return subtitle_text
            
            # 수동 업로드 자막 확인
            if 'subtitles' in info and info['subtitles']:
                subtitles = info['subtitles']
                
                # 한국어 수동 자막
                if 'ko' in subtitles:
                    for subtitle in subtitles['ko']:
                        if 'url' in subtitle:
                            subtitle_text = download_subtitle_content(subtitle['url'])
                            if subtitle_text and len(subtitle_text) > 50:
                                return subtitle_text
                
                # 영어 수동 자막
                if 'en' in subtitles:
                    for subtitle in subtitles['en']:
                        if 'url' in subtitle:
                            subtitle_text = download_subtitle_content(subtitle['url'])
                            if subtitle_text and len(subtitle_text) > 50:
                                return subtitle_text
        
        return None
        
    except Exception as e:
        print(f"❌ YouTube 자막 추출 실패: {e}")
        return None

def download_subtitle_content(subtitle_url: str) -> str:
    """
    자막 URL에서 실제 텍스트를 다운로드합니다.
    기존 로직 유지하되 타임아웃 및 에러 처리 강화
    """
    try:
        response = requests.get(subtitle_url, timeout=30)
        response.raise_for_status()
        
        subtitle_text = response.text
        
        # SRT 포맷에서 텍스트만 추출
        lines = subtitle_text.split('\n')
        clean_lines = []
        
        for line in lines:
            line = line.strip()
            # 숫자만 있는 라인 건너뛰기
            if line.isdigit():
                continue
            # 타임코드 라인 건너뛰기 (00:00:00,000 --> 00:00:05,000 형식)
            if '-->' in line:
                continue
            # 빈 라인 건너뛰기
            if not line:
                continue
            # HTML 태그 제거 (예: <c>텍스트</c>)
            line = re.sub(r'<[^>]+>', '', line)
            
            if line:
                clean_lines.append(line)
        
        result = ' '.join(clean_lines)
        return result if len(result) > 10 else ""
        
    except Exception as e:
        print(f"❌ 자막 다운로드 실패: {e}")
        return ""

def clean_transcript(text: str) -> str:
    """
    자막 텍스트를 정리합니다.
    메모리 효율성 및 처리 속도 최적화
    """
    if not text:
        return ""
    
    # 큰 텍스트는 청크 단위로 처리 (메모리 절약)
    if len(text) > 100000:  # 100KB 이상
        return clean_large_transcript(text)
    
    # 기본 정리 과정
    # HTML 태그 제거
    text = re.sub(r'<[^>]+>', '', text)
    
    # 중복 공백 제거
    text = re.sub(r'\s+', ' ', text)
    
    # 특수 문자 정리 (음악 기호, 이모지 등)
    text = re.sub(r'[♪♫🎵🎶]', '', text)
    text = re.sub(r'[\U0001F600-\U0001F64F]', '', text)  # 이모티콘
    text = re.sub(r'[\U0001F300-\U0001F5FF]', '', text)  # 기타 심볼
    
    # 반복되는 문구 제거 (STT 오류 보정)
    text = remove_repetitive_phrases(text)
    
    # 앞뒤 공백 제거
    text = text.strip()
    
    return text

def clean_large_transcript(text: str, chunk_size: int = 20000) -> str:
    """
    대용량 자막 텍스트를 청크 단위로 정리 (메모리 절약)
    """
    cleaned_chunks = []
    
    for i in range(0, len(text), chunk_size):
        chunk = text[i:i + chunk_size]
        
        # 청크별로 정리
        chunk = re.sub(r'<[^>]+>', '', chunk)
        chunk = re.sub(r'\s+', ' ', chunk)
        chunk = re.sub(r'[♪♫🎵🎶]', '', chunk)
        chunk = re.sub(r'[\U0001F600-\U0001F64F]', '', chunk)
        chunk = re.sub(r'[\U0001F300-\U0001F5FF]', '', chunk)
        
        cleaned_chunks.append(chunk.strip())
        
        # 중간중간 메모리 정리
        if i % (chunk_size * 5) == 0:
            gc.collect()
    
    result = ' '.join(cleaned_chunks)
    
    # 반복 문구 제거 (전체 텍스트 대상)
    result = remove_repetitive_phrases(result)
    
    # 최종 메모리 정리
    del cleaned_chunks
    gc.collect()
    
    return result

def remove_repetitive_phrases(text: str) -> str:
    """
    STT에서 자주 발생하는 반복 문구를 제거합니다.
    """
    if len(text) < 100:
        return text
    
    # 짧은 반복 구문 제거 (3-10글자)
    pattern = r'(.{3,10})\1{2,}'  # 같은 구문이 3번 이상 반복
    text = re.sub(pattern, r'\1', text)
    
    # 단어 단위 반복 제거
    words = text.split()
    if len(words) > 10:
        # 연속된 같은 단어 제거
        cleaned_words = []
        prev_word = ""
        repeat_count = 0
        
        for word in words:
            if word == prev_word:
                repeat_count += 1
                if repeat_count < 2:  # 최대 2번까지만 허용
                    cleaned_words.append(word)
            else:
                cleaned_words.append(word)
                prev_word = word
                repeat_count = 0
        
        text = ' '.join(cleaned_words)
    
    return text

def get_transcript_with_fallback_strategy(video_id: str) -> tuple[Optional[str], str]:
    """
    다양한 전략으로 자막을 수집하고 어떤 방법이 성공했는지 반환합니다.
    
    Returns:
        tuple: (transcript_text, method_used)
        method_used: "youtube_subtitle", "local_stt", "cloud_stt", "failed"
    """
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    
    # 1. YouTube 자막 시도
    transcript = extract_subtitles_with_ytdlp(video_url)
    if transcript and len(transcript.strip()) > 50:
        return clean_transcript(transcript), "youtube_subtitle"
    
    # 2. 로컬 STT 시도 (무료)
    try:
        local_transcript = get_transcript_local_only(video_id, "base")
        if local_transcript and len(local_transcript.strip()) > 50:
            return local_transcript, "local_stt"
    except Exception as e:
        print(f"로컬 STT 실패: {e}")
    
    # 3. 클라우드 STT 시도 (유료) - 사용자 확인 필요
    try:
        # Google Cloud 백업 설정 (무료 할당량 우선 사용)
        cloud_config = STTConfig(
            primary_provider=STTProvider.GOOGLE,
            fallback_provider=STTProvider.OPENAI,
            auto_fallback=True,
            cost_confirmation_required=True
        )
        
        cloud_transcript = get_transcript_with_custom_stt(video_id, cloud_config)
        if cloud_transcript and len(cloud_transcript.strip()) > 50:
            return cloud_transcript, "cloud_stt"
    except Exception as e:
        print(f"클라우드 STT 실패: {e}")
    
    return None, "failed"

def estimate_stt_cost(video_duration_minutes: float, provider: str = "google") -> dict:
    """
    STT 비용을 예상합니다.
    
    Args:
        video_duration_minutes: 영상 길이 (분)
        provider: STT 제공자 ("google", "openai", "local")
    
    Returns:
        dict: 비용 정보
    """
    if provider == "local":
        return {
            "cost": 0.0,
            "provider": "로컬 Whisper",
            "free": True,
            "note": "완전 무료, CPU 사용량 증가"
        }
    
    cost_per_minute = 0.006  # Google Cloud & OpenAI 동일
    
    if provider == "google":
        # Google Cloud 무료 할당량 고려
        stt_engine = get_safe_stt_engine()
        cost_summary = stt_engine.get_cost_summary()
        free_remaining = cost_summary['monthly']['google_free_remaining']
        
        billable_minutes = max(0, video_duration_minutes - free_remaining)
        cost = billable_minutes * cost_per_minute
        
        return {
            "cost": cost,
            "provider": "Google Cloud",
            "free": cost == 0,
            "free_remaining": free_remaining,
            "billable_minutes": billable_minutes,
            "note": f"월 60분 무료, 남은 무료: {free_remaining:.1f}분"
        }
    
    elif provider == "openai":
        cost = video_duration_minutes * cost_per_minute
        
        return {
            "cost": cost,
            "provider": "OpenAI Whisper API",
            "free": False,
            "billable_minutes": video_duration_minutes,
            "note": "무료 할당량 없음, 25MB 파일 제한"
        }
    
    else:
        return {
            "cost": 0.0,
            "provider": "알 수 없음",
            "free": True,
            "note": "지원하지 않는 제공자"
        }

# 하위 호환성을 위한 기존 함수명 유지
def get_transcript_safe(video_id: str) -> Optional[str]:
    """하위 호환성을 위한 래퍼 함수"""
    return get_transcript(video_id, use_safe_stt=True)

def get_transcript_free_only(video_id: str) -> Optional[str]:
    """완전 무료로만 자막을 가져오는 함수"""
    return get_transcript_local_only(video_id, "base")