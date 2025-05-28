import yt_dlp
import os
import tempfile
import requests
import re
import gc
from typing import Optional

# 메모리 관리 모듈 import
from memory_manager import whisper_manager, memory_manager, memory_monitor_decorator

# faster-whisper 가용성 체크
WHISPER_AVAILABLE = True

def get_whisper_model():
    """Whisper 모델 매니저 사용 (더 이상 직접 import 하지 않음)"""
    return whisper_manager.get_model()

@memory_monitor_decorator
def get_transcript(video_id: str) -> Optional[str]:
    """
    YouTube 영상의 자막을 가져옵니다.
    1순위: 자동생성 자막 (한국어/영어)
    2순위: faster-whisper STT (사용 가능한 경우)
    """
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    
    # 1. yt-dlp로 자막 추출 시도
    transcript = extract_subtitles_with_ytdlp(video_url)
    
    if transcript:
        print(f"✅ 자막 수집 성공: {video_id}")
        return transcript
    
    # 2. 자막이 없으면 faster-whisper STT 시도
    if whisper_manager.is_loaded() or WHISPER_AVAILABLE:
        print(f"🎤 자막이 없어서 faster-whisper STT 시도: {video_id}")
        return extract_audio_and_transcribe(video_url)
    else:
        print(f"❌ 자막 없음 + Whisper 불가: {video_id}")
        return None


def extract_subtitles_with_ytdlp(video_url: str) -> Optional[str]:
    """
    yt-dlp를 사용하여 자막을 추출합니다.
    """
    try:
        ydl_opts = {
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitleslangs': ['ko', 'en'],  # 한국어, 영어 우선
            'skip_download': True,  # 영상 다운로드 하지 않음
            'subtitlesformat': 'srt',
            'quiet': True,  # 로그 최소화
            'no_warnings': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # 자막 정보만 추출
            info = ydl.extract_info(video_url, download=False)
            
            # 자동 생성 자막 확인
            if 'automatic_captions' in info and info['automatic_captions']:
                auto_captions = info['automatic_captions']
                
                # 한국어 자막 우선
                if 'ko' in auto_captions:
                    for caption in auto_captions['ko']:
                        if caption.get('ext') == 'srt' or 'url' in caption:
                            subtitle_text = download_subtitle_content(caption['url'])
                            if subtitle_text:
                                return subtitle_text
                
                # 영어 자막 대체
                if 'en' in auto_captions:
                    for caption in auto_captions['en']:
                        if caption.get('ext') == 'srt' or 'url' in caption:
                            subtitle_text = download_subtitle_content(caption['url'])
                            if subtitle_text:
                                return subtitle_text
            
            # 수동 업로드 자막 확인
            if 'subtitles' in info and info['subtitles']:
                subtitles = info['subtitles']
                
                if 'ko' in subtitles:
                    for subtitle in subtitles['ko']:
                        if subtitle.get('ext') == 'srt' or 'url' in subtitle:
                            subtitle_text = download_subtitle_content(subtitle['url'])
                            if subtitle_text:
                                return subtitle_text
                                
                if 'en' in subtitles:
                    for subtitle in subtitles['en']:
                        if subtitle.get('ext') == 'srt' or 'url' in subtitle:
                            subtitle_text = download_subtitle_content(subtitle['url'])
                            if subtitle_text:
                                return subtitle_text
        
        return None
        
    except Exception as e:
        print(f"자막 추출 실패: {e}")
        return None


def download_subtitle_content(subtitle_url: str) -> str:
    """
    자막 URL에서 실제 텍스트를 다운로드합니다.
    """
    try:
        response = requests.get(subtitle_url, timeout=30)
        response.raise_for_status()
        
        # SRT 포맷에서 텍스트만 추출
        subtitle_text = response.text
        
        # 타임코드와 숫자 제거하고 텍스트만 추출
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
            
            clean_lines.append(line)
        
        result = ' '.join(clean_lines)
        return result if len(result) > 10 else ""  # 너무 짧은 자막은 제외
        
    except Exception as e:
        print(f"자막 다운로드 실패: {e}")
        return ""


@memory_monitor_decorator
def extract_audio_and_transcribe(video_url: str) -> Optional[str]:
    """
    영상에서 오디오를 추출하고 faster-whisper로 STT 처리합니다.
    메모리 최적화 적용 버전
    """
    # 메모리 압박 체크
    if memory_manager.check_memory_pressure(threshold_mb=2500):
        print("⚠️ 메모리 부족으로 STT 처리를 건너뜁니다.")
        return None
    
    try:
        # 임시 디렉토리 생성
        temp_dir = tempfile.mkdtemp(prefix="whisper_")
        
        try:
            # 오디오 파일 경로 (확장자 없이)
            audio_path_base = os.path.join(temp_dir, "audio")
            
            # yt-dlp로 오디오만 추출
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': audio_path_base + '.%(ext)s',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'wav',  # faster-whisper는 wav 선호
                    'preferredquality': '192',
                }],
                'quiet': True,
                'no_warnings': True,
            }
            
            print("🎵 오디오 추출 중...")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])
            
            # 생성된 오디오 파일 찾기
            audio_file = None
            for file in os.listdir(temp_dir):
                if file.startswith('audio') and (file.endswith('.wav') or file.endswith('.mp3')):
                    audio_file = os.path.join(temp_dir, file)
                    break
            
            if not audio_file or not os.path.exists(audio_file):
                print("❌ 오디오 파일 추출 실패")
                return None
            
            # 파일 크기 체크 (너무 크면 처리 안함)
            file_size_mb = os.path.getsize(audio_file) / 1024 / 1024
            if file_size_mb > 200:  # 200MB 초과
                print(f"⚠️ 오디오 파일이 너무 큽니다 ({file_size_mb:.1f}MB). STT를 건너뜁니다.")
                return None
            
            print(f"📁 오디오 파일 크기: {file_size_mb:.1f}MB")
            
            # Whisper 모델 가져오기 (싱글톤)
            model = whisper_manager.get_model("base")  # base 모델 사용
            
            if not model:
                print("❌ Whisper 모델을 로드할 수 없습니다.")
                return None
            
            # STT 처리
            print("🎤 음성 인식 처리 중...")
            
            # 메모리 사용량 모니터링하면서 처리
            memory_before = memory_manager.get_memory_usage()["rss"]
            
            segments, info = model.transcribe(
                audio_file, 
                language="ko",
                condition_on_previous_text=False,  # 메모리 절약
                temperature=0.0,  # 안정성 향상
                compression_ratio_threshold=2.4,  # 반복 텍스트 방지
                no_speech_threshold=0.6  # 무음 구간 필터링
            )
            
            # 결과 텍스트 수집
            transcript_parts = []
            segment_count = 0
            
            for segment in segments:
                transcript_parts.append(segment.text.strip())
                segment_count += 1
                
                # 중간중간 메모리 체크
                if segment_count % 50 == 0:
                    current_memory = memory_manager.get_memory_usage()["rss"]
                    if current_memory > memory_before + 1000:  # 1GB 증가시
                        print("⚠️ 메모리 사용량 급증, 가비지 컬렉션 실행")
                        gc.collect()
            
            transcript = " ".join(transcript_parts).strip()
            
            memory_after = memory_manager.get_memory_usage()["rss"]
            print(f"📊 STT 메모리 사용량: +{memory_after - memory_before:.1f}MB")
            
            if len(transcript) < 10:
                print("⚠️ STT 결과가 너무 짧습니다.")
                return None
                
            print(f"✅ STT 완료: {len(transcript)}자, {segment_count}개 세그먼트")
            return transcript
            
        finally:
            # 임시 파일 정리 (확실하게)
            try:
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
                print("🗑️ 임시 파일 정리 완료")
            except:
                pass
            
            # 명시적 가비지 컬렉션
            gc.collect()
            
    except Exception as e:
        print(f"faster-whisper STT 실패: {e}")
        
        # 에러 발생시 모델 해제 고려
        current_memory = memory_manager.get_memory_usage()["rss"]
        if current_memory > 3500:  # 3.5GB 초과시
            print("🗑️ 메모리 부족으로 Whisper 모델 해제")
            whisper_manager.clear_model()
        
        return None


def clean_transcript(text: str) -> str:
    """
    자막 텍스트를 정리합니다.
    메모리 효율적인 버전
    """
    if not text:
        return ""
    
    # 큰 텍스트의 경우 청크 단위로 처리
    if len(text) > 50000:  # 50KB 이상
        return clean_large_transcript(text)
    
    # HTML 태그 제거
    text = re.sub(r'<[^>]+>', '', text)
    
    # 중복 공백 제거
    text = re.sub(r'\s+', ' ', text)
    
    # 특수 문자 정리
    text = re.sub(r'[♪♫🎵🎶]', '', text)  # 음악 기호 제거
    
    # 앞뒤 공백 제거
    text = text.strip()
    
    return text


def clean_large_transcript(text: str, chunk_size: int = 10000) -> str:
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
        
        cleaned_chunks.append(chunk.strip())
        
        # 중간중간 메모리 정리
        if i % (chunk_size * 5) == 0:
            gc.collect()
    
    result = ' '.join(cleaned_chunks)
    
    # 최종 정리
    gc.collect()
    
    return result