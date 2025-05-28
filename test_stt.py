# test_stt.py - STT 시스템 테스트 스크립트
import os
import sys
import time
from typing import Dict, List

def check_dependencies() -> Dict[str, bool]:
    """의존성 라이브러리 설치 상태 확인"""
    dependencies = {
        "faster_whisper": False,
        "torch": False,
        "yt_dlp": False,
        "ffmpeg": False,
        "streamlit": False
    }
    
    # Python 패키지 확인
    try:
        import faster_whisper
        dependencies["faster_whisper"] = True
        print("✅ faster-whisper 설치됨")
    except ImportError:
        print("❌ faster-whisper 미설치")
    
    try:
        import torch
        dependencies["torch"] = True
        print(f"✅ torch 설치됨 (버전: {torch.__version__})")
    except ImportError:
        print("❌ torch 미설치")
    
    try:
        import yt_dlp
        dependencies["yt_dlp"] = True
        # yt-dlp 버전 확인을 더 안전하게 처리
        try:
            version = getattr(yt_dlp, '__version__', 'unknown')
            print(f"✅ yt-dlp 설치됨 (버전: {version})")
        except:
            print("✅ yt-dlp 설치됨")
    except ImportError:
        print("❌ yt-dlp 미설치")
    
    # ffmpeg 확인
    try:
        import subprocess
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True)
        if result.returncode == 0:
            dependencies["ffmpeg"] = True
            print("✅ ffmpeg 설치됨")
        else:
            print("❌ ffmpeg 실행 불가")
    except:
        print("❌ ffmpeg 미설치")
    
    try:
        import streamlit
        dependencies["streamlit"] = True
        print(f"✅ streamlit 설치됨 (버전: {streamlit.__version__})")
    except ImportError:
        print("❌ streamlit 미설치")
    
    return dependencies

def check_system_resources() -> Dict[str, any]:
    """시스템 리소스 확인"""
    import psutil
    
    # 메모리 정보
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('.')
    
    resources = {
        "total_memory_gb": memory.total / (1024**3),
        "available_memory_gb": memory.available / (1024**3),
        "memory_percent": memory.percent,
        "disk_free_gb": disk.free / (1024**3),
        "cpu_count": psutil.cpu_count()
    }
    
    print("\n🖥️ 시스템 리소스:")
    print(f"   총 메모리: {resources['total_memory_gb']:.1f}GB")
    print(f"   사용 가능 메모리: {resources['available_memory_gb']:.1f}GB")
    print(f"   메모리 사용률: {resources['memory_percent']:.1f}%")
    print(f"   디스크 여유공간: {resources['disk_free_gb']:.1f}GB")
    print(f"   CPU 코어: {resources['cpu_count']}개")
    
    # 권장사항
    if resources['total_memory_gb'] < 8:
        print("⚠️ 권장: 최소 8GB RAM 필요")
    
    if resources['available_memory_gb'] < 4:
        print("⚠️ 경고: 사용 가능 메모리 부족")
    
    if resources['disk_free_gb'] < 5:
        print("⚠️ 경고: 디스크 여유공간 부족")
    
    return resources

def test_whisper_model_loading():
    """Whisper 모델 로딩 테스트"""
    print("\n🤖 Whisper 모델 로딩 테스트:")
    
    models_to_test = ["tiny", "base", "small"]
    
    for model_size in models_to_test:
        try:
            print(f"   {model_size} 모델 테스트 중...")
            start_time = time.time()
            
            from faster_whisper import WhisperModel
            model = WhisperModel(
                model_size,
                device="cpu",
                compute_type="int8"
            )
            
            load_time = time.time() - start_time
            print(f"   ✅ {model_size} 모델 로딩 성공 ({load_time:.1f}초)")
            
            # 메모리 사용량 확인
            import psutil
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            print(f"      메모리 사용량: {memory_mb:.1f}MB")
            
            # 모델 해제
            del model
            import gc
            gc.collect()
            
        except Exception as e:
            print(f"   ❌ {model_size} 모델 로딩 실패: {e}")

def test_audio_extraction():
    """오디오 추출 테스트 (짧은 영상)"""
    print("\n🎵 오디오 추출 테스트:")
    
    # 테스트용 짧은 YouTube 영상 (공개 도메인)
    test_video_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"  # 예시 URL
    
    try:
        import tempfile
        import yt_dlp
        
        temp_dir = tempfile.mkdtemp(prefix="stt_test_")
        audio_output = os.path.join(temp_dir, "test_audio.wav")
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': audio_output.replace('.wav', '.%(ext)s'),
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'wav',
                'preferredquality': '16',
            }],
            'postprocessor_args': ['-ac', '1', '-ar', '16000'],
            'quiet': True,
            'no_warnings': True,
        }
        
        print(f"   테스트 영상에서 오디오 추출 중...")
        
        start_time = time.time()
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([test_video_url])
        
        extract_time = time.time() - start_time
        
        # 추출된 파일 확인
        extracted_file = None
        for file in os.listdir(temp_dir):
            if file.startswith('test_audio') and file.endswith('.wav'):
                extracted_file = os.path.join(temp_dir, file)
                break
        
        if extracted_file and os.path.exists(extracted_file):
            file_size_mb = os.path.getsize(extracted_file) / 1024 / 1024
            print(f"   ✅ 오디오 추출 성공 ({extract_time:.1f}초, {file_size_mb:.1f}MB)")
        else:
            print("   ❌ 오디오 파일을 찾을 수 없음")
        
        # 정리
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
        
    except Exception as e:
        print(f"   ❌ 오디오 추출 실패: {e}")

def test_stt_integration():
    """STT 통합 테스트"""
    print("\n🔧 STT 통합 테스트:")
    
    try:
        # 새로운 STT 엔진 import
        from stt_engine import STTEngine, STTConfig, STTProvider
        
        # 설정
        config = STTConfig(
            primary_provider=STTProvider.LOCAL,
            whisper_model_size="tiny",  # 테스트용 작은 모델
            enable_chunking=False,  # 테스트에서는 비활성화
            max_duration_seconds=300  # 5분 제한
        )
        
        # STT 엔진 생성
        stt_engine = STTEngine(config)
        
        # 상태 확인
        status = stt_engine.get_status()
        print(f"   STT 엔진 상태:")
        print(f"   - 로컬 STT: {'✅' if status['providers']['local'] else '❌'}")
        print(f"   - Google STT: {'✅' if status['providers']['google'] else '❌'}")
        print(f"   - OpenAI STT: {'✅' if status['providers']['openai'] else '❌'}")
        
        # 실제 테스트는 짧은 영상으로만
        print("   실제 STT 테스트는 main.py에서 수행하세요.")
        
    except Exception as e:
        print(f"   ❌ STT 통합 테스트 실패: {e}")

def install_missing_dependencies(missing: List[str]):
    """누락된 의존성 설치 가이드"""
    if not missing:
        return
    
    print(f"\n📦 누락된 의존성 설치 가이드:")
    
    install_commands = {
        "faster_whisper": "pip install faster-whisper",
        "torch": "pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu",
        "yt_dlp": "pip install yt-dlp",
        "ffmpeg": "시스템 패키지 매니저로 설치 (Windows: https://ffmpeg.org/download.html)",
        "streamlit": "pip install streamlit"
    }
    
    for dep in missing:
        if dep in install_commands:
            print(f"   {dep}: {install_commands[dep]}")

def main():
    """메인 테스트 실행"""
    print("🧪 STT 시스템 진단 및 테스트")
    print("=" * 50)
    
    # 1. 의존성 확인
    print("\n1️⃣ 의존성 확인:")
    dependencies = check_dependencies()
    missing = [dep for dep, installed in dependencies.items() if not installed]
    
    if missing:
        install_missing_dependencies(missing)
        print(f"\n❌ {len(missing)}개 의존성 누락. 설치 후 다시 실행하세요.")
        return False
    
    print("✅ 모든 의존성 설치됨")
    
    # 2. 시스템 리소스 확인
    print("\n2️⃣ 시스템 리소스 확인:")
    resources = check_system_resources()
    
    # 3. Whisper 모델 테스트
    if dependencies.get("faster_whisper"):
        test_whisper_model_loading()
    
    # 4. 오디오 추출 테스트
    if dependencies.get("yt_dlp") and dependencies.get("ffmpeg"):
        test_audio_extraction()
    
    # 5. STT 통합 테스트
    test_stt_integration()
    
    # 최종 판정
    print("\n" + "=" * 50)
    print("🎯 최종 진단 결과:")
    
    critical_deps = ["faster_whisper", "torch", "yt_dlp", "ffmpeg"]
    critical_missing = [dep for dep in critical_deps if dep in missing]
    
    if not critical_missing and resources['available_memory_gb'] >= 2:
        print("✅ STT 시스템 준비 완료!")
        print("   이제 main.py에서 실제 STT 기능을 테스트할 수 있습니다.")
        return True
    else:
        print("❌ STT 시스템 준비 미완료")
        if critical_missing:
            print(f"   누락 의존성: {', '.join(critical_missing)}")
        if resources['available_memory_gb'] < 2:
            print(f"   메모리 부족: {resources['available_memory_gb']:.1f}GB (최소 2GB 필요)")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)