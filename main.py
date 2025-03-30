import os
import json
import requests
from datetime import datetime
from aliyunsdkcore.client import AcsClient
from aliyunsdkcore.acs_exception.exceptions import ServerException
from aliyunsdkgreen.request.v20220302 import FileAsyncScanRequest
from notion_client import Client

# 初始化Notion客户端
notion = Client(auth=os.getenv("NOTION_TOKEN"))

def get_pending_pages():
    """获取所有待处理的Notion页面"""
    query = {
        "database_id": os.getenv("NOTION_DATABASE_ID"),
        "filter": {
            "property": "Status",
            "select": {"equals": "Pending"}
        }
    }
    return notion.databases.query(**query).get("results", [])

def download_audio(audio_url):
    """从Notion下载音频文件内容"""
    headers = {"Authorization": f"Bearer {os.getenv('NOTION_TOKEN')}"}
    response = requests.get(audio_url, headers=headers)
    response.raise_for_status()
    return response.content

def ali_asr(audio_content):
    """调用阿里云Paraformer-v2 API"""
    client = AcsClient(
        os.getenv("ALIYUN_KEY_ID"),
        os.getenv("ALIYUN_KEY_SECRET"),
        region_id="cn-shanghai"
    )
    
    request = FileAsyncScanRequest.FileAsyncScanRequest()
    request.set_accept_format('json')
    request.set_FileBytes(audio_content)
    request.set_Service("paraformer_realtime")
    request.set_Async(False)
    
    try:
        response = client.do_action_with_exception(request)
        result = json.loads(response)
        return "\n".join([item["Text"] for item in result["Result"]])
    except ServerException as e:
        print(f"阿里云API错误: {e}")
        return None

def generate_summary(text):
    """简易文本摘要"""
    return text[:150] + "..." if len(text) > 150 else text

def update_notion_page(page_id, text, summary):
    """更新Notion页面"""
    notion.pages.update(
        page_id,
        properties={
            "Transcript": {"rich_text": [{"text": {"content": text}}]},
            "Summary": {"rich_text": [{"text": {"content": summary}}]},
            "Status": {"select": {"name": "Completed"}},
            "ProcessedTime": {"date": {"start": datetime.now().isoformat()}}
        }
    )

def main():
    pages = get_pending_pages()
    if not pages:
        print("没有待处理的录音文件")
        return

    for page in pages:
        try:
            # 获取音频URL
            file_prop = page["properties"].get("Audio", {})
            if not file_prop.get("files"):
                continue
                
            audio_url = file_prop["files"][0]["file"]["url"]
            
            # 处理流程
            audio_content = download_audio(audio_url)
            transcript = ali_asr(audio_content)
            
            if transcript:
                summary = generate_summary(transcript)
                update_notion_page(page["id"], transcript, summary)
                print(f"已处理页面：{page['id']}")
                
        except Exception as e:
            print(f"处理页面 {page['id']} 失败：{str(e)}")

if __name__ == "__main__":
    main()
