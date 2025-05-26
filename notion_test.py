# notion_test.py - Notion 연결 테스트용 스크립트

from notion_client import Client
import os
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

# 환경변수 확인
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

print("🔍 환경변수 확인:")
print(f"NOTION_TOKEN: {'✅ 설정됨' if NOTION_TOKEN else '❌ 없음'}")
print(f"NOTION_DATABASE_ID: {'✅ 설정됨' if NOTION_DATABASE_ID else '❌ 없음'}")

if not NOTION_TOKEN or not NOTION_DATABASE_ID:
    print("\n❌ 환경변수가 설정되지 않았습니다. .env 파일을 확인하세요.")
    exit(1)

# Notion 클라이언트 생성
notion = Client(auth=NOTION_TOKEN)

print("\n🔗 Notion API 연결 테스트 중...")

try:
    # 1. 사용자 정보 확인
    print("1️⃣ 사용자 정보 확인...")
    user_info = notion.users.me()
    print(f"   ✅ 연결됨: {user_info.get('name', 'Unknown')}")
    
    # 2. 데이터베이스 접근 테스트
    print("2️⃣ 데이터베이스 접근 테스트...")
    database_info = notion.databases.retrieve(database_id=NOTION_DATABASE_ID)
    print(f"   ✅ 데이터베이스명: {database_info['title'][0]['text']['content']}")
    
    # 3. 데이터베이스 속성 확인
    print("3️⃣ 데이터베이스 속성 확인...")
    properties = database_info['properties']
    required_props = ['제목', '채널', 'Video ID', '키워드', '감성', '요약 일시', 'YouTube URL']
    
    for prop in required_props:
        if prop in properties:
            prop_type = properties[prop]['type']
            print(f"   ✅ {prop} ({prop_type})")
        else:
            print(f"   ❌ {prop} - 누락됨")
    
    # 4. 테스트 데이터 생성
    print("4️⃣ 테스트 데이터 생성...")
    test_data = {
        "제목": {
            "title": [{"text": {"content": "🧪 연결 테스트"}}]
        },
        "채널": {
            "rich_text": [{"text": {"content": "테스트 채널"}}]
        },
        "Video ID": {
            "rich_text": [{"text": {"content": "test123"}}]
        },
        "키워드": {
            "multi_select": [{"name": "테스트"}]
        },
        "감성": {
            "select": {"name": "중립적"}
        },
        "요약 일시": {
            "date": {"start": "2024-01-01"}
        },
        "YouTube URL": {
            "url": "https://youtube.com/watch?v=test123"
        }
    }
    
    response = notion.pages.create(
        parent={"database_id": NOTION_DATABASE_ID},
        properties=test_data,
        children=[
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": "연결 테스트 성공! 🎉"}}]
                }
            }
        ]
    )
    
    print(f"   ✅ 테스트 페이지 생성 완료: {response['id']}")
    print(f"   🔗 URL: {response['url']}")
    
    print("\n🎉 모든 테스트 통과! Notion 연결이 정상적으로 설정되었습니다.")
    
except Exception as e:
    print(f"\n❌ 오류 발생: {e}")
    
    # 구체적인 오류 해결 방법 제시
    error_str = str(e).lower()
    
    if "could not find database" in error_str:
        print("\n💡 해결 방법:")
        print("1. 데이터베이스 ID가 올바른지 확인")
        print("2. Notion에서 데이터베이스에 Integration을 연결했는지 확인")
        print("3. 데이터베이스 → ... → 연결 → 'YouTube Summarizer' Integration 선택")
        
    elif "unauthorized" in error_str or "invalid token" in error_str:
        print("\n💡 해결 방법:")
        print("1. NOTION_TOKEN이 올바른지 확인")
        print("2. https://www.notion.so/my-integrations 에서 토큰 재생성")
        
    elif "validation failed" in error_str:
        print("\n💡 해결 방법:")
        print("1. 데이터베이스 속성 이름이 정확한지 확인")
        print("2. '감성' 속성에 '긍정적', '중립적', '부정적' 옵션 추가")
        
    print(f"\n📋 현재 설정:")
    print(f"TOKEN: {NOTION_TOKEN[:20]}..." if NOTION_TOKEN else "❌ 없음")
    print(f"DATABASE_ID: {NOTION_DATABASE_ID}" if NOTION_DATABASE_ID else "❌ 없음")