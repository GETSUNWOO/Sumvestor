# cloud_stt.py - 클라우드 STT API 통합
import os
import tempfile
import time
from typing import Optional
from abc import ABC, abstractmethod

class CloudSTT(ABC):
    """클라우드 STT 기본 클래스"""
    
    @abstractmethod
    def transcribe(self, video_url: str) -> 'STTResult':
        pass
    
    @abstractmethod  
    def cleanup(self):
        pass

class GoogleSTT(CloudSTT):
    """Google Cloud Speech-to-Text API"""
    
    def __init__(self):
        self.client = None
        self._setup_client()
    
    def _setup_client(self):
        """Google Cloud 클라이언트 설정"""
        try:
            from google.cloud import speech
            
            credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            if not credentials_path:
                raise ValueError("GOOGLE_APPLICATION_CREDENTIALS 환경변수 필요")
            
            self.client = speech.SpeechClient()
            print("✅ Google Cloud STT 클라이언트 초기화 완료")
            
        except ImportError:
            raise RuntimeError("Google Cloud Speech 라이브러리 필요: pip install google-cloud-speech")
        except Exception as e:
            raise RuntimeError(f"Google Cloud STT 초기화 실패: {e}")
    
    def transcribe(self, video_url: str) -> 'STTResult':
        """Google STT 처리"""
        from stt_engine import STTResult, STTProvider
        
        try:
            # 오디오 추출 및 변환
            audio_file = self._extract_and_convert_audio(video_url)
            if not audio_file:
                return STTResult(
                    success=False,
                    text="",
                    provider=STTProvider.GOOGLE,
                    duration_seconds=0,
                    error_message="오디오 추출 실패"
                )
            
            # Google Cloud STT 처리
            print("🎤 Google Cloud STT 처리 중...")
            
            # 오디오 파일 읽기
            with open(audio_file, "rb") as audio_data:
                content = audio_data.read()
            
            # STT 설정
            audio = {"content": content}
            config = {
                "encoding": "LINEAR16",
                "sample_rate_hertz": 16000,
                "language_code": "ko-KR",
                "alternative_language_codes": ["en-US"],
                "enable_automatic_punctuation": True,
                "enable_word_confidence": True,
                "model": "latest_long"  # 긴 오디오용 모델
            }
            
            # STT 요청
            response = self.client.recognize(config=config, audio=audio)
            
            # 결과 처리
            transcript_parts = []
            confidence_scores = []
            
            for result in response.results:
                alternative = result.alternatives[0]
                transcript_parts.append(alternative.transcript)
                confidence_scores.append(alternative.confidence)
            
            final_text = " ".join(transcript_parts).strip()
            avg_confidence = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0
            
            success = len(final_text) > 10
            
            print(f"✅ Google STT 완료: {len(final_text)}자, 신뢰도: {avg_confidence:.2f}")
            
            return STTResult(
                success=success,
                text=final_text,
                provider=STTProvider.GOOGLE,
                duration_seconds=0,
                confidence=avg_confidence
            )
            
        except Exception as e:
            print(f"❌ Google STT 실패: {e}")
            return STTResult(
                success=False,
                text="",
                provider=STTProvider.GOOGLE,
                duration_seconds=0,
                error_message=str(e)
            )
        finally:
            # 임시 파일 정리
            if 'audio_file' in locals() and audio_file and os.path.exists(audio_file):
                try:
                    os.remove(audio_file)
                except:
                    pass
    
    def _extract_and_convert_audio(self, video_url: str) -> Optional[str]:
        """오디오 추출 및 Google STT 형식으로 변환"""
        try:
            import yt_dlp
            
            temp_dir = tempfile.mkdtemp(prefix="google_stt_")
            audio_output = os.path.join(temp_dir, "audio.wav")
            
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': audio_output.replace('.wav', '.%(ext)s'),
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'wav',
                    'preferredquality': '16',
                }],
                'postprocessor_args': [
                    '-ac', '1',      # 모노
                    '-ar', '16000',  # 16kHz
                    '-acodec', 'pcm_s16le'  # 16-bit PCM
                ],
                'quiet': True,
                'no_warnings': True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])
            
            # 변환된 파일 찾기
            for file in os.listdir(temp_dir):
                if file.startswith('audio') and file.endswith('.wav'):
                    return os.path.join(temp_dir, file)
            
            return None
            
        except Exception as e:
            print(f"❌ Google STT용 오디오 변환 실패: {e}")
            return None
    
    def cleanup(self):
        """리소스 정리"""
        self.client = None

class OpenAISTT(CloudSTT):
    """OpenAI Whisper API"""
    
    def __init__(self):
        self.client = None
        self._setup_client()
    
    def _setup_client(self):
        """OpenAI 클라이언트 설정"""
        try:
            import openai
            
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY 환경변수 필요")
            
            self.client = openai.OpenAI(api_key=api_key)
            print("✅ OpenAI STT 클라이언트 초기화 완료")
            
        except ImportError:
            raise RuntimeError("OpenAI 라이브러리 필요: pip install openai")
        except Exception as e:
            raise RuntimeError(f"OpenAI STT 초기화 실패: {e}")
    
    def transcribe(self, video_url: str) -> 'STTResult':
        """OpenAI Whisper API 처리"""
        from stt_engine import STTResult, STTProvider
        
        try:
            # 오디오 추출
            audio_file = self._extract_audio_for_openai(video_url)
            if not audio_file:
                return STTResult(
                    success=False,
                    text="",
                    provider=STTProvider.OPENAI,
                    duration_seconds=0,
                    error_message="오디오 추출 실패"
                )
            
            # 파일 크기 체크 (OpenAI 제한: 25MB)
            file_size_mb = os.path.getsize(audio_file) / 1024 / 1024
            if file_size_mb > 24:  # 안전 마진
                return STTResult(
                    success=False,
                    text="",
                    provider=STTProvider.OPENAI,
                    duration_seconds=0,
                    error_message=f"파일이 너무 큼: {file_size_mb:.1f}MB (최대 25MB)"
                )
            
            print(f"🎤 OpenAI Whisper API 처리 중... ({file_size_mb:.1f}MB)")
            
            # OpenAI Whisper API 호출
            with open(audio_file, "rb") as audio_data:
                transcript = self.client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_data,
                    language="ko",  # 한국어 지정
                    response_format="text"
                )
            
            final_text = transcript.strip() if isinstance(transcript, str) else str(transcript).strip()
            success = len(final_text) > 10
            
            print(f"✅ OpenAI STT 완료: {len(final_text)}자")
            
            return STTResult(
                success=success,
                text=final_text,
                provider=STTProvider.OPENAI,
                duration_seconds=0,
                confidence=0.9  # OpenAI는 신뢰도 제공 안함, 임의값
            )
            
        except Exception as e:
            print(f"❌ OpenAI STT 실패: {e}")
            return STTResult(
                success=False,
                text="",
                provider=STTProvider.OPENAI,
                duration_seconds=0,
                error_message=str(e)
            )
        finally:
            # 임시 파일 정리
            if 'audio_file' in locals() and audio_file and os.path.exists(audio_file):
                try:
                    os.remove(audio_file)
                except:
                    pass
    
    def _extract_audio_for_openai(self, video_url: str) -> Optional[str]:
        """OpenAI API용 오디오 추출 (MP3 형식)"""
        try:
            import yt_dlp
            
            temp_dir = tempfile.mkdtemp(prefix="openai_stt_")
            audio_output = os.path.join(temp_dir, "audio.mp3")
            
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': audio_output.replace('.mp3', '.%(ext)s'),
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '128',  # 품질 낮춤 (파일 크기 제한)
                }],
                'quiet': True,
                'no_warnings': True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])
            
            # 변환된 파일 찾기
            for file in os.listdir(temp_dir):
                if file.startswith('audio') and file.endswith('.mp3'):
                    return os.path.join(temp_dir, file)
            
            return None
            
        except Exception as e:
            print(f"❌ OpenAI STT용 오디오 변환 실패: {e}")
            return None
    
    def cleanup(self):
        """리소스 정리"""
        self.client = None