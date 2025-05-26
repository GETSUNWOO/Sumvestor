from notion_client import Client
import os
from dotenv import load_dotenv
from datetime import datetime
from typing import Optional, Dict, List

# .env 로드
load_dotenv()

# Notion API 설정
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

notion = Client(auth=NOTION_TOKEN)


def create_database_if_not_exists():
    """
    Notion 데이터베이스를 생성합니다 (수동으로 생성 후 ID를 환경변수에 설정하는 것을 권장)
    """
    # 실제로는 Notion에서 수동으로 데이터베이스를 만들고 ID를 .env에 설정하는 것이 좋습니다.
    pass


def save_summary_to_notion(summary_data: Dict, video_id: str) -> bool:
    """
    요약 데이터를 Notion 데이터베이스에 저장합니다.
    """
    try:
        # Notion 페이지 속성 구성
        properties = {
            "제목": {
                "title": [
                    {
                        "text": {
                            "content": summary_data["video_title"]
                        }
                    }
                ]
            },
            "채널": {
                "rich_text": [
                    {
                        "text": {
                            "content": summary_data["channel_name"]
                        }
                    }
                ]
            },
            "Video ID": {
                "rich_text": [
                    {
                        "text": {
                            "content": video_id
                        }
                    }
                ]
            },
            "키워드": {
                "multi_select": [
                    {"name": keyword} for keyword in summary_data.get("keywords", [])[:5]  # 최대 5개
                ]
            },
            "감성": {
                "select": {
                    "name": summary_data.get("sentiment", "중립적")
                }
            },
            "요약 일시": {
                "date": {
                    "start": datetime.now().isoformat()
                }
            },
            "YouTube URL": {
                "url": f"https://www.youtube.com/watch?v={video_id}"
            }
        }
        
        # 페이지 내용 구성 (요약 텍스트)
        children = [
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {
                                "content": "📊 AI 요약"
                            }
                        }
                    ]
                }
            },
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {
                                "content": summary_data["summary_text"]
                            }
                        }
                    ]
                }
            },
            {
                "object": "block",
                "type": "divider",
                "divider": {}
            },
            {
                "object": "block",
                "type": "heading_3",
                "heading_3": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {
                                "content": "📝 원본 자막"
                            }
                        }
                    ]
                }
            },
            {
                "object": "block",
                "type": "toggle",
                "toggle": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {
                                "content": "자막 전문 보기"
                            }
                        }
                    ],
                    "children": [
                        {
                            "object": "block",
                            "type": "paragraph",
                            "paragraph": {
                                "rich_text": [
                                    {
                                        "type": "text",
                                        "text": {
                                            "content": summary_data.get("original_transcript", "")[:2000]  # Notion 제한으로 2000자까지
                                        }
                                    }
                                ]
                            }
                        }
                    ]
                }
            }
        ]
        
        # Notion 페이지 생성
        response = notion.pages.create(
            parent={"database_id": NOTION_DATABASE_ID},
            properties=properties,
            children=children
        )
        
        print(f"Notion에 저장 완료: {response['id']}")
        return True
        
    except Exception as e:
        print(f"Notion 저장 실패: {e}")
        return False


def search_summaries_by_keyword(keyword: str) -> List[Dict]:
    """
    키워드로 저장된 요약들을 검색합니다.
    """
    try:
        # Notion 데이터베이스에서 검색
        response = notion.databases.query(
            database_id=NOTION_DATABASE_ID,
            filter={
                "or": [
                    {
                        "property": "제목",
                        "title": {
                            "contains": keyword
                        }
                    },
                    {
                        "property": "키워드",
                        "multi_select": {
                            "contains": keyword
                        }
                    }
                ]
            },
            sorts=[
                {
                    "property": "요약 일시",
                    "direction": "descending"
                }
            ]
        )
        
        results = []
        for page in response["results"]:
            props = page["properties"]
            
            result = {
                "title": props["제목"]["title"][0]["text"]["content"] if props["제목"]["title"] else "",
                "channel": props["채널"]["rich_text"][0]["text"]["content"] if props["채널"]["rich_text"] else "",
                "video_id": props["Video ID"]["rich_text"][0]["text"]["content"] if props["Video ID"]["rich_text"] else "",
                "keywords": [tag["name"] for tag in props["키워드"]["multi_select"]],
                "sentiment": props["감성"]["select"]["name"] if props["감성"]["select"] else "",
                "created_time": props["요약 일시"]["date"]["start"] if props["요약 일시"]["date"] else "",
                "notion_url": page["url"]
            }
            results.append(result)
        
        return results
        
    except Exception as e:
        print(f"Notion 검색 실패: {e}")
        return []


def get_recent_summaries(days: int = 7) -> List[Dict]:
    """
    최근 N일간의 요약들을 가져옵니다.
    """
    try:
        from datetime import datetime, timedelta
        
        # N일 전 날짜 계산
        since_date = (datetime.now() - timedelta(days=days)).isoformat()
        
        response = notion.databases.query(
            database_id=NOTION_DATABASE_ID,
            filter={
                "property": "요약 일시",
                "date": {
                    "after": since_date
                }
            },
            sorts=[
                {
                    "property": "요약 일시",
                    "direction": "descending"
                }
            ]
        )
        
        results = []
        for page in response["results"]:
            props = page["properties"]
            
            result = {
                "title": props["제목"]["title"][0]["text"]["content"] if props["제목"]["title"] else "",
                "channel": props["채널"]["rich_text"][0]["text"]["content"] if props["채널"]["rich_text"] else "",
                "keywords": [tag["name"] for tag in props["키워드"]["multi_select"]],
                "sentiment": props["감성"]["select"]["name"] if props["감성"]["select"] else "",
                "created_time": props["요약 일시"]["date"]["start"] if props["요약 일시"]["date"] else "",
                "notion_url": page["url"]
            }
            results.append(result)
        
        return results
        
    except Exception as e:
        print(f"최근 요약 조회 실패: {e}")
        return []


def get_database_stats() -> Dict:
    """
    데이터베이스 통계를 가져옵니다.
    """
    try:
        response = notion.databases.query(
            database_id=NOTION_DATABASE_ID
        )
        
        total_count = len(response["results"])
        
        # 감성 분포 계산
        sentiment_count = {"긍정적": 0, "중립적": 0, "부정적": 0}
        channel_count = {}
        
        for page in response["results"]:
            props = page["properties"]
            
            # 감성 통계
            sentiment = props["감성"]["select"]["name"] if props["감성"]["select"] else "중립적"
            sentiment_count[sentiment] = sentiment_count.get(sentiment, 0) + 1
            
            # 채널 통계
            channel = props["채널"]["rich_text"][0]["text"]["content"] if props["채널"]["rich_text"] else "알 수 없음"
            channel_count[channel] = channel_count.get(channel, 0) + 1
        
        return {
            "total_summaries": total_count,
            "sentiment_distribution": sentiment_count,
            "top_channels": sorted(channel_count.items(), key=lambda x: x[1], reverse=True)[:5]
        }
        
    except Exception as e:
        print(f"통계 조회 실패: {e}")
        return {"total_summaries": 0, "sentiment_distribution": {}, "top_channels": []}