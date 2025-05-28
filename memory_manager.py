# memory_manager.py - 메모리 관리 및 모니터링 유틸리티

import gc
import psutil
import os
import threading
import time
from typing import Optional, Dict, Any
import streamlit as st

class MemoryManager:
    """메모리 사용량 모니터링 및 정리 관리"""
    
    def __init__(self):
        self.process = psutil.Process()
        self._monitoring = False
        self._monitor_thread = None
        
    def get_memory_usage(self) -> Dict[str, float]:
        """현재 메모리 사용량 반환 (MB 단위)"""
        memory_info = self.process.memory_info()
        return {
            "rss": memory_info.rss / 1024 / 1024,  # 실제 물리 메모리
            "vms": memory_info.vms / 1024 / 1024,  # 가상 메모리
            "percent": self.process.memory_percent()
        }
    
    def check_memory_pressure(self, threshold_mb: float = 3000) -> bool:
        """메모리 압박 상황 체크"""
        current_memory = self.get_memory_usage()["rss"]
        return current_memory > threshold_mb
    
    def force_cleanup(self, aggressive: bool = False):
        """강제 메모리 정리"""
        # Python 가비지 컬렉션 실행
        collected = gc.collect()
        
        if aggressive:
            # 더 적극적인 정리
            for i in range(3):
                gc.collect()
                time.sleep(0.1)
        
        return collected
    
    def cleanup_session_state(self, max_items: int = 50):
        """Streamlit 세션 상태 정리"""
        cleanup_keys = ["video_list", "search_results"]
        
        for key in cleanup_keys:
            if key in st.session_state:
                items = st.session_state[key]
                if isinstance(items, list) and len(items) > max_items:
                    # 최근 항목만 유지
                    st.session_state[key] = items[-max_items:]
                    
        # 선택된 비디오 리스트도 정리
        if "selected_videos" in st.session_state:
            selected = st.session_state["selected_videos"]
            if isinstance(selected, list) and len(selected) > 20:
                st.session_state["selected_videos"] = selected[-20:]
    
    def start_monitoring(self, interval: float = 5.0):
        """백그라운드 메모리 모니터링 시작"""
        if self._monitoring:
            return
            
        self._monitoring = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, 
            args=(interval,), 
            daemon=True
        )
        self._monitor_thread.start()
    
    def stop_monitoring(self):
        """메모리 모니터링 중지"""
        self._monitoring = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=1.0)
    
    def _monitor_loop(self, interval: float):
        """모니터링 루프 (백그라운드)"""
        while self._monitoring:
            try:
                if self.check_memory_pressure():
                    print(f"⚠️ 메모리 압박 감지: {self.get_memory_usage()['rss']:.1f}MB")
                    self.force_cleanup()
                
                time.sleep(interval)
            except Exception as e:
                print(f"메모리 모니터링 오류: {e}")
                break

# 전역 메모리 매니저 인스턴스
memory_manager = MemoryManager()


class WhisperModelManager:
    """faster-whisper 모델 싱글톤 관리"""
    
    _instance = None
    _model = None
    _model_size = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def get_model(self, model_size: str = "base"):
        """Whisper 모델 가져오기 (필요시 로딩)"""
        with self._lock:
            # 다른 크기 모델 요청시 기존 모델 해제
            if self._model is not None and self._model_size != model_size:
                self.clear_model()
            
            # 모델이 없으면 로딩
            if self._model is None:
                try:
                    from faster_whisper import WhisperModel
                    print(f"🤖 Whisper 모델 로딩 중... ({model_size})")
                    
                    # 메모리 사용량 체크
                    memory_before = memory_manager.get_memory_usage()["rss"]
                    
                    self._model = WhisperModel(
                        model_size, 
                        device="cpu", 
                        compute_type="int8"  # 메모리 절약
                    )
                    self._model_size = model_size
                    
                    memory_after = memory_manager.get_memory_usage()["rss"]
                    print(f"✅ 모델 로딩 완료 (+{memory_after - memory_before:.1f}MB)")
                    
                except ImportError:
                    print("❌ faster-whisper를 사용할 수 없습니다")
                    return None
                except Exception as e:
                    print(f"❌ 모델 로딩 실패: {e}")
                    return None
            
            return self._model
    
    def clear_model(self):
        """모델 메모리에서 해제"""
        with self._lock:
            if self._model is not None:
                print("🗑️ Whisper 모델 메모리 해제 중...")
                del self._model
                self._model = None
                self._model_size = None
                
                # 강제 가비지 컬렉션
                memory_manager.force_cleanup(aggressive=True)
                print("✅ 모델 해제 완료")
    
    def get_model_info(self) -> Optional[Dict[str, Any]]:
        """현재 로딩된 모델 정보"""
        if self._model is None:
            return None
        
        return {
            "size": self._model_size,
            "device": "cpu",
            "compute_type": "int8"
        }
    
    def is_loaded(self) -> bool:
        """모델 로딩 여부 체크"""
        return self._model is not None

# 전역 Whisper 모델 매니저 인스턴스
whisper_manager = WhisperModelManager()


def memory_monitor_decorator(func):
    """함수 실행 전후 메모리 사용량 모니터링 데코레이터"""
    def wrapper(*args, **kwargs):
        # 실행 전 메모리 체크
        memory_before = memory_manager.get_memory_usage()
        print(f"📊 {func.__name__} 시작 - 메모리: {memory_before['rss']:.1f}MB")
        
        try:
            result = func(*args, **kwargs)
            return result
        finally:
            # 실행 후 메모리 체크
            memory_after = memory_manager.get_memory_usage()
            memory_diff = memory_after['rss'] - memory_before['rss']
            
            print(f"📊 {func.__name__} 완료 - 메모리: {memory_after['rss']:.1f}MB ({memory_diff:+.1f}MB)")
            
            # 메모리 증가량이 클 경우 정리
            if memory_diff > 500:  # 500MB 이상 증가
                print("🗑️ 대용량 메모리 증가 감지, 정리 실행...")
                memory_manager.force_cleanup()
    
    return wrapper


def display_memory_info():
    """Streamlit에서 메모리 정보 표시"""
    memory_info = memory_manager.get_memory_usage()
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(
            "물리 메모리", 
            f"{memory_info['rss']:.0f}MB",
            delta=None
        )
    with col2:
        st.metric(
            "가상 메모리", 
            f"{memory_info['vms']:.0f}MB",
            delta=None
        )
    with col3:
        color = "🟢" if memory_info['rss'] < 2000 else "🟡" if memory_info['rss'] < 3000 else "🔴"
        st.metric(
            "메모리 상태", 
            f"{color}",
            delta=f"{memory_info['percent']:.1f}%"
        )
    
    # 메모리 압박시 경고
    if memory_manager.check_memory_pressure():
        st.warning("⚠️ 메모리 사용량이 높습니다. 정리를 권장합니다.")
        if st.button("🗑️ 메모리 정리 실행"):
            with st.spinner("메모리 정리 중..."):
                collected = memory_manager.force_cleanup(aggressive=True)
                memory_manager.cleanup_session_state()
            st.success(f"✅ 정리 완료 ({collected}개 객체)")
            st.rerun()


def cleanup_on_exit():
    """프로그램 종료시 정리 작업"""
    print("🧹 프로그램 종료 - 정리 작업 시작...")
    
    # Whisper 모델 해제
    whisper_manager.clear_model()
    
    # 메모리 모니터링 중지
    memory_manager.stop_monitoring()
    
    # 최종 메모리 정리
    memory_manager.force_cleanup(aggressive=True)
    
    print("✅ 정리 작업 완료")

# 프로그램 종료시 자동 정리
import atexit
atexit.register(cleanup_on_exit)