# core/data_provider.py 約150行
import json
import logging
from collections import Counter
from services.firestore_handler import FirestoreHandler
import config

logger = logging.getLogger(__name__)

class DataProvider:
    def __init__(self, mode: str, firestore_handler: FirestoreHandler = None):
        if mode not in ['local', 'cloud']:
            raise ValueError("Mode 必須是 'local' 或 'cloud'")

        self.mode = mode
        self.firestore = firestore_handler
        self.guests = []
        self.tables = {} 
        self.guest_name_counts = Counter()
        self.refresh_data() # 初始化時即載入資料

    def refresh_data(self):
        """重新從資料來源載入所有資料，以獲取最新狀態。"""
        logger.info("[DataProvider] 正在刷新資料...")
        if self.mode == 'local':
            self._load_from_local_files()
        elif self.mode == 'cloud':
            if not self.firestore:
                logger.error("在 'cloud' 模式下無法刷新，因為缺少 firestore_handler")
                return
            self._load_from_firestore()
        
        self._build_name_counts()
        logger.info("[DataProvider] 資料刷新完成。")

    def _load_from_local_files(self):
        """從本地 JSON 檔案載入資料，並使用'tableId'作為桌位的主鍵。"""
        # 載入賓客資料 (不變)
        try:
            with open(config.LOCAL_GUESTS_FILE, 'r', encoding='utf-8') as f:
                self.guests = json.load(f)
            logger.info(f"成功從 '{config.LOCAL_GUESTS_FILE}' 載入 {len(self.guests)} 位賓客資料。")
        except Exception as e:
            logger.error(f"載入賓客檔案失敗: {e}")
            self.guests = []
        
        # 載入桌位資料
        try:
            with open(config.LOCAL_TABLES_FILE, 'r', encoding='utf-8') as f:
                local_tables_data = json.load(f)

            temp_tables = {}
            if isinstance(local_tables_data, list):
                for table_data in local_tables_data:
                    # 尋找 'tableId' 欄位
                    logical_table_id = table_data.get('tableId')
                    if logical_table_id:
                        temp_tables[logical_table_id.upper()] = table_data
                    else:
                        logger.warning(f"本地桌位檔案中的一筆資料缺少'tableId'欄位，將被忽略。")
            elif isinstance(local_tables_data, dict):
                # 假設字典的鍵就是 tableId
                temp_tables = {k.upper(): v for k, v in local_tables_data.items()}
            
            self.tables = temp_tables
            logger.info(f"成功從 '{config.LOCAL_TABLES_FILE}' 載入並處理 {len(self.tables)} 個桌位資料。")
        except Exception as e:
            logger.error(f"載入或處理桌位檔案失敗: {e}")
            self.tables = {}

    def _load_from_firestore(self):
        """從 Firestore 載入資料，並使用'tableId'作為桌位的主鍵。"""
        # 載入賓客資料 (不變)
        guest_docs = self.firestore.get_documents(config.GUESTS_COLLECTION, config.PROJECT_ID)
        self.guests = [doc.to_dict() for doc in guest_docs]
        
        # 載入桌位資料
        table_docs = self.firestore.get_documents(config.TABLES_COLLECTION, config.PROJECT_ID)
        temp_tables = {}
        for doc in table_docs:
            table_data = doc.to_dict()
            
            logical_table_id = table_data.get('tableId')
            
            if logical_table_id:
                # 使用邏輯ID (tableId) 作為字典的 key
                table_data['document_id'] = doc.id
                temp_tables[logical_table_id.upper()] = table_data
            else:
                # 只有在'tableId'欄位也缺失的情況下，才會發出警告
                logger.warning(f"Firestore中的桌位文件(ID: {doc.id})缺少'tableId'欄位，將被忽略。")
                
        self.tables = temp_tables

    def _build_name_counts(self):
        """計算同名人數。"""
        if self.guests:
            raw_names = [guest.get("name") for guest in self.guests if guest.get("name")]
            self.guest_name_counts = Counter(raw_names)

    def get_all_guests(self) -> list:
        """獲取所有賓客的列表。"""
        return self.guests

    def get_all_tables(self) -> dict:
        """獲取所有桌位資訊的字典。"""
        return self.tables

    def get_guests_by_name(self, name: str) -> list:
        """根據姓名精確查找賓客。"""
        name_lower = name.lower()
        return [g for g in self.guests if g.get("name", "").lower() == name_lower]

    def get_guests_by_nickname(self, nickname: str) -> list:
        """根據綽號精確查找賓客。"""
        nickname_lower = nickname.lower()
        return [g for g in self.guests if g.get("nickname", "").lower() == nickname_lower]
        
    def get_guests_by_phone(self, phone: str) -> list:
        """根據電話號碼查找賓客。"""
        # 在雲端模式下，直接查詢 DB 更有效率
        if self.mode == 'cloud':
            return self.firestore.get_guests_by_field(
                config.GUESTS_COLLECTION, config.PROJECT_ID, 'phone', phone
            )
        # 本地模式則遍歷列表
        return [g for g in self.guests if g.get("phone") == phone]

    def get_guests_by_table(self, table_id: str) -> list:
        """根據桌號查找所有賓客。"""
        table_id_upper = table_id.upper()
        # 在雲端模式下，直接查詢 DB 更有效率
        if self.mode == 'cloud':
            return self.firestore.get_guests_by_field(
                config.GUESTS_COLLECTION, config.PROJECT_ID, 'seat', table_id_upper
            )
        # 本地模式則遍歷列表
        return [g for g in self.guests if g.get("seat", "").upper() == table_id_upper]

    def get_table_info(self, table_id: str) -> dict | None:
        """根據桌號獲取單一桌位資訊。"""
        return self.tables.get(table_id.upper())
        
    def get_guest_name_counts(self) -> Counter:
        """獲取姓名計數器。"""
        return self.guest_name_counts
