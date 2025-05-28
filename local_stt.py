# local_stt.py - faster-whisper 기반 로컬 STT (메모리 관리 통합)
import os
import tempfile
import shutil
import gc
import time
from typing import Optional, List, Tuple
from dataclasses import dataclass

import yt_dlp

# 메모리 관리자 통합 사용 (중복 클래스 제거)
from memory_manager import memory_manager, whisper_manager, memory_monitor_decorator

@dataclass 
class AudioChunk:
    """오디오 청크 정보"""
    file_path: str
    start_time: float
    end_time: float
    duration: float

class LocalSTT:
    """faster-whisper 기반 로컬 STT 처리 (메모리 최적화)"""
    
    def __init__(self, model_size: str = "base", enable_chunking: bool = True, chunk_duration: int = 600):
        self.model_size = model_size
        self.enable_chunking = enable_chunking
        self.chunk_duration = chunk_duration  # 초 단위
        self._temp_dir = None
        
        print(f"🎤 LocalSTT 초기화: 모델={model_size}, 청킹={enable_chunking}")
    
    def _get_model(self):
        """통합된 Whisper 모델 매니저 사용"""
        return whisper_manager.get_model(self.model_size)
    
    def _setup_temp_dir(self):
        """임시 디렉토리 설정"""
        if self._temp_dir is None:
            self._temp_dir = tempfile.mkdtemp(prefix="whisper_stt_")
            print(f"📁 임시 디렉토리: {self._temp_dir}")
    
    @memory_monitor_decorator
    def transcribe(self, video_url: str) -> 'STTResult':
        """메인 STT 처리 함수 (메모리 모니터링 포함)"""
        from safe_stt_engine import STTResult, STTProvider
        
        start_time = time.time()
        
        try:
            self._setup_temp_dir()
            
            # 메모리 압박 상황 체크
            if memory_manager.check_memory_pressure(threshold_mb=2500):
                print("⚠️ 메모리 압박 상황 - 정리 후 진행")
                memory_manager.force_cleanup(aggressive=True)
            
            # 1. 오디오 추출
            print("🎵 오디오 추출 중...")
            audio_file = self._extract_audio(video_url)
            if not audio_file:
                return STTResult(
                    success=False,
                    text="",
                    provider=STTProvider.LOCAL,
                    duration_seconds=time.time() - start_time,
                    error_message="오디오 추출 실패"
                )
            
            # 2. 오디오 정보 확인
            duration = self._get_audio_duration(audio_file)
            file_size_mb = os.path.getsize(audio_file) / 1024 / 1024
            
            print(f"🎵 오디오 정보: {duration:.1f}초, {file_size_mb:.1f}MB")
            
            # 메모리 부족시 작은 모델로 변경
            current_memory = memory_manager.get_memory_usage()["rss"]
            if current_memory > 2000 and self.model_size != "tiny":
                print(f"⚠️ 메모리 부족 ({current_memory:.0f}MB) - tiny 모델로 변경")
                original_size = self.model_size
                self.model_size = "tiny"
                whisper_manager.clear_model()  # 기존 모델 해제
            
            # 3. 청킹 여부 결정 및 처리
            if self.enable_chunking and duration > self.chunk_duration:
                print(f"📊 청킹 처리 모드: {duration:.1f}초 → {self.chunk_duration}초 단위")
                result = self._transcribe_chunks(audio_file, duration)
            else:
                print("🎤 단일 파일 처리 모드")
                result = self._transcribe_single(audio_file)
            
            # 처리 시간 설정
            result.duration_seconds = time.time() - start_time
            return result
            
        except Exception as e:
            print(f"❌ 로컬 STT 처리 실패: {e}")
            return STTResult(
                success=False,
                text="",
                provider=STTProvider.LOCAL,
                duration_seconds=time.time() - start_time,
                error_message=str(e)
            )
        finally:
            self._cleanup_temp_files()
            # 메모리 정리
            gc.collect()
    
    def _extract_audio(self, video_url: str) -> Optional[str]:
        """yt-dlp로 오디오 추출 (최적화)"""
        try:
            audio_output = os.path.join(self._temp_dir, "audio.wav")
            
            # 메모리 절약을 위한 최적화된 설정
            ydl_opts = {
                'format': 'bestaudio[filesize<100M]/bestaudio/best[filesize<100M]',  # 100MB 제한
                'outtmpl': audio_output.replace('.wav', '.%(ext)s'),
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'wav',
                    'preferredquality': '16',  # 16kHz로 품질 낮춤
                }],
                'postprocessor_args': [
                    '-ac', '1',          # 모노 채널
                    '-ar', '16000',      # 16kHz 샘플링
                    '-acodec', 'pcm_s16le',  # 16bit PCM
                    '-t', '7200',        # 최대 2시간 제한
                ],
                'quiet': True,
                'no_warnings': True,
                'extractaudio': True,
                'audioformat': 'wav',
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])
            
            # 추출된 파일 찾기
            for file in os.listdir(self._temp_dir):
                if file.startswith('audio') and file.endswith('.wav'):
                    result_path = os.path.join(self._temp_dir, file)
                    
                    # 파일 크기 체크
                    size_mb = os.path.getsize(result_path) / 1024 / 1024
                    if size_mb > 500:  # 500MB 초과시 경고
                        print(f"⚠️ 대용량 오디오 파일: {size_mb:.1f}MB")
                    
                    print(f"✅ 오디오 추출 완료: {file} ({size_mb:.1f}MB)")
                    return result_path
            
            print("❌ 오디오 파일을 찾을 수 없음")
            return None
            
        except Exception as e:
            print(f"❌ 오디오 추출 실패: {e}")
            return None
    
    def _get_audio_duration(self, audio_file: str) -> float:
        """오디오 파일 길이 확인 (여러 방법 시도)"""
        try:
            # 방법 1: wave 라이브러리 사용
            import wave
            with wave.open(audio_file, 'r') as wav_file:
                frames = wav_file.getnframes()
                rate = wav_file.getframerate()
                duration = frames / float(rate)
                return duration
        except Exception:
            pass
        
        try:
            # 방법 2: ffmpeg-python 사용
            import ffmpeg
            probe = ffmpeg.probe(audio_file)
            duration = float(probe['streams'][0]['duration'])
            return duration
        except Exception:
            pass
        
        # 방법 3: 파일 크기로 추정 (16kHz, 16bit, mono 기준)
        try:
            file_size = os.path.getsize(audio_file)
            estimated_duration = file_size / (16000 * 2)  # 16kHz * 2bytes
            print(f"⚠️ 길이 추정: {estimated_duration:.1f}초 (파일 크기 기준)")
            return estimated_duration
        except Exception:
            return 1800.0  # 기본값 30분
    
    def _create_audio_chunks(self, audio_file: str, duration: float) -> List[AudioChunk]:
        """오디오를 청크로 분할 (메모리 효율적)"""
        chunks = []
        
        try:
            import ffmpeg
            
            chunk_count = int(duration / self.chunk_duration) + 1
            print(f"📊 {chunk_count}개 청크로 분할 처리 예정")
            
            # 너무 많은 청크는 메모리 문제 발생 가능
            if chunk_count > 20:
                print(f"⚠️ 청크 수 제한: {chunk_count} → 20개")
                chunk_count = 20
                self.chunk_duration = int(duration / 20)
            
            for i in range(chunk_count):
                start_time = i * self.chunk_duration
                end_time = min(start_time + self.chunk_duration, duration)
                
                if start_time >= duration:
                    break
                
                chunk_file = os.path.join(self._temp_dir, f"chunk_{i:03d}.wav")
                
                try:
                    # ffmpeg로 청크 추출
                    (
                        ffmpeg
                        .input(audio_file, ss=start_time, t=(end_time - start_time))
                        .output(
                            chunk_file, 
                            acodec='pcm_s16le', 
                            ac=1, 
                            ar=16000,
                            loglevel='quiet'
                        )
                        .overwrite_output()
                        .run(capture_stdout=True, capture_stderr=True)
                    )
                    
                    if os.path.exists(chunk_file) and os.path.getsize(chunk_file) > 1000:
                        chunks.append(AudioChunk(
                            file_path=chunk_file,
                            start_time=start_time,
                            end_time=end_time,
                            duration=end_time - start_time
                        ))
                    else:
                        print(f"⚠️ 청크 {i} 생성 실패 또는 파일이 너무 작음")
                        
                except Exception as e:
                    print(f"⚠️ 청크 {i} 분할 실패: {e}")
                    continue
            
            print(f"✅ {len(chunks)}개 청크 생성 완료")
            return chunks
            
        except ImportError:
            print("⚠️ ffmpeg-python 미설치, 단일 파일로 처리")
            return [AudioChunk(
                file_path=audio_file,
                start_time=0,
                end_time=duration,
                duration=duration
            )]
        except Exception as e:
            print(f"⚠️ 청크 분할 실패: {e}, 단일 파일로 처리")
            return [AudioChunk(
                file_path=audio_file,
                start_time=0,
                end_time=duration,
                duration=duration
            )]
    
    def _transcribe_chunks(self, audio_file: str, duration: float) -> 'STTResult':
        """청크 단위로 STT 처리 (메모리 최적화)"""
        from safe_stt_engine import STTResult, STTProvider
        
        chunks = self._create_audio_chunks(audio_file, duration)
        if not chunks:
            return STTResult(
                success=False,
                text="",
                provider=STTProvider.LOCAL,
                duration_seconds=0,
                error_message="청크 생성 실패"
            )
        
        model = self._get_model()
        if not model:
            return STTResult(
                success=False,
                text="",
                provider=STTProvider.LOCAL,
                duration_seconds=0,
                error_message="Whisper 모델 로드 실패"
            )
        
        all_texts = []
        processed_chunks = 0
        failed_chunks = 0
        
        for i, chunk in enumerate(chunks):
            try:
                print(f"🎤 청크 {i+1}/{len(chunks)} 처리 중... ({chunk.start_time:.1f}s-{chunk.end_time:.1f}s)")
                
                # 메모리 체크 (매 3청크마다)
                if i % 3 == 0:
                    current_memory = memory_manager.get_memory_usage()["rss"]
                    if current_memory > 3000:  # 3GB 초과
                        print(f"⚠️ 메모리 부족으로 청크 처리 중단 ({i+1}/{len(chunks)}) - {current_memory:.0f}MB")
                        break
                
                # STT 처리 (메모리 효율적 설정)
                segments, info = model.transcribe(
                    chunk.file_path,
                    language="ko",
                    condition_on_previous_text=False,  # 메모리 절약
                    temperature=0.0,
                    compression_ratio_threshold=2.4,
                    no_speech_threshold=0.6,
                    beam_size=1,  # 메모리 절약을 위해 beam size 감소
                    best_of=1     # 메모리 절약
                )
                
                # 결과 수집
                chunk_texts = []
                for segment in segments:
                    text = segment.text.strip()
                    if text and len(text) > 1:  # 너무 짧은 텍스트 제외
                        chunk_texts.append(text)
                
                chunk_text = " ".join(chunk_texts).strip()
                if chunk_text:
                    all_texts.append(chunk_text)
                    processed_chunks += 1
                else:
                    failed_chunks += 1
                
                # 청크 파일 즉시 삭제 (메모리 절약)
                if chunk.file_path != audio_file:  # 원본 파일이 아닌 경우만
                    try:
                        os.remove(chunk.file_path)
                    except:
                        pass
                
                # 메모리 정리 (매 청크마다)
                del segments, info, chunk_texts, chunk_text
                gc.collect()
                
                # 진행률 출력
                if (i + 1) % 5 == 0 or i == len(chunks) - 1:
                    print(f"📊 진행률: {i+1}/{len(chunks)} 청크 완료 (성공: {processed_chunks}, 실패: {failed_chunks})")
                
            except Exception as e:
                print(f"❌ 청크 {i+1} 처리 실패: {e}")
                failed_chunks += 1
                continue
        
        # 최종 결과 조합
        final_text = " ".join(all_texts).strip()
        success = len(final_text) > 50 and processed_chunks > 0
        confidence = processed_chunks / len(chunks) if chunks else 0
        
        print(f"✅ 청킹 STT 완료: {processed_chunks}/{len(chunks)} 청크 성공, {len(final_text)}자 생성")
        
        if failed_chunks > processed_chunks:
            print(f"⚠️ 실패 청크가 많음: 성공 {processed_chunks} vs 실패 {failed_chunks}")
        
        return STTResult(
            success=success,
            text=final_text,
            provider=STTProvider.LOCAL,
            duration_seconds=0,  # 나중에 설정됨
            chunks_processed=processed_chunks,
            confidence=confidence
        )
    
    def _transcribe_single(self, audio_file: str) -> 'STTResult':
        """단일 파일 STT 처리 (메모리 최적화)"""
        from safe_stt_engine import STTResult, STTProvider
        
        try:
            model = self._get_model()
            if not model:
                return STTResult(
                    success=False,
                    text="",
                    provider=STTProvider.LOCAL,
                    duration_seconds=0,
                    error_message="Whisper 모델 로드 실패"
                )
            
            print("🎤 단일 파일 STT 처리 중...")
            
            # 파일 크기 체크
            file_size_mb = os.path.getsize(audio_file) / 1024 / 1024
            if file_size_mb > 200:  # 200MB 초과시 경고
                print(f"⚠️ 대용량 파일 처리: {file_size_mb:.1f}MB")
            
            # 메모리 효율적 설정으로 STT 처리
            segments, info = model.transcribe(
                audio_file,
                language="ko",
                condition_on_previous_text=False,
                temperature=0.0,
                compression_ratio_threshold=2.4,
                no_speech_threshold=0.6,
                beam_size=1,  # 메모리 절약
                best_of=1     # 메모리 절약
            )
            
            # 결과 수집 (메모리 효율적)
            all_texts = []
            segment_count = 0
            
            for segment in segments:
                text = segment.text.strip()
                if text and len(text) > 1:
                    all_texts.append(text)
                    segment_count += 1
                
                # 너무 많은 세그먼트시 중간 정리
                if segment_count % 100 == 0:
                    gc.collect()
            
            final_text = " ".join(all_texts).strip()
            success = len(final_text) > 20
            
            print(f"✅ 단일 STT 완료: {segment_count}개 세그먼트, {len(final_text)}자")
            
            return STTResult(
                success=success,
                text=final_text,
                provider=STTProvider.LOCAL,
                duration_seconds=0,
                chunks_processed=1,
                confidence=1.0 if success else 0.0
            )
            
        except Exception as e:
            print(f"❌ 단일 STT 실패: {e}")
            return STTResult(
                success=False,
                text="",
                provider=STTProvider.LOCAL,
                duration_seconds=0,
                error_message=str(e)
            )
    
    def _cleanup_temp_files(self):
        """임시 파일 정리 (안전한 삭제)"""
        if self._temp_dir and os.path.exists(self._temp_dir):
            try:
                # 파일 개수 확인
                file_count = len(os.listdir(self._temp_dir))
                total_size = sum(
                    os.path.getsize(os.path.join(self._temp_dir, f)) 
                    for f in os.listdir(self._temp_dir)
                ) / 1024 / 1024
                
                shutil.rmtree(self._temp_dir, ignore_errors=True)
                print(f"🗑️ 임시 파일 정리 완료: {file_count}개 파일, {total_size:.1f}MB")
            except Exception as e:
                print(f"⚠️ 임시 파일 정리 실패: {e}")
            finally:
                self._temp_dir = None
    
    def cleanup(self):
        """리소스 정리 (통합된 메모리 관리자 사용)"""
        print("🗑️ LocalSTT 리소스 정리 중...")
        
        # 임시 파일 정리
        self._cleanup_temp_files()
        
        # 통합 모델 관리자를 통한 정리 (중복 제거)
        # whisper_manager.clear_model()  # 필요시에만 호출
        
        # 메모리 정리
        memory_manager.force_cleanup(aggressive=True)
        
        print("✅ LocalSTT 정리 완료")
    
    def get_model_info(self) -> dict:
        """현재 모델 정보 반환"""
        model_info = whisper_manager.get_model_info()
        if model_info:
            return model_info
        else:
            return {
                "size": self.model_size,
                "loaded": False,
                "device": "cpu",
                "compute_type": "int8"
            }
    
    def is_model_loaded(self) -> bool:
        """모델 로딩 상태 확인"""
        return whisper_manager.is_loaded()

# 편의 함수들
def transcribe_video_local(video_url: str, model_size: str = "base", enable_chunking: bool = True) -> dict:
    """
    단일 함수로 로컬 STT 처리
    
    Args:
        video_url: YouTube URL
        model_size: Whisper 모델 크기 (tiny, base, small)
        enable_chunking: 청킹 사용 여부
    
    Returns:
        dict: 처리 결과
    """
    local_stt = LocalSTT(model_size=model_size, enable_chunking=enable_chunking)
    
    try:
        result = local_stt.transcribe(video_url)
        
        return {
            "success": result.success,
            "text": result.text,
            "duration": result.duration_seconds,
            "chunks_processed": result.chunks_processed,
            "confidence": result.confidence,
            "error": result.error_message,
            "model_info": local_stt.get_model_info()
        }
    finally:
        local_stt.cleanup()

def estimate_processing_time(video_duration_minutes: float, model_size: str = "base") -> dict:
    """
    로컬 STT 처리 시간 추정
    
    Args:
        video_duration_minutes: 영상 길이 (분)
        model_size: 모델 크기
    
    Returns:
        dict: 시간 추정 정보
    """
    # 모델별 처리 속도 (실제 시간 대비 배수)
    speed_multipliers = {
        "tiny": 0.1,   # 10% 시간 (매우 빠름)
        "base": 0.15,  # 15% 시간 (보통)
        "small": 0.25, # 25% 시간 (느림)
        "medium": 0.4, # 40% 시간 (매우 느림)
        "large": 0.6   # 60% 시간 (가장 느림)
    }
    
    multiplier = speed_multipliers.get(model_size, 0.15)
    estimated_minutes = video_duration_minutes * multiplier
    
    return {
        "video_duration": video_duration_minutes,
        "model_size": model_size,
        "estimated_processing_minutes": estimated_minutes,
        "estimated_processing_time": f"{int(estimated_minutes)}분 {int((estimated_minutes % 1) * 60)}초",
        "speed_multiplier": multiplier,
        "memory_usage_mb": {
            "tiny": 500,
            "base": 1000,
            "small": 2000,
            "medium": 4000,
            "large": 8000
        }.get(model_size, 1000)
    }

# 시스템 체크 함수
def check_local_stt_requirements() -> dict:
    """로컬 STT 시스템 요구사항 체크"""
    requirements = {
        "faster_whisper": False,
        "yt_dlp": False,
        "ffmpeg_python": False,
        "torch": False,
        "system_memory_gb": 0,
        "available_models": [],
        "recommended_model": "base"
    }
    
    try:
        import faster_whisper
        requirements["faster_whisper"] = True
        
        # 사용 가능한 모델 체크
        try:
            test_model = faster_whisper.WhisperModel("tiny", device="cpu")
            requirements["available_models"].append("tiny")
            del test_model
            gc.collect()
        except:
            pass
            
    except ImportError:
        pass
    
    try:
        import yt_dlp
        requirements["yt_dlp"] = True
    except ImportError:
        pass
    
    try:
        import ffmpeg
        requirements["ffmpeg_python"] = True
    except ImportError:
        pass
    
    try:
        import torch
        requirements["torch"] = True
    except ImportError:
        pass
    
    # 시스템 메모리 체크
    try:
        import psutil
        memory_gb = psutil.virtual_memory().total / (1024**3)
        requirements["system_memory_gb"] = round(memory_gb, 1)
        
        # 메모리 기반 권장 모델
        if memory_gb < 4:
            requirements["recommended_model"] = "tiny"
        elif memory_gb < 8:
            requirements["recommended_model"] = "base"
        else:
            requirements["recommended_model"] = "small"
            
    except ImportError:
        pass
    
    # 전체 준비 상태
    requirements["ready"] = all([
        requirements["faster_whisper"],
        requirements["yt_dlp"],
        requirements["torch"]
    ])
    
    return requirements