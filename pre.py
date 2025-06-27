# pre.py 約100行
"""
本地批次處理進入點，用於預先生成所有賓客的座位圖並上傳至 GCS。
"""
import logging
import config
from services.gcs_handler import GCSHandler
from core.data_provider import DataProvider
from core.image_generator import ImageGenerator

# --- 初始化日誌 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(module)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    logger.info("--- 開始執行批次圖片生成任務 ---")
    
    # --- 服務初始化 (本地模式) ---
    try:
        # 外部服務
        # 注意：此處 GCS Handler 必須傳入金鑰路徑才能在本地進行驗證
        if not config.GCS_SERVICE_ACCOUNT_PATH:
            logger.critical("未設定 GCS_SERVICE_ACCOUNT_PATH 環境變數，無法執行本地批次任務。")
            return
            
        gcs_handler = GCSHandler(
            project_id=config.GCP_PROJECT_ID, 
            bucket_name=config.GCS_BUCKET_NAME,
            service_account_path=config.GCS_SERVICE_ACCOUNT_PATH
        )
        
        # 核心模組
        # DataProvider 在 'local' 模式下不需要 firestore_handler
        data_provider = DataProvider(mode='local')
        image_generator = ImageGenerator(gcs_handler=gcs_handler)

        logger.info("所有服務已在 [local] 模式下成功初始化。")
    except Exception as e:
        logger.critical(f"服務初始化失敗: {e}", exc_info=True)
        return

    # --- 執行邏輯 ---
    all_guests = data_provider.get_all_guests()
    all_tables = data_provider.get_all_tables()
    name_counts = data_provider.get_guest_name_counts()
    
    if not all_guests or not all_tables:
        logger.error("賓客或桌位資料為空，無法繼續執行。請檢查 JSON 檔案。")
        return

    total = len(all_guests)
    success_count = 0
    
    for i, guest in enumerate(all_guests):
        guest_name = guest.get("name")
        seat_id = guest.get("seat")
        
        if not all([guest_name, seat_id]):
            logger.warning(f"跳過不完整的賓客資料: {guest}")
            continue

        logger.info(f"[{i+1}/{total}] 正在處理賓客: {guest_name} (座位: {seat_id})")

        # 1. 生成 GCS 檔名
        gcs_path = image_generator.generate_gcs_filename(
            guest_name=guest_name,
            guest_category=guest.get("category"),
            name_counts=name_counts
        )

        # 2. 生成圖片
        image_io = image_generator.create_seat_image(
            all_tables_data=all_tables,
            target_seat_id=seat_id,
            guest_name=guest_name
        )

        if not image_io:
            logger.error(f"為 {guest_name} 生成圖片失敗。")
            continue

        # 3. 上傳圖片
        if gcs_handler.upload(image_io, gcs_path):
            success_count += 1
        else:
            logger.error(f"為 {guest_name} 上傳圖片失敗。")

    logger.info(f"--- 任務完成 ---")
    logger.info(f"總計處理: {total} 位賓客，成功生成並上傳: {success_count} 張圖片。")


if __name__ == "__main__":
    main()
