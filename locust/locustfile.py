import hmac
import base64
import hashlib
import json
import uuid  # 用於產生唯一的使用者 ID
from locust import HttpUser, task, between

class LineBotUser(HttpUser):
    # 設置 User-Agent，有些伺服器會檢查這個
    host = "https://5f1a-27-53-18-210.ngrok-free.app"
    wait_time = between(1, 5)  # 每個虛擬使用者執行任務後等待 1-5 秒

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.channel_secret = '967524b34b7e8566c30bc4522bbb55a0'.encode('utf-8')

    def _generate_signature(self, body):
        """產生 X-Line-Signature"""
        hash_obj = hmac.new(self.channel_secret, body.encode('utf-8'), hashlib.sha256)
        return base64.b64encode(hash_obj.digest()).decode('utf-8')

    @task
    def send_message(self):
        # 1. 準備請求的 Body (JSON)
        # 使用 uuid 來確保每個請求的 userId 都是獨一無二的
        user_id = "U" + uuid.uuid4().hex
        timestamp = int(self.environment.runner.start_time * 1000)

        body = {
            "destination": "@478pdylx", # 換成你的 Channel ID
            "events": [{
                "type": "message",
                "message": {"type": "text", "id": "12345", "text": "林宏軒"},
                "timestamp": timestamp,
                "source": {"type": "user", "userId": user_id},
                "replyToken": "dummy_reply_token", # 回覆 token 在壓測中通常不重要
                "mode": "active"
            }]
        }
        json_body = json.dumps(body)

        # 2. 產生簽章
        signature = self._generate_signature(json_body)

        # 3. 準備 Headers
        headers = {
            'Content-Type': 'application/json',
            'X-Line-Signature': signature
        }

        # 4. 發送 POST 請求到 /callback
        self.client.post("/callback", data=json_body, headers=headers, name="SendMessage")