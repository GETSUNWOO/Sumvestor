from googleapiclient.discovery import build
from googleapiclient.discovery import Resource
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta

# .env 로드
load_dotenv()

# 환경 변수에서 API 키 가져오기
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

# YouTube API 클라이언트 생성
youtube: Resource = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)


def search_channel(query, max_results=5):
    """
    키워드로 유튜브 채널을 검색
    """
    request = youtube.search().list(
        q=query,
        type="channel",
        part="snippet",
        maxResults=max_results
    )
    response = request.execute()

    channels = []
    for item in response["items"]:
        channel_info = {
            "channel_title": item["snippet"]["title"],
            "channel_id": item["snippet"]["channelId"],
            "thumbnail_url": item["snippet"]["thumbnails"]["default"]["url"],
            "description": item["snippet"]["description"]
        }
        channels.append(channel_info)

    return channels


def get_videos_from_channel(channel_id, published_after=None, exclude_shorts=True):
    """
    채널 ID를 기반으로 영상 목록 조회
    published_after: ISO 8601 포맷 (예: '2024-05-01T00:00:00Z')
    exclude_shorts: 쇼츠 영상 제외 여부
    """
    videos = []
    next_page_token = None
    
    while True:
        request = youtube.search().list(
            part="snippet",
            channelId=channel_id,
            maxResults=50,
            order="date",
            type="video",
            publishedAfter=published_after if published_after else None,
            pageToken=next_page_token
        )
        response = request.execute()

        # 비디오 ID 목록 생성
        video_ids = [item["id"]["videoId"] for item in response["items"]]
        
        # 영상 세부 정보 가져오기 (duration 포함)
        if video_ids:
            details_request = youtube.videos().list(
                part="contentDetails,snippet",
                id=",".join(video_ids)
            )
            details_response = details_request.execute()
            
            # duration을 초 단위로 변환하는 함수
            def parse_duration(duration):
                """
                PT4M13S -> 253초 변환
                PT1H2M3S -> 3723초 변환
                """
                import re
                duration = duration.replace('PT', '')
                
                hours = re.search(r'(\d+)H', duration)
                minutes = re.search(r'(\d+)M', duration)
                seconds = re.search(r'(\d+)S', duration)
                
                total_seconds = 0
                if hours:
                    total_seconds += int(hours.group(1)) * 3600
                if minutes:
                    total_seconds += int(minutes.group(1)) * 60
                if seconds:
                    total_seconds += int(seconds.group(1))
                    
                return total_seconds
            
            for item in details_response["items"]:
                duration_seconds = parse_duration(item["contentDetails"]["duration"])
                
                # 쇼츠 필터링 (60초 이하는 쇼츠로 간주)
                if exclude_shorts and duration_seconds <= 60:
                    continue
                
                # 영상 정보 구성
                video_info = {
                    "video_id": item["id"],
                    "title": item["snippet"]["title"],
                    "published_at": item["snippet"]["publishedAt"],
                    "thumbnail_url": item["snippet"]["thumbnails"]["default"]["url"],
                    "duration_seconds": duration_seconds,
                    "duration_formatted": format_duration(duration_seconds)
                }
                videos.append(video_info)
        
        # 다음 페이지 확인
        next_page_token = response.get("nextPageToken")
        if not next_page_token or len(videos) >= 100:  # 최대 100개로 제한
            break
    
    return videos


def format_duration(seconds):
    """
    초를 MM:SS 또는 HH:MM:SS 포맷으로 변환
    """
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    else:
        return f"{minutes:02d}:{seconds:02d}"