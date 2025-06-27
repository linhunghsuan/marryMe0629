# services/gcs_handler.py 約100行
"""
封裝所有與 Google Cloud Storage 相關的操作。
"""
import os
import io
import logging
from google.cloud import storage

logger = logging.getLogger(__name__)

class GCSHandler:
    def __init__(self, project_id: str, bucket_name: str, service_account_path: str = None):
        """
        初始化 GCS 客戶端和 Bucket。
        Args:
            project_id (str): Google Cloud 專案 ID。
            bucket_name (str): GCS 儲存桶名稱。
            service_account_path (str, optional): 服務帳號金鑰的路徑 (用於本地)。
        """
        try:
            if service_account_path and os.path.exists(service_account_path):
                self.client = storage.Client.from_service_account_json(service_account_path)
                logger.info(f"GCS Client 已從本機金鑰 '{service_account_path}' 初始化。")
            else:
                self.client = storage.Client(project=project_id)
                logger.info("GCS Client 使用應用程式預設憑證初始化。")
            
            self.bucket = self.client.bucket(bucket_name)
            logger.info(f"成功連接到 GCS Bucket: {bucket_name}")
        except Exception as e:
            logger.critical(f"連接 GCS 失敗: {e}")
            raise

    def upload(self, data_io: io.BytesIO, gcs_path: str, content_type='image/png'):
        """上傳檔案 (BytesIO) 到 GCS。"""
        try:
            blob = self.bucket.blob(gcs_path)
            data_io.seek(0)
            blob.upload_from_file(data_io, content_type=content_type)
            logger.info(f"檔案已上傳至 GCS: gs://{self.bucket.name}/{gcs_path}")
            return f"https://storage.googleapis.com/{self.bucket.name}/{gcs_path}"
        except Exception as e:
            logger.error(f"上傳檔案到 GCS 失敗 ({gcs_path}): {e}")
            return None

    def download(self, gcs_path: str) -> io.BytesIO | None:
        """從 GCS 下載檔案並回傳 BytesIO 物件。"""
        try:
            blob = self.bucket.blob(gcs_path)
            if blob.exists():
                data_io = io.BytesIO()
                blob.download_to_file(data_io)
                data_io.seek(0)
                logger.info(f"從 GCS 成功下載檔案: gs://{self.bucket.name}/{gcs_path}")
                return data_io
            else:
                logger.warning(f"GCS 檔案不存在: gs://{self.bucket.name}/{gcs_path}")
                return None
        except Exception as e:
            logger.error(f"從 GCS 下載檔案失敗 ({gcs_path}): {e}")
            return None

    def check_exists(self, gcs_path: str) -> bool:
        """檢查 GCS 上是否存在指定的檔案。"""
        try:
            blob = self.bucket.blob(gcs_path)
            return blob.exists()
        except Exception as e:
            logger.error(f"檢查 GCS 檔案存在性失敗 (gs://{self.bucket.name}/{gcs_path}): {e}")
            return False
