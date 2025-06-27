# import_script.py (重構後)
"""
資料匯入工具，將本地 JSON 檔案的資料批次匯入 Firestore。
"""
import json
import logging
import re
from pypinyin import pinyin, Style

import config
from services.firestore_handler import FirestoreHandler

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def _to_pinyin_string(text: str) -> str:
    """將中文字串轉換為安全的拼音字串。"""
    if not text: return ""
    syllables = pinyin(text, style=Style.NORMAL, errors='replace')
    ascii_text = "".join(s[0] for s in syllables if s and s[0])
    ascii_text = ascii_text.lower()
    ascii_text = re.sub(r'[^\w.-]+', '_', ascii_text)
    return re.sub(r'_+', '_', ascii_text).strip('_')

def import_tables(firestore: FirestoreHandler):
    """匯入桌位資訊。"""
    logger.info(f"--- 開始匯入桌位資訊到 '{config.TABLES_COLLECTION}' ---")
    try:
        with open(config.LOCAL_TABLES_FILE, 'r', encoding='utf-8') as f:
            tables_data = json.load(f)
    except Exception as e:
        logger.error(f"讀取桌位檔案 '{config.LOCAL_TABLES_FILE}' 失敗: {e}")
        return

    # 準備 Firestore 需要的格式
    data_to_import = []
    for table_id, data in tables_data.items():
        # 在新架構中，文件ID即為桌號，不需另外儲存 tableId 欄位
        new_data = {
            'project_id': config.PROJECT_ID,
            'displayName': data.get('displayName', table_id),
            'position': data.get('position', [0, 0]),
            'type': data.get('type', 'normal'),
            'capacity': data.get('capacity', 10),
            'tableId': table_id # 確保此欄位存在
        }
        data_to_import.append(new_data)
    
    # 使用 batch_import_data 進行批次寫入 (unique_key_fields 設為 ['project_id', 'tableId'])
    # 這會根據 project_id 和 tableId 判斷是新增還是更新
    new, updated = firestore.batch_import_data(
        config.TABLES_COLLECTION,
        data_to_import,
        unique_key_fields=['project_id', 'tableId']
    )
    logger.info(f"✅ 桌位匯入完成！新增: {new}, 更新: {updated}")

def import_guests(firestore: FirestoreHandler):
    """匯入賓客名單。"""
    logger.info(f"--- 開始匯入賓客名單到 '{config.GUESTS_COLLECTION}' ---")
    try:
        with open(config.LOCAL_GUESTS_FILE, 'r', encoding='utf-8') as f:
            guests_data = json.load(f)
    except Exception as e:
        logger.error(f"讀取賓客檔案 '{config.LOCAL_GUESTS_FILE}' 失敗: {e}")
        return
        
    data_to_import = []
    for guest in guests_data:
        guest_name = guest.get('name')
        if not guest_name:
            logger.warning(f"發現無姓名資料，已跳過: {guest}")
            continue
        
        new_data = {
            'project_id': config.PROJECT_ID,
            'name': guest_name,
            'category': guest.get('category', '未分類'),
            'seat': guest.get('seat', ''),
            'pinyin': _to_pinyin_string(guest_name),
            'checked_in': guest.get('checked_in', False),
            'expected_count': guest.get('expected_count',1),
            'checked_in_count': guest.get('checked_in_count',0),
            'phone': guest.get('phone', ''),
            'nickname': guest.get('nickname', ''),
            'group_id': guest.get('group_id', '')
        }
        data_to_import.append(new_data)
        
    # 根據 project_id, name, category 判斷唯一性
    new, updated = firestore.batch_import_data(
        config.GUESTS_COLLECTION,
        data_to_import,
        unique_key_fields=['project_id', 'name', 'category']
    )
    logger.info(f"✅ 賓客匯入完成！新增: {new}, 更新: {updated}")

def main():
    logger.info("--- 開始執行 Firestore 資料匯入腳本 ---")
    try:
        # 注意：執行此腳本需要 Google Cloud SDK 驗證 (gcloud auth application-default login)
        # 或設定 GOOGLE_APPLICATION_CREDENTIALS 環境變數
        firestore_handler = FirestoreHandler(project_id=config.GCP_PROJECT_ID)
    except Exception as e:
        logger.critical(f"初始化 FirestoreHandler 失敗: {e}", exc_info=True)
        return
        
    import_tables(firestore_handler)
    import_guests(firestore_handler)

if __name__ == '__main__':
    main()
