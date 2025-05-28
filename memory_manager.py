# memory_manager.py - 통합 메모리 관리 및 모니터링 유틸리티
import gc
import psutil
import os
import threading
import time
from typing import Optional, Dict, Any, Callable
import tempfile
import shutil

# Streamlit import (선택적)
try:
    import streamlit as st
    STREAMLIT_AVAILABLE = True
except ImportError:
    STREAMLIT_AVAILABLE = False

class MemoryManager:
    """시스템 메모리 사용량 모니터링 및 정리 관리"""
    
    def __init__(self):
        self.process = psutil.Process()
        self._monitoring = False
        self._monitor_thread = None
        self._memory_alerts = []
        self._cleanup_callbacks = []
        
        print("🖥️ MemoryManager 초기화 완료")
        
    def get_memory_usage(self) -> Dict[str, float]:
        """현재 메모리 사용량 반환 (MB 단위)"""
        try:
            memory_info = self.process.memory_info()
            return {
                "rss": memory_info.rss / 1024 / 1024,  # 실제 물리 메모리
                "vms": memory_info.vms / 1024 / 1024,  # 가상 메모리
                "percent": self.process.memory_percent(),
                "available": psutil.virtual_memory().available / 1024 / 1024,
                "total": psutil.virtual_memory().total / 1024 / 1024
            }
        except Exception as e:
            print(f"메모리 정보 수집 실패: {e}")
            return {"rss": 0, "vms": 0, "percent": 0, "available": 0, "total": 0}
    
    def get_system_memory_info(self) -> Dict[str, Any]:
        """시스템 전체 메모리 정보"""
        try:
            vm = psutil.virtual_memory()
            return {
                "total_gb": vm.total / (1024**3),
                "available_gb": vm.available / (1024**3),
                "used_gb": vm.used / (1024**3),
                "percent": vm.percent,
                "free_gb": vm.free / (1024**3),
                "cached_gb": getattr(vm, 'cached', 0) / (1024**3),
                "buffers_gb": getattr(vm, 'buffers', 0) / (1024**3)
            }
        except Exception as e:
            print(f"시스템 메모리 정보 수집 실패: {e}")
            return {}
    
    def check_memory_pressure(self, threshold_mb: float = 3000) -> bool:
        """메모리 압박 상황 체크"""
        try:
            current_memory = self.get_memory_usage()["rss"]
            return current_memory > threshold_mb
        except:
            return False
    
    def add_cleanup_callback(self, callback: Callable):
        """정리 콜백 함수 등록"""
        self._cleanup_callbacks.append(callback)
    
    def force_cleanup(self, aggressive: bool = False) -> int:
        """강제 메모리 정리"""
        print("🗑️ 메모리 정리 시작...")
        memory_before = self.get_memory_usage()["rss"]
        
        # 등록된 콜백 함수들 실행
        for callback in self._cleanup_callbacks:
            try:
                callback()
            except Exception as e:
                print(f"콜백 정리 실패: {e}")
        
        # Python 가비지 컬렉션 실행
        collected = gc.collect()
        
        if aggressive:
            # 더 적극적인 정리
            for i in range(3):
                collected += gc.collect()
                time.sleep(0.1)
        
        memory_after = self.get_memory_usage()["rss"]
        freed_mb = memory_before - memory_after
        
        print(f"🗑️ 메모리 정리 완료: {freed_mb:.1f}MB 해제, {collected}개 객체 수집")
        return collected
    
    def cleanup_session_state(self, max_items: int = 50):
        """Streamlit 세션 상태 정리"""
        if not STREAMLIT_AVAILABLE:
            return
        
        try:
            cleanup_keys = ["video_list", "search_results", "search_results_data", "processing_logs"]
            
            for key in cleanup_keys:
                if key in st.session_state:
                    items = st.session_state[key]
                    if isinstance(items, list) and len(items) > max_items:
                        # 최근 항목만 유지
                        st.session_state[key] = items[-max_items:]
                        print(f"🗑️ {key} 정리: {len(items)} → {max_items}개")
                        
            # 선택된 비디오 리스트도 정리
            if "selected_videos" in st.session_state:
                selected = st.session_state["selected_videos"]
                if isinstance(selected, list) and len(selected) > 20:
                    st.session_state["selected_videos"] = selected[-20:]
                    print(f"🗑️ selected_videos 정리: {len(selected)} → 20개")
        except Exception as e:
            print(f"세션 상태 정리 실패: {e}")
    
    def start_monitoring(self, interval: float = 10.0, alert_threshold_mb: float = 3000):
        """백그라운드 메모리 모니터링 시작"""
        if self._monitoring:
            return
            
        self._monitoring = True
        self._alert_threshold = alert_threshold_mb
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, 
            args=(interval,), 
            daemon=True
        )
        self._monitor_thread.start()
        print(f"🖥️ 메모리 모니터링 시작 (간격: {interval}초, 경고: {alert_threshold_mb}MB)")
    
    def stop_monitoring(self):
        """메모리 모니터링 중지"""
        self._monitoring = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=2.0)
        print("🖥️ 메모리 모니터링 중지")
    
    def _monitor_loop(self, interval: float):
        """모니터링 루프 (백그라운드)"""
        consecutive_alerts = 0
        
        while self._monitoring:
            try:
                memory_info = self.get_memory_usage()
                current_memory = memory_info["rss"]
                
                if current_memory > self._alert_threshold:
                    consecutive_alerts += 1
                    alert_msg = f"⚠️ 메모리 압박 감지: {current_memory:.1f}MB (연속 {consecutive_alerts}회)"
                    print(alert_msg)
                    self._memory_alerts.append({
                        "timestamp": time.time(),
                        "memory_mb": current_memory,
                        "message": alert_msg
                    })
                    
                    # 연속 3회 경고시 자동 정리
                    if consecutive_alerts >= 3:
                        print("🚨 자동 메모리 정리 실행")
                        self.force_cleanup(aggressive=True)
                        consecutive_alerts = 0
                else:
                    consecutive_alerts = 0
                
                # 알림 히스토리 정리 (최근 100개만 유지)
                if len(self._memory_alerts) > 100:
                    self._memory_alerts = self._memory_alerts[-50:]
                
                time.sleep(interval)
                
            except Exception as e:
                print(f"메모리 모니터링 오류: {e}")
                time.sleep(interval)
                break
    
    def get_memory_alerts(self, recent_minutes: int = 10) -> list:
        """최근 메모리 알림 목록"""
        cutoff_time = time.time() - (recent_minutes * 60)
        return [alert for alert in self._memory_alerts if alert["timestamp"] > cutoff_time]
    
    def clear_memory_alerts(self):
        """메모리 알림 히스토리 초기화"""
        self._memory_alerts.clear()
        print("🗑️ 메모리 알림 히스토리 초기화")

class WhisperModelManager:
    """faster-whisper 모델 통합 관리 (싱글톤 패턴)"""
    
    _instance = None
    _model = None
    _model_size = None
    _lock = threading.Lock()
    _load_time = None
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    print("🤖 WhisperModelManager 싱글톤 생성")
        return cls._instance
    
    def get_model(self, model_size: str = "base", force_reload: bool = False):
        """Whisper 모델 가져오기 (필요시 로딩)"""
        with self._lock:
            # 다른 크기 모델 요청시 기존 모델 해제
            if (self._model is not None and 
                (self._model_size != model_size or force_reload)):
                self.clear_model()
            
            # 모델이 없으면 로딩
            if self._model is None:
                try:
                    from faster_whisper import WhisperModel
                    print(f"🤖 Whisper 모델 로딩 중... ({model_size})")
                    
                    # 메모리 사용량 체크
                    memory_before = memory_manager.get_memory_usage()["rss"]
                    start_time = time.time()
                    
                    # 시스템 메모리에 따른 설정 최적화
                    system_memory = memory_manager.get_system_memory_info()
                    total_memory_gb = system_memory.get("total_gb", 8)
                    
                    if total_memory_gb < 4:
                        # 저사양 시스템
                        compute_type = "int8"
                        cpu_threads = 2
                    elif total_memory_gb < 8:
                        # 중간 사양 시스템  
                        compute_type = "int8"
                        cpu_threads = 4
                    else:
                        # 고사양 시스템
                        compute_type = "int8"  # 여전히 메모리 절약
                        cpu_threads = min(8, os.cpu_count() or 4)
                    
                    self._model = WhisperModel(
                        model_size, 
                        device="cpu", 
                        compute_type=compute_type,
                        cpu_threads=cpu_threads,
                        num_workers=1  # 메모리 절약
                    )
                    
                    self._model_size = model_size
                    self._load_time = time.time()
                    
                    memory_after = memory_manager.get_memory_usage()["rss"]
                    load_time = time.time() - start_time
                    
                    print(f"✅ 모델 로딩 완료: +{memory_after - memory_before:.1f}MB, {load_time:.1f}초")
                    
                    # 메모리 관리자에 정리 콜백 등록
                    memory_manager.add_cleanup_callback(self.clear_model)
                    
                except ImportError as e:
                    print(f"❌ faster-whisper를 사용할 수 없습니다: {e}")
                    print("설치 방법: pip install faster-whisper")
                    return None
                except Exception as e:
                    print(f"❌ 모델 로딩 실패: {e}")
                    return None
            
            return self._model
    
    def clear_model(self):
        """모델 메모리에서 해제"""
        with self._lock:
            if self._model is not None:
                print(f"🗑️ Whisper 모델 해제 중... ({self._model_size})")
                memory_before = memory_manager.get_memory_usage()["rss"]
                
                del self._model
                self._model = None
                self._model_size = None
                self._load_time = None
                
                # 강제 가비지 컬렉션
                gc.collect()
                
                memory_after = memory_manager.get_memory_usage()["rss"]
                freed_mb = memory_before - memory_after
                
                print(f"✅ 모델 해제 완료: {freed_mb:.1f}MB 해제")
    
    def get_model_info(self) -> Optional[Dict[str, Any]]:
        """현재 로딩된 모델 정보"""
        if self._model is None:
            return None
        
        uptime = time.time() - self._load_time if self._load_time else 0
        
        return {
            "size": self._model_size,
            "device": "cpu",
            "compute_type": "int8",
            "loaded_time": self._load_time,
            "uptime_seconds": uptime,
            "uptime_formatted": f"{int(uptime//60)}분 {int(uptime%60)}초"
        }
    
    def is_loaded(self) -> bool:
        """모델 로딩 여부 체크"""
        return self._model is not None
    
    def get_memory_usage(self) -> Dict[str, float]:
        """모델 관련 메모리 사용량 추정"""
        if not self.is_loaded():
            return {"estimated_mb": 0, "loaded": False}
        
        # 모델 크기별 대략적인 메모리 사용량 (MB)
        model_memory_estimates = {
            "tiny": 200,
            "base": 500,
            "small": 1000,
            "medium": 2000,
            "large": 4000,
            "large-v2": 4000,
            "large-v3": 4000
        }
        
        estimated_mb = model_memory_estimates.get(self._model_size, 500)
        
        return {
            "estimated_mb": estimated_mb,
            "loaded": True,
            "model_size": self._model_size
        }

class TempFileManager:
    """임시 파일 관리자"""
    
    def __init__(self):
        self._temp_dirs = set()
        self._temp_files = set()
        self._cleanup_callbacks = []
        
    def create_temp_dir(self, prefix: str = "sumvestor_") -> str:
        """임시 디렉토리 생성"""
        temp_dir = tempfile.mkdtemp(prefix=prefix)
        self._temp_dirs.add(temp_dir)
        print(f"📁 임시 디렉토리 생성: {temp_dir}")
        return temp_dir
    
    def create_temp_file(self, suffix: str = "", prefix: str = "sumvestor_") -> str:
        """임시 파일 생성"""
        fd, temp_file = tempfile.mkstemp(suffix=suffix, prefix=prefix)
        os.close(fd)  # 파일 핸들 닫기
        self._temp_files.add(temp_file)
        print(f"📄 임시 파일 생성: {temp_file}")
        return temp_file
    
    def cleanup_temp_dir(self, temp_dir: str):
        """특정 임시 디렉토리 정리"""
        if temp_dir in self._temp_dirs:
            try:
                if os.path.exists(temp_dir):
                    file_count = len(os.listdir(temp_dir))
                    total_size = sum(
                        os.path.getsize(os.path.join(temp_dir, f)) 
                        for f in os.listdir(temp_dir)
                        if os.path.isfile(os.path.join(temp_dir, f))
                    ) / 1024 / 1024
                    
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    self._temp_dirs.remove(temp_dir)
                    print(f"🗑️ 임시 디렉토리 정리: {file_count}개 파일, {total_size:.1f}MB")
            except Exception as e:
                print(f"임시 디렉토리 정리 실패: {e}")
    
    def cleanup_temp_file(self, temp_file: str):
        """특정 임시 파일 정리"""
        if temp_file in self._temp_files:
            try:
                if os.path.exists(temp_file):
                    file_size = os.path.getsize(temp_file) / 1024 / 1024
                    os.remove(temp_file)
                    self._temp_files.remove(temp_file)
                    print(f"🗑️ 임시 파일 정리: {file_size:.1f}MB")
            except Exception as e:
                print(f"임시 파일 정리 실패: {e}")
    
    def cleanup_all(self):
        """모든 임시 파일/디렉토리 정리"""
        print("🗑️ 모든 임시 파일 정리 시작...")
        
        # 임시 디렉토리 정리
        for temp_dir in list(self._temp_dirs):
            self.cleanup_temp_dir(temp_dir)
        
        # 임시 파일 정리
        for temp_file in list(self._temp_files):
            self.cleanup_temp_file(temp_file)
        
        print("✅ 모든 임시 파일 정리 완료")
    
    def get_temp_usage(self) -> Dict[str, Any]:
        """임시 파일 사용량 정보"""
        total_size = 0
        total_files = 0
        
        # 디렉토리 크기 계산
        for temp_dir in self._temp_dirs:
            if os.path.exists(temp_dir):
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        try:
                            file_path = os.path.join(root, file)
                            total_size += os.path.getsize(file_path)
                            total_files += 1
                        except:
                            pass
        
        # 파일 크기 계산
        for temp_file in self._temp_files:
            if os.path.exists(temp_file):
                try:
                    total_size += os.path.getsize(temp_file)
                    total_files += 1
                except:
                    pass
        
        return {
            "total_size_mb": total_size / 1024 / 1024,
            "total_files": total_files,
            "temp_dirs": len(self._temp_dirs),
            "temp_files": len(self._temp_files)
        }

# 전역 인스턴스들
memory_manager = MemoryManager()
whisper_manager = WhisperModelManager()
temp_file_manager = TempFileManager()

def memory_monitor_decorator(func):
    """함수 실행 전후 메모리 사용량 모니터링 데코레이터"""
    def wrapper(*args, **kwargs):
        # 실행 전 메모리 체크
        memory_before = memory_manager.get_memory_usage()
        func_name = func.__name__
        print(f"📊 {func_name} 시작 - 메모리: {memory_before['rss']:.1f}MB")
        
        try:
            result = func(*args, **kwargs)
            return result
        finally:
            # 실행 후 메모리 체크
            memory_after = memory_manager.get_memory_usage()
            memory_diff = memory_after['rss'] - memory_before['rss']
            
            print(f"📊 {func_name} 완료 - 메모리: {memory_after['rss']:.1f}MB ({memory_diff:+.1f}MB)")
            
            # 메모리 증가량이 클 경우 정리
            if memory_diff > 500:  # 500MB 이상 증가
                print("🗑️ 대용량 메모리 증가 감지, 정리 실행...")
                memory_manager.force_cleanup()
    
    return wrapper

def display_memory_info():
    """Streamlit에서 메모리 정보 표시"""
    if not STREAMLIT_AVAILABLE:
        return
    
    memory_info = memory_manager.get_memory_usage()
    system_info = memory_manager.get_system_memory_info()
    
    # 메인 메트릭
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(
            "프로세스 메모리", 
            f"{memory_info['rss']:.0f}MB",
            delta=None
        )
    with col2:
        st.metric(
            "시스템 메모리", 
            f"{system_info.get('used_gb', 0):.1f}GB",
            delta=f"{system_info.get('percent', 0):.1f}%"
        )
    with col3:
        # 메모리 상태 표시
        if memory_info['rss'] < 1500:
            color = "🟢"
            status = "양호"
        elif memory_info['rss'] < 2500:
            color = "🟡"
            status = "주의"
        else:
            color = "🔴"
            status = "위험"
        
        st.metric(
            "메모리 상태", 
            f"{color} {status}",
            delta=f"{memory_info['rss']:.0f}MB"
        )
    
    # Whisper 모델 정보
    if whisper_manager.is_loaded():
        model_info = whisper_manager.get_model_info()
        st.info(f"🤖 Whisper 모델: {model_info['size']} ({model_info['uptime_formatted']})")
    
    # 메모리 압박시 경고
    if memory_manager.check_memory_pressure():
        st.warning("⚠️ 메모리 사용량이 높습니다. 정리를 권장합니다.")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🗑️ 메모리 정리"):
                with st.spinner("메모리 정리 중..."):
                    collected = memory_manager.force_cleanup(aggressive=True)
                    memory_manager.cleanup_session_state()
                    temp_file_manager.cleanup_all()
                st.success(f"✅ 정리 완료 ({collected}개 객체)")
                st.rerun()
        
        with col2:
            if st.button("🤖 모델 해제"):
                with st.spinner("모델 해제 중..."):
                    whisper_manager.clear_model()
                st.success("✅ 모델 해제 완료")
                st.rerun()
    
    # 최근 메모리 알림 표시
    recent_alerts = memory_manager.get_memory_alerts(recent_minutes=5)
    if recent_alerts:
        with st.expander(f"⚠️ 최근 메모리 알림 ({len(recent_alerts)}개)"):
            for alert in recent_alerts[-5:]:  # 최근 5개만 표시
                st.write(f"• {alert['message']}")

def cleanup_on_exit():
    """프로그램 종료시 정리 작업"""
    print("🧹 프로그램 종료 - 정리 작업 시작...")
    
    # Whisper 모델 해제
    whisper_manager.clear_model()
    
    # 메모리 모니터링 중지
    memory_manager.stop_monitoring()
    
    # 임시 파일 정리
    temp_file_manager.cleanup_all()
    
    # 최종 메모리 정리
    memory_manager.force_cleanup(aggressive=True)
    
    print("✅ 정리 작업 완료")

def get_system_status() -> Dict[str, Any]:
    """시스템 전체 상태 정보"""
    memory_info = memory_manager.get_memory_usage()
    system_info = memory_manager.get_system_memory_info()
    temp_info = temp_file_manager.get_temp_usage()
    
    return {
        "memory": {
            "process_mb": memory_info["rss"],
            "system_used_gb": system_info.get("used_gb", 0),
            "system_percent": system_info.get("percent", 0),
            "available_gb": system_info.get("available_gb", 0),
            "pressure": memory_manager.check_memory_pressure()
        },
        "whisper_model": {
            "loaded": whisper_manager.is_loaded(),
            "info": whisper_manager.get_model_info()
        },
        "temp_files": temp_info,
        "alerts": len(memory_manager.get_memory_alerts(recent_minutes=10)),
        "timestamp": time.time()
    }

# 편의 함수들
def optimize_for_low_memory():
    """저메모리 환경 최적화"""
    print("🔧 저메모리 환경 최적화 중...")
    
    # 가비지 컬렉션 주기 단축
    gc.set_threshold(100, 5, 5)  # 기본값보다 짧게
    
    # 메모리 모니터링 간격 단축
    memory_manager.start_monitoring(interval=5.0, alert_threshold_mb=2000)
    
    # 자동 정리 활성화
    memory_manager.add_cleanup_callback(lambda: gc.collect())
    
    print("✅ 저메모리 최적화 완료")

def optimize_for_high_memory():
    """고메모리 환경 최적화"""
    print("🔧 고메모리 환경 최적화 중...")
    
    # 가비지 컬렉션 주기 늘리기
    gc.set_threshold(1000, 20, 20)  # 기본값보다 길게
    
    # 메모리 모니터링 간격 늘리기
    memory_manager.start_monitoring(interval=15.0, alert_threshold_mb=4000)
    
    print("✅ 고메모리 최적화 완료")

# 프로그램 종료시 자동 정리
import atexit
atexit.register(cleanup_on_exit)