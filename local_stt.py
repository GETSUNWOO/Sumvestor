# local_stt.py - faster-whisper 기반 로컬 STT
import os
import tempfile
import shutil
import gc
import time
from typing import Optional, List, Tuple
from dataclasses import dataclass

import yt_dlp
from memory_manager import memory_manager, memory_monitor_decorator

@dataclass 
class AudioChunk:
    """오디오 청크 정보"""
    file_path: str
    start_time: float
    end_time: float
    duration: float

class LocalSTT:
    """faster-whisper 기반 로컬 STT 처리"""
    
    def __init__(self, model_size: str = "base", enable_chunking: bool = True, chunk_duration: int = 600):
        self.model_size = model_size
        self.enable_chunking = enable_chunking
        self.chunk_duration = chunk_duration  # 초 단위
        self._model = None
        self._temp_dir = None
    
    def _get_model(self):
        """Whisper 모델 로딩 (지연 로딩)"""
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
                
                print(f"🤖 Whisper 모델 로딩 중... ({self.model_size})")
                memory_before = memory_manager.get_memory_usage()["rss"]
                
                # CPU 최적화 설정
                self._model = WhisperModel(
                    self.model_size,
                    device="cpu",
                    compute_type="int8",  # 메모리 절약
                    cpu_threads=4,        # 스레드 제한
                    num_workers=1         # 워커 제한
                )
                
                memory_after = memory_manager.get_memory_usage()["rss"]
                print(f"✅ 모델 로딩 완료 (+{memory_after - memory_before:.1f}MB)")
                
            except ImportError as e:
                raise RuntimeError("faster-whisper 설치 필요: pip install faster-whisper")
            except Exception as e:
                raise RuntimeError(f"Whisper 모델 로딩 실패: {e}")
        
        return self._model
    
    def _setup_temp_dir(self):
        """임시 디렉토리 설정"""
        if self._temp_dir is None:
            self._temp_dir = tempfile.mkdtemp(prefix="whisper_stt_")
            print(f"📁 임시 디렉토리: {self._temp_dir}")
    
    @memory_monitor_decorator
    def transcribe(self, video_url: str) -> 'STTResult':
        """메인 STT 처리 함수"""
        from stt_engine import STTResult, STTProvider
        
        try:
            self._setup_temp_dir()
            
            # 1. 오디오 추출
            audio_file = self._extract_audio(video_url)
            if not audio_file:
                return STTResult(
                    success=False,
                    text="",
                    provider=STTProvider.LOCAL,
                    duration_seconds=0,
                    error_message="오디오 추출 실패"
                )
            
            # 2. 오디오 정보 확인
            duration = self._get_audio_duration(audio_file)
            file_size_mb = os.path.getsize(audio_file) / 1024 / 1024
            
            print(f"🎵 오디오 정보: {duration:.1f}초, {file_size_mb:.1f}MB")
            
            # 3. 청킹 여부 결정
            if self.enable_chunking and duration > self.chunk_duration:
                chunks_result = self._transcribe_chunks(audio_file, duration)
            else:
                chunks_result = self._transcribe_single(audio_file)
            
            return chunks_result
            
        except Exception as e:
            print(f"❌ 로컬 STT 처리 실패: {e}")
            return STTResult(
                success=False,
                text="",
                provider=STTProvider.LOCAL,
                duration_seconds=0,
                error_message=str(e)
            )
        finally:
            self._cleanup_temp_files()
    
    def _extract_audio(self, video_url: str) -> Optional[str]:
        """yt-dlp로 오디오 추출"""
        try:
            audio_output = os.path.join(self._temp_dir, "audio.wav")
            
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': audio_output.replace('.wav', '.%(ext)s'),
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'wav',
                    'preferredquality': '16',  # 16kHz로 품질 낮춤 (Whisper는 16kHz에서 동작)
                }],
                'postprocessor_args': [
                    '-ac', '1',  # 모노 채널
                    '-ar', '16000',  # 16kHz 샘플링
                ],
                'quiet': True,
                'no_warnings': True,
            }
            
            print("🎵 오디오 추출 중...")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])
            
            # 추출된 파일 찾기
            for file in os.listdir(self._temp_dir):
                if file.startswith('audio') and file.endswith('.wav'):
                    result_path = os.path.join(self._temp_dir, file)
                    print(f"✅ 오디오 추출 완료: {file}")
                    return result_path
            
            print("❌ 오디오 파일을 찾을 수 없음")
            return None
            
        except Exception as e:
            print(f"❌ 오디오 추출 실패: {e}")
            return None
    
    def _get_audio_duration(self, audio_file: str) -> float:
        """오디오 파일 길이 확인"""
        try:
            import wave
            with wave.open(audio_file, 'r') as wav_file:
                frames = wav_file.getnframes()
                rate = wav_file.getframerate()
                duration = frames / float(rate)
                return duration
        except:
            # 대략적인 크기로 추정 (16kHz, 16bit, mono 기준)
            file_size = os.path.getsize(audio_file)
            estimated_duration = file_size / (16000 * 2)  # 16kHz * 2bytes
            return estimated_duration
    
    def _create_audio_chunks(self, audio_file: str, duration: float) -> List[AudioChunk]:
        """오디오를 청크로 분할"""
        chunks = []
        
        try:
            import ffmpeg
            
            chunk_count = int(duration / self.chunk_duration) + 1
            print(f"📊 {chunk_count}개 청크로 분할 처리")
            
            for i in range(chunk_count):
                start_time = i * self.chunk_duration
                end_time = min(start_time + self.chunk_duration, duration)
                
                if start_time >= duration:
                    break
                
                chunk_file = os.path.join(self._temp_dir, f"chunk_{i:03d}.wav")
                
                # ffmpeg로 청크 추출
                (
                    ffmpeg
                    .input(audio_file, ss=start_time, t=(end_time - start_time))
                    .output(chunk_file, acodec='pcm_s16le', ac=1, ar=16000)
                    .overwrite_output()
                    .run(quiet=True, capture_stdout=True)
                )
                
                if os.path.exists(chunk_file):
                    chunks.append(AudioChunk(
                        file_path=chunk_file,
                        start_time=start_time,
                        end_time=end_time,
                        duration=end_time - start_time
                    ))
            
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
        """청크 단위로 STT 처리"""
        from stt_engine import STTResult, STTProvider
        
        chunks = self._create_audio_chunks(audio_file, duration)
        model = self._get_model()
        
        all_texts = []
        processed_chunks = 0
        
        for i, chunk in enumerate(chunks):
            try:
                print(f"🎤 청크 {i+1}/{len(chunks)} 처리 중... ({chunk.start_time:.1f}s-{chunk.end_time:.1f}s)")
                
                # 메모리 체크
                current_memory = memory_manager.get_memory_usage()["rss"]
                if current_memory > 3500:  # 3.5GB 초과
                    print(f"⚠️ 메모리 부족으로 청크 처리 중단 ({i+1}/{len(chunks)})")
                    break
                
                # STT 처리
                segments, info = model.transcribe(
                    chunk.file_path,
                    language="ko",
                    condition_on_previous_text=False,
                    temperature=0.0,
                    compression_ratio_threshold=2.4,
                    no_speech_threshold=0.6
                )
                
                # 결과 수집
                chunk_texts = []
                for segment in segments:
                    chunk_texts.append(segment.text.strip())
                
                chunk_text = " ".join(chunk_texts).strip()
                if chunk_text:
                    all_texts.append(chunk_text)
                
                processed_chunks += 1
                
                # 청크 파일 즉시 삭제 (메모리 절약)
                if chunk.file_path != audio_file:  # 원본 파일이 아닌 경우만
                    try:
                        os.remove(chunk.file_path)
                    except:
                        pass
                
                # 가비지 컬렉션
                del segments, info, chunk_texts, chunk_text
                gc.collect()
                
                # 프로그레스 출력
                if (i + 1) % 3 == 0:
                    print(f"📊 진행률: {i+1}/{len(chunks)} 청크 완료")
                
            except Exception as e:
                print(f"❌ 청크 {i+1} 처리 실패: {e}")
                continue
        
        # 최종 결과
        final_text = " ".join(all_texts).strip()
        success = len(final_text) > 10 and processed_chunks > 0
        
        print(f"✅ 청크 STT 완료: {processed_chunks}/{len(chunks)} 청크, {len(final_text)}자")
        
        return STTResult(
            success=success,
            text=final_text,
            provider=STTProvider.LOCAL,
            duration_seconds=0,  # 나중에 설정됨
            chunks_processed=processed_chunks,
            confidence=processed_chunks / len(chunks) if chunks else 0
        )
    
    def _transcribe_single(self, audio_file: str) -> 'STTResult':
        """단일 파일 STT 처리"""
        from stt_engine import STTResult, STTProvider
        
        try:
            model = self._get_model()
            
            print("🎤 단일 파일 STT 처리 중...")
            
            segments, info = model.transcribe(
                audio_file,
                language="ko",
                condition_on_previous_text=False,
                temperature=0.0,
                compression_ratio_threshold=2.4,
                no_speech_threshold=0.6
            )
            
            # 결과 수집
            all_texts = []
            for segment in segments:
                all_texts.append(segment.text.strip())
            
            final_text = " ".join(all_texts).strip()
            success = len(final_text) > 10
            
            print(f"✅ 단일 STT 완료: {len(final_text)}자")
            
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
        """임시 파일 정리"""
        if self._temp_dir and os.path.exists(self._temp_dir):
            try:
                shutil.rmtree(self._temp_dir, ignore_errors=True)
                print("🗑️ 임시 파일 정리 완료")
            except:
                pass
            finally:
                self._temp_dir = None
    
    def cleanup(self):
        """리소스 정리"""
        if self._model:
            print("🗑️ Whisper 모델 해제 중...")
            del self._model
            self._model = None
        
        self._cleanup_temp_files()
        memory_manager.force_cleanup(aggressive=True)