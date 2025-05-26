import google.generativeai as genai
import os
from dotenv import load_dotenv
from typing import Optional, Dict
import json

# .env 로드
load_dotenv()

# Gemini API 키 설정
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)

# Gemini 2.0 Flash 모델 사용
model = genai.GenerativeModel('gemini-2.0-flash-exp')


def summarize_transcript(transcript: str, video_title: str, channel_name: str) -> Optional[Dict]:
    """
    자막을 요약하여 구조화된 데이터를 반환합니다.
    """
    if not transcript or len(transcript.strip()) < 100:
        return None
    
    # 투자 관련 요약 프롬프트
    prompt = f"""
다음은 '{channel_name}' 채널의 '{video_title}' 영상 자막입니다.

투자 분석 관점에서 다음 형식으로 요약해주세요:

## 📊 핵심 요약 (2-3문장)
[가장 중요한 투자 정보나 인사이트를 간결하게]

## 🎯 주요 포인트
- [핵심 논점 1]
- [핵심 논점 2] 
- [핵심 논점 3]

## 💡 투자 인사이트
[투자 결정에 도움이 될 만한 구체적인 정보나 전망]

## 🏷️ 키워드
[관련 키워드들을 쉼표로 구분: 예시 - 삼성전자, 반도체, 실적, 전망]

## ⚠️ 리스크 요인
[언급된 위험 요소나 주의사항]

## 📈 감성 분석
[긍정적/중립적/부정적 중 하나와 간단한 이유]

---
자막 내용:
{transcript}
"""

    try:
        response = model.generate_content(prompt)
        summary_text = response.text
        
        # 결과를 구조화하여 반환
        result = {
            "video_title": video_title,
            "channel_name": channel_name,
            "summary_text": summary_text,
            "original_transcript": transcript,
            "keywords": extract_keywords_from_summary(summary_text),
            "sentiment": extract_sentiment_from_summary(summary_text)
        }
        
        return result
        
    except Exception as e:
        print(f"Gemini API 요약 실패: {e}")
        return None


def extract_keywords_from_summary(summary_text: str) -> list:
    """
    요약문에서 키워드 섹션을 추출합니다.
    """
    try:
        # 🏷️ 키워드 섹션 찾기
        lines = summary_text.split('\n')
        keywords_section = False
        keywords_text = ""
        
        for line in lines:
            if '🏷️ 키워드' in line:
                keywords_section = True
                continue
            elif keywords_section and line.startswith('## '):
                break
            elif keywords_section and line.strip():
                keywords_text += line.strip() + " "
        
        # 키워드를 쉼표로 분리하고 정리
        if keywords_text:
            keywords = [kw.strip() for kw in keywords_text.split(',') if kw.strip()]
            return keywords[:10]  # 최대 10개
        
        return []
        
    except Exception as e:
        print(f"키워드 추출 실패: {e}")
        return []


def extract_sentiment_from_summary(summary_text: str) -> str:
    """
    요약문에서 감성 분석 결과를 추출합니다.
    """
    try:
        # 📈 감성 분석 섹션 찾기
        lines = summary_text.split('\n')
        
        for line in lines:
            if '📈 감성 분석' in line:
                continue
            elif line.strip() and ('긍정' in line or '부정' in line or '중립' in line):
                if '긍정' in line:
                    return '긍정적'
                elif '부정' in line:
                    return '부정적'
                else:
                    return '중립적'
        
        return '중립적'  # 기본값
        
    except Exception as e:
        print(f"감성 분석 추출 실패: {e}")
        return '중립적'


def generate_weekly_report(summaries: list) -> str:
    """
    주간 리포트를 생성합니다.
    """
    if not summaries:
        return "분석할 데이터가 없습니다."
    
    # 키워드 빈도 분석
    all_keywords = []
    for summary in summaries:
        all_keywords.extend(summary.get('keywords', []))
    
    keyword_count = {}
    for keyword in all_keywords:
        keyword_count[keyword] = keyword_count.get(keyword, 0) + 1
    
    # 상위 키워드 추출
    top_keywords = sorted(keyword_count.items(), key=lambda x: x[1], reverse=True)[:10]
    
    # 감성 분석 통계
    sentiment_count = {'긍정적': 0, '중립적': 0, '부정적': 0}
    for summary in summaries:
        sentiment = summary.get('sentiment', '중립적')
        sentiment_count[sentiment] = sentiment_count.get(sentiment, 0) + 1
    
    prompt = f"""
다음 데이터를 바탕으로 주간 투자 동향 리포트를 작성해주세요:

분석 영상 수: {len(summaries)}개
상위 키워드: {dict(top_keywords)}
감성 분포: {sentiment_count}

## 📊 주간 투자 동향 요약

## 🔥 핫 키워드 TOP 5

## 📈 시장 감성 분석

## 💡 주요 인사이트

## ⚠️ 주의 포인트

리포트 형식으로 작성해주세요.
"""

    try:
        response = model.generate_content(prompt)
        return response.text
        
    except Exception as e:
        print(f"주간 리포트 생성 실패: {e}")
        return "리포트 생성 중 오류가 발생했습니다."