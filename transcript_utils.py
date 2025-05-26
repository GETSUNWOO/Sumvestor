import yt_dlp
import os
import tempfile
import requests
import re
from typing import Optional

# faster-whisper 임포트를 함수 내부로 이동
WHISPER_AVAILABLE = True

def get_whisper_model():
    """필요할 때만 Whisper 모델을 로드합니다."""
    try:
        from faster_whisper import WhisperModel
        return WhisperModel
    except ImportError as e:
        print(f"⚠️ faster-whisper 사용 불가: {e}")
        return None

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
    if WHISPER_AVAILABLE:
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


def extract_audio_and_transcribe(video_url: str) -> Optional[str]:
    """
    영상에서 오디오를 추출하고 faster-whisper로 STT 처리합니다.
    """
    # 실제 사용할 때만 import
    WhisperModel = get_whisper_model()
    if not WhisperModel:
        print("❌ faster-whisper를 로드할 수 없습니다.")
        return None
        
    try:
        # 임시 디렉토리 생성
        with tempfile.TemporaryDirectory() as temp_dir:
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
            
            # faster-whisper 모델 로드 (base 모델로 시작)
            print("🤖 faster-whisper 모델 로딩 중... (base 모델)")
            
            # CPU에서 실행 (GPU 없어도 괜찮음)
            model = WhisperModel("base", device="cpu", compute_type="int8")
            
            # STT 처리
            print("🎤 음성 인식 처리 중...")
            segments, info = model.transcribe(audio_file, language="ko")
            
            # 결과 텍스트 수집
            transcript_parts = []
            for segment in segments:
                transcript_parts.append(segment.text)
            
            transcript = " ".join(transcript_parts).strip()
            
            if len(transcript) < 10:
                print("⚠️ STT 결과가 너무 짧습니다.")
                return None
                
            print(f"✅ STT 완료: {len(transcript)}자")
            return transcript
            
    except Exception as e:
        print(f"faster-whisper STT 실패: {e}")
        return None


def clean_transcript(text: str) -> str:
    """
    자막 텍스트를 정리합니다.
    """
    if not text:
        return ""
    
    # HTML 태그 제거
    text = re.sub(r'<[^>]+>', '', text)
    
    # 중복 공백 제거
    text = re.sub(r'\s+', ' ', text)
    
    # 특수 문자 정리
    text = re.sub(r'[♪♫🎵🎶]', '', text)  # 음악 기호 제거
    
    # 앞뒤 공백 제거
    text = text.strip()
    
    return text