# safe_stt_engine.py - 비용 안전장치 포함 STT 엔진
import os
import tempfile
import gc
import time
import json
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timedelta

# 로컬 모듈
from memory_manager import memory_manager, memory_monitor_decorator

class STTProvider(Enum):
    LOCAL = "local"
    GOOGLE = "google" 
    OPENAI = "openai"

@dataclass
class CostInfo:
    """비용 정보 클래스"""
    provider: STTProvider
    cost_per_minute: float
    free_tier_minutes: int = 0  # 월간 무료 할당량
    file_size_limit_mb: int = 0  # 파일 크기 제한
    
    @classmethod
    def get_cost_info(cls, provider: STTProvider) -> 'CostInfo':
        cost_map = {
            STTProvider.LOCAL: cls(provider, 0.0, 0, 0),  # 완전 무료
            STTProvider.GOOGLE: cls(provider, 0.006, 60, 1000),  # $0.006/분, 60분 무료, 1GB 제한
            STTProvider.OPENAI: cls(provider, 0.006, 0, 25)  # $0.006/분, 무료 없음, 25MB 제한
        }
        return cost_map[provider]

@dataclass
class CostTracker:
    """비용 추적 클래스"""
    session_cost: float = 0.0
    session_minutes: float = 0.0
    monthly_cost: float = 0.0
    monthly_minutes: float = 0.0
    last_reset: str = ""
    
    def add_usage(self, minutes: float, cost: float):
        """사용량 추가"""
        self.session_cost += cost
        self.session_minutes += minutes
        self.monthly_cost += cost
        self.monthly_minutes += minutes
    
    def reset_session(self):
        """세션 초기화"""
        self.session_cost = 0.0
        self.session_minutes = 0.0
    
    def reset_monthly(self):
        """월간 초기화"""
        self.monthly_cost = 0.0
        self.monthly_minutes = 0.0
        self.last_reset = datetime.now().strftime("%Y-%m")
    
    def should_reset_monthly(self) -> bool:
        """월간 리셋 필요 여부"""
        current_month = datetime.now().strftime("%Y-%m")
        return self.last_reset != current_month

@dataclass
class SafetyLimits:
    """안전 한도 설정"""
    daily_cost_limit: float = 1.0      # 일일 $1 한도
    monthly_cost_limit: float = 10.0   # 월간 $10 한도
    session_cost_limit: float = 2.0    # 세션 $2 한도
    single_video_limit_minutes: int = 120  # 단일 영상 2시간 한도
    require_confirmation_above: float = 0.5  # $0.5 이상시 확인 요구

@dataclass
class STTConfig:
    """STT 설정 클래스 (안전장치 포함)"""
    primary_provider: STTProvider = STTProvider.LOCAL
    fallback_provider: Optional[STTProvider] = None  # 기본값 None (안전)
    max_duration_seconds: int = 3600
    chunk_duration_seconds: int = 600
    whisper_model_size: str = "base"
    enable_chunking: bool = True
    auto_fallback: bool = False  # 기본값 False (안전)
    safety_limits: SafetyLimits = SafetyLimits()
    cost_confirmation_required: bool = True  # 비용 확인 필수

@dataclass
class STTResult:
    """STT 결과 클래스"""
    success: bool
    text: str
    provider: STTProvider
    duration_seconds: float
    confidence: Optional[float] = None
    error_message: Optional[str] = None
    chunks_processed: int = 0
    cost_incurred: float = 0.0  # 발생한 비용
    processing_minutes: float = 0.0  # 처리된 분수

class SafeSTTEngine:
    """비용 안전장치 포함 STT 엔진"""
    
    def __init__(self, config: STTConfig = None):
        self.config = config or STTConfig()
        self._local_stt = None
        self._cloud_stt = None
        self.cost_tracker = self._load_cost_tracker()
        
        # 월간 리셋 체크
        if self.cost_tracker.should_reset_monthly():
            self.cost_tracker.reset_monthly()
            self._save_cost_tracker()
    
    def _load_cost_tracker(self) -> CostTracker:
        """비용 추적 데이터 로드"""
        try:
            tracker_file = "cost_tracker.json"
            if os.path.exists(tracker_file):
                with open(tracker_file, 'r') as f:
                    data = json.load(f)
                    return CostTracker(**data)
        except:
            pass
        return CostTracker()
    
    def _save_cost_tracker(self):
        """비용 추적 데이터 저장"""
        try:
            tracker_file = "cost_tracker.json"
            with open(tracker_file, 'w') as f:
                json.dump(self.cost_tracker.__dict__, f)
        except Exception as e:
            print(f"비용 추적 데이터 저장 실패: {e}")
    
    def estimate_cost(self, video_duration_minutes: float, provider: STTProvider) -> Dict:
        """비용 추정"""
        cost_info = CostInfo.get_cost_info(provider)
        
        if provider == STTProvider.LOCAL:
            return {
                "cost": 0.0,
                "free_tier_remaining": 0,
                "will_exceed_free": False,
                "estimated_total": 0.0
            }
        
        # Google Cloud 무료 할당량 계산
        free_remaining = 0
        if provider == STTProvider.GOOGLE:
            used_this_month = self.cost_tracker.monthly_minutes
            free_remaining = max(0, cost_info.free_tier_minutes - used_this_month)
        
        # 비용 계산
        billable_minutes = max(0, video_duration_minutes - free_remaining)
        cost = billable_minutes * cost_info.cost_per_minute
        
        will_exceed_free = video_duration_minutes > free_remaining
        estimated_total = self.cost_tracker.session_cost + cost
        
        return {
            "cost": cost,
            "free_tier_remaining": free_remaining,
            "will_exceed_free": will_exceed_free,
            "estimated_total": estimated_total,
            "billable_minutes": billable_minutes
        }
    
    def check_safety_limits(self, video_duration_minutes: float, provider: STTProvider) -> Dict:
        """안전 한도 체크"""
        cost_estimate = self.estimate_cost(video_duration_minutes, provider)
        limits = self.config.safety_limits
        
        warnings = []
        blocks = []
        
        # 단일 영상 길이 체크
        if video_duration_minutes > limits.single_video_limit_minutes:
            blocks.append(f"영상이 너무 깁니다 ({video_duration_minutes:.1f}분 > {limits.single_video_limit_minutes}분)")
        
        # 세션 비용 한도 체크
        if cost_estimate["estimated_total"] > limits.session_cost_limit:
            blocks.append(f"세션 비용 한도 초과 (${cost_estimate['estimated_total']:.2f} > ${limits.session_cost_limit})")
        
        # 월간 비용 한도 체크 (예상)
        monthly_projection = self.cost_tracker.monthly_cost + cost_estimate["cost"]
        if monthly_projection > limits.monthly_cost_limit:
            blocks.append(f"월간 비용 한도 초과 예상 (${monthly_projection:.2f} > ${limits.monthly_cost_limit})")
        
        # 확인 필요 한도
        if cost_estimate["cost"] > limits.require_confirmation_above:
            warnings.append(f"비용 확인 필요 (${cost_estimate['cost']:.2f})")
        
        return {
            "safe": len(blocks) == 0,
            "warnings": warnings,
            "blocks": blocks,
            "cost_estimate": cost_estimate
        }
    
    def get_user_confirmation(self, safety_check: Dict, provider: STTProvider) -> bool:
        """사용자 확인 (Streamlit에서 구현되어야 함)"""
        # 이 함수는 실제로 Streamlit UI에서 구현됨
        # 여기서는 기본적으로 안전하지 않으면 False 반환
        return safety_check["safe"]
    
    @memory_monitor_decorator
    def transcribe_video(self, video_url: str, user_confirmation_callback=None) -> STTResult:
        """안전한 영상 STT 처리"""
        print(f"🎤 안전한 STT 처리 시작: {video_url}")
        
        # 메모리 체크
        if memory_manager.check_memory_pressure(threshold_mb=2000):
            return STTResult(
                success=False,
                text="",
                provider=self.config.primary_provider,
                duration_seconds=0,
                error_message="메모리 부족으로 STT 처리 불가"
            )
        
        # 영상 길이 추정 (정확하지 않을 수 있음)
        estimated_duration = self._estimate_video_duration(video_url)
        
        # 1차: Primary provider 안전성 체크
        primary_safety = self.check_safety_limits(estimated_duration, self.config.primary_provider)
        
        if not primary_safety["safe"] and self.config.primary_provider != STTProvider.LOCAL:
            print(f"⚠️ Primary STT ({self.config.primary_provider.value}) 안전하지 않음: {primary_safety['blocks']}")
            
            # 로컬 STT로 폴백 (항상 안전)
            if self.config.fallback_provider == STTProvider.LOCAL or self.config.primary_provider != STTProvider.LOCAL:
                print("🔄 로컬 STT로 안전 폴백")
                return self._try_transcription(video_url, STTProvider.LOCAL)
            else:
                return STTResult(
                    success=False,
                    text="",
                    provider=self.config.primary_provider,
                    duration_seconds=0,
                    error_message=f"안전 한도 초과: {'; '.join(primary_safety['blocks'])}"
                )
        
        # 비용 확인이 필요한 경우
        if (self.config.cost_confirmation_required and 
            self.config.primary_provider != STTProvider.LOCAL and
            primary_safety["cost_estimate"]["cost"] > 0):
            
            if user_confirmation_callback:
                confirmed = user_confirmation_callback(primary_safety, self.config.primary_provider)
                if not confirmed:
                    print("❌ 사용자가 비용 발생을 거부함")
                    return STTResult(
                        success=False,
                        text="",
                        provider=self.config.primary_provider,
                        duration_seconds=0,
                        error_message="사용자가 비용 발생을 거부함"
                    )
            else:
                # 콜백이 없으면 로컬로 폴백
                print("🔄 비용 확인 불가로 로컬 STT 사용")
                return self._try_transcription(video_url, STTProvider.LOCAL)
        
        # Primary provider 시도
        result = self._try_transcription(video_url, self.config.primary_provider)
        
        # Fallback 시도 (안전한 경우에만)
        if (not result.success and 
            self.config.auto_fallback and 
            self.config.fallback_provider and
            self.config.fallback_provider != self.config.primary_provider):
            
            fallback_safety = self.check_safety_limits(estimated_duration, self.config.fallback_provider)
            
            if fallback_safety["safe"] or self.config.fallback_provider == STTProvider.LOCAL:
                print(f"🔄 안전한 Fallback STT 시도: {self.config.fallback_provider.value}")
                
                # 비용 확인 (fallback도 유료인 경우)
                if (self.config.fallback_provider != STTProvider.LOCAL and
                    fallback_safety["cost_estimate"]["cost"] > 0):
                    
                    if user_confirmation_callback:
                        confirmed = user_confirmation_callback(fallback_safety, self.config.fallback_provider)
                        if confirmed:
                            result = self._try_transcription(video_url, self.config.fallback_provider)
                    # 확인 불가시 fallback 건너뛰기
                else:
                    result = self._try_transcription(video_url, self.config.fallback_provider)
        
        # 비용 추적 업데이트
        if result.cost_incurred > 0:
            self.cost_tracker.add_usage(result.processing_minutes, result.cost_incurred)
            self._save_cost_tracker()
            print(f"💰 비용 발생: ${result.cost_incurred:.3f} ({result.processing_minutes:.1f}분)")
        
        return result
    
    def _estimate_video_duration(self, video_url: str) -> float:
        """영상 길이 추정 (분 단위)"""
        try:
            import yt_dlp
            
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
                duration_seconds = info.get('duration', 0)
                return duration_seconds / 60.0 if duration_seconds else 30.0  # 기본값 30분
                
        except Exception as e:
            print(f"영상 길이 추정 실패: {e}")
            return 30.0  # 안전한 기본값
    
    def _try_transcription(self, video_url: str, provider: STTProvider) -> STTResult:
        """특정 provider로 STT 시도 (비용 추적 포함)"""
        if not self.is_available(provider):
            return STTResult(
                success=False,
                text="",
                provider=provider,
                duration_seconds=0,
                error_message=f"{provider.value} STT 사용 불가"
            )
        
        try:
            start_time = time.time()
            
            if provider == STTProvider.LOCAL:
                result = self._transcribe_local(video_url)
            elif provider == STTProvider.GOOGLE:
                result = self._transcribe_google(video_url)
            elif provider == STTProvider.OPENAI:
                result = self._transcribe_openai(video_url)
            else:
                raise ValueError(f"지원하지 않는 provider: {provider}")
            
            duration = time.time() - start_time
            result.duration_seconds = duration
            result.provider = provider
            
            # 비용 계산 (성공한 경우에만)
            if result.success and provider != STTProvider.LOCAL:
                cost_info = CostInfo.get_cost_info(provider)
                
                # 실제 처리된 시간을 기준으로 비용 계산
                actual_minutes = result.processing_minutes or (duration / 60.0)
                
                # Google Cloud 무료 할당량 적용
                if provider == STTProvider.GOOGLE:
                    free_remaining = max(0, 60 - self.cost_tracker.monthly_minutes)
                    billable_minutes = max(0, actual_minutes - free_remaining)
                else:
                    billable_minutes = actual_minutes
                
                result.cost_incurred = billable_minutes * cost_info.cost_per_minute
                result.processing_minutes = actual_minutes
            
            return result
            
        except Exception as e:
            print(f"❌ {provider.value} STT 실패: {e}")
            return STTResult(
                success=False,
                text="",
                provider=provider,
                duration_seconds=time.time() - start_time,
                error_message=str(e)
            )
    
    def _transcribe_local(self, video_url: str) -> STTResult:
        """로컬 faster-whisper STT"""
        from local_stt import LocalSTT
        
        if self._local_stt is None:
            self._local_stt = LocalSTT(
                model_size=self.config.whisper_model_size,
                enable_chunking=self.config.enable_chunking,
                chunk_duration=self.config.chunk_duration_seconds
            )
        
        return self._local_stt.transcribe(video_url)
    
    def _transcribe_google(self, video_url: str) -> STTResult:
        """Google Cloud STT"""
        from cloud_stt import GoogleSTT
        
        if self._cloud_stt is None:
            self._cloud_stt = GoogleSTT()
        
        return self._cloud_stt.transcribe(video_url)
    
    def _transcribe_openai(self, video_url: str) -> STTResult:
        """OpenAI Whisper API STT"""
        from cloud_stt import OpenAISTT
        
        if self._cloud_stt is None:
            self._cloud_stt = OpenAISTT()
        
        return self._cloud_stt.transcribe(video_url)
    
    def is_available(self, provider: STTProvider) -> bool:
        """STT 제공자 사용 가능 여부 확인"""
        if provider == STTProvider.LOCAL:
            return self._check_local_stt_availability()
        elif provider == STTProvider.GOOGLE:
            return self._check_google_stt_availability()
        elif provider == STTProvider.OPENAI:
            return self._check_openai_stt_availability()
        return False
    
    def _check_local_stt_availability(self) -> bool:
        """로컬 STT 사용 가능 여부"""
        try:
            import faster_whisper
            return True
        except ImportError:
            return False
    
    def _check_google_stt_availability(self) -> bool:
        """Google STT 사용 가능 여부"""
        try:
            from google.cloud import speech
            return bool(os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))
        except ImportError:
            return False
    
    def _check_openai_stt_availability(self) -> bool:
        """OpenAI STT 사용 가능 여부"""
        try:
            import openai
            return bool(os.getenv("OPENAI_API_KEY"))
        except ImportError:
            return False
    
    def get_cost_summary(self) -> Dict:
        """비용 요약 정보"""
        return {
            "session": {
                "cost": self.cost_tracker.session_cost,
                "minutes": self.cost_tracker.session_minutes
            },
            "monthly": {
                "cost": self.cost_tracker.monthly_cost,
                "minutes": self.cost_tracker.monthly_minutes,
                "google_free_remaining": max(0, 60 - self.cost_tracker.monthly_minutes)
            },
            "limits": {
                "daily_limit": self.config.safety_limits.daily_cost_limit,
                "monthly_limit": self.config.safety_limits.monthly_cost_limit,
                "session_limit": self.config.safety_limits.session_cost_limit
            }
        }
    
    def cleanup(self):
        """리소스 정리"""
        if self._local_stt:
            self._local_stt.cleanup()
            self._local_stt = None
        
        if self._cloud_stt:
            self._cloud_stt.cleanup()
            self._cloud_stt = None
        
        memory_manager.force_cleanup(aggressive=True)
    
    def get_status(self) -> Dict:
        """STT 엔진 상태 정보"""
        return {
            "providers": {
                "local": self.is_available(STTProvider.LOCAL),
                "google": self.is_available(STTProvider.GOOGLE),
                "openai": self.is_available(STTProvider.OPENAI)
            },
            "config": {
                "primary": self.config.primary_provider.value,
                "fallback": self.config.fallback_provider.value if self.config.fallback_provider else None,
                "auto_fallback": self.config.auto_fallback,
                "cost_confirmation": self.config.cost_confirmation_required,
                "max_duration": self.config.max_duration_seconds,
                "model_size": self.config.whisper_model_size
            },
            "costs": self.get_cost_summary(),
            "memory": memory_manager.get_memory_usage()
        }

# 전역 STT 엔진 인스턴스
_safe_stt_engine = None

def get_safe_stt_engine(config: STTConfig = None) -> SafeSTTEngine:
    """안전한 STT 엔진 싱글톤 인스턴스"""
    global _safe_stt_engine
    
    if _safe_stt_engine is None:
        _safe_stt_engine = SafeSTTEngine(config)
    
    return _safe_stt_engine

def cleanup_safe_stt_engine():
    """안전한 STT 엔진 정리"""
    global _safe_stt_engine
    
    if _safe_stt_engine:
        _safe_stt_engine.cleanup()
        _safe_stt_engine = None

def reset_session_costs():
    """세션 비용 초기화"""
    global _safe_stt_engine
    
    if _safe_stt_engine:
        _safe_stt_engine.cost_tracker.reset_session()
        _safe_stt_engine._save_cost_tracker()

# 프로그램 종료시 자동 정리
import atexit
atexit.register(cleanup_safe_stt_engine)