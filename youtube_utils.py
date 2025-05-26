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


def get_videos_from_channel(channel_id, published_after=None):
    """
    채널 ID를 기반으로 영상 목록 조회
    published_after: ISO 8601 포맷 (예: '2024-05-01T00:00:00Z')
    """
    videos = []
    request = youtube.search().list(
        part="snippet",
        channelId=channel_id,
        maxResults=50,
        order="date",
        type="video",
        publishedAfter=published_after if published_after else None
    )
    response = request.execute()

    for item in response["items"]:
        video_info = {
            "video_id": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "published_at": item["snippet"]["publishedAt"],
            "thumbnail_url": item["snippet"]["thumbnails"]["default"]["url"]
        }
        videos.append(video_info)
    return videos
