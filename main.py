import os
import json
import time
import requests
from datetime import datetime
from aliyunsdkcore.client import AcsClient
from aliyunsdkcore.acs_exception.exceptions import ServerException
from aliyunsdkspeechfile.request.v20220302 import SubmitSpeechTaskRequest, GetSpeechTaskResultRequest
from notion_client import Client

# 初始化Notion客户端
notion = Client(auth=os.getenv("NOTION_TOKEN"))

def get_pending_pages():
    """获取所有待处理的Notion页面"""
    return notion.databases.query(
        database_id=os.getenv("NOTION_DATABASE_ID"),
        filter={"property": "Status", "select": {"equals": "Pending"}}
    ).get("results", [])

def download_audio(audio_url):
    """从Notion下载音频文件内容"""
    headers = {"Authorization": f"Bearer {os.getenv('NOTION_TOKEN')}"}
    response = requests.get(audio_url, headers=headers)
    response.raise_for_status()
    return response.content

def submit_ali_task(audio_content):
    """提交阿里云语音识别任务"""
    client = AcsClient(
        os.getenv("ALIYUN_KEY_ID"),
        os.getenv("ALIYUN_KEY_SECRET"),
        region_id="cn-shanghai"
    )
    
    request = SubmitSpeechTaskRequest.SubmitSpeechTaskRequest()
    request.set_FileBytes(audio_content)
    request.set_SampleRate(16000)  # 必须与音频实际采样率一致
    request.set_Format("wav")       # 支持格式：wav/mp3/pcm
    request.set_EnableWords(False)  # 是否开启分词
    
    response = client.do_action_with_exception(request)
    return json.loads(response)["Data"]["TaskId"]

def get_ali_result(task_id):
    """获取语音识别结果"""
    client = AcsClient(
        os.getenv("ALIYUN_KEY_ID"),
        os.getenv("ALIYUN_KEY_SECRET"),
        region_id="cn-shanghai"
    )
    
    request = GetSpeechTaskResultRequest.GetSpeechTaskResultRequest()
    request.set_TaskId(task_id)
    
    # 轮询结果（最大等待30秒）
    for _ in range(6):
        response = client.do_action_with_exception(request)
        result = json.loads(response)
        if result["Data"]["Status"] == "SUCCESS":
            return result["Data"]["Result"]["Sentences"][0]["Text"]
        time.sleep(5)
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
            # 获取音频文件属性
            file_prop = page["properties"].get("Audio", {})
            if not file_prop.get("files"):
                print(f"页面 {page['id']} 缺少音频文件")
                continue
                
            audio_url = file_prop["files"][0]["file"]["url"]
            
            # 处理流程
            audio_content = download_audio(audio_url)
            task_id = submit_ali_task(audio_content)
            transcript = get_ali_result(task_id)
            
            if transcript:
                summary = generate_summary(transcript)
                update_notion_page(page["id"], transcript, summary)
                print(f"已处理页面：{page['id']}")
            else:
                print(f"语音识别失败：{page['id']}")
                
        except Exception as e:
            print(f"处理页面 {page['id']} 失败：{str(e)}")

if __name__ == "__main__":
    main()
