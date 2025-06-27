# services/firestore_handler.py 約150行
import logging
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

logger = logging.getLogger(__name__)

class FirestoreHandler:
    def __init__(self, project_id: str):
        try:
            self.db = firestore.Client(project=project_id)
            logger.info(f"Firestore 客戶端初始化成功 (專案: {project_id})。")
        except Exception as e:
            logger.critical(f"初始化 Firestore 客戶端失敗: {e}")
            raise

    def get_documents(self, collection: str, project_id_filter: str):
        """通用查詢函式，獲取指定集合中屬於特定專案的所有文件。"""
        try:
            docs_ref = self.db.collection(collection).where(filter=FieldFilter('project_id', '==', project_id_filter))
            return list(docs_ref.stream())
        except Exception as e:
            logger.error(f"從 Firestore 集合 '{collection}' 獲取文件失敗: {e}")
            return []
    
    def get_guests_by_field(self, collection: str, project_id_filter: str, field: str, value: str):
        """根據指定欄位查找賓客。"""
        try:
            guests_ref = self.db.collection(collection).where('project_id', '==', project_id_filter).where(field, '==', value)
            docs = list(guests_ref.stream())
            return [doc.to_dict() for doc in docs]
        except Exception as e:
            logger.error(f"Firestore 查詢失敗 (field: {field}, value: {value}): {e}")
            return []
        
    def find_guests_by_name(self, collection: str, project_id_filter: str, name: str):
        """根據姓名查找賓客，回傳文件串流。"""
        try:
            guests_ref = self.db.collection(collection).where(filter=FieldFilter('project_id', '==', project_id_filter)).where(filter=FieldFilter('name', '==', name))
            return list(guests_ref.stream())
        except Exception as e:
            logger.error(f"Firestore 姓名查詢失敗 (name: {name}): {e}")
            return []
            
    def check_in_guest_by_id(self, collection: str, doc_id: str, count: int):
        """根據文件 ID 報到賓客。"""
        try:
            doc_ref = self.db.collection(collection).document(doc_id)
            doc = doc_ref.get()
            if not doc.exists:
                return None, "not_found"
            
            # 更新報到狀態和人數
            doc_ref.update({
                'checked_in': True,
                'checked_in_count': count,
                'check_in_time': firestore.SERVER_TIMESTAMP
            })
            updated_doc = doc_ref.get()
            return updated_doc.to_dict(), "success"
        except Exception as e:
            logger.error(f"報到賓客(ID: {doc_id})時出錯: {e}")
            return None, "error"
            
    def cancel_check_in_by_id(self, collection: str, doc_id: str):
        """根據文件 ID 取消報到。"""
        try:
            doc_ref = self.db.collection(collection).document(doc_id)
            doc = doc_ref.get()
            if not doc.exists:
                return None, "not_found"
            
            if not doc.to_dict().get('checked_in'):
                return doc.to_dict(), "already_cancelled"

            doc_ref.update({
                'checked_in': False,
                'checked_in_count': 0
            })
            updated_doc = doc_ref.get()
            return updated_doc.to_dict(), "success"
        except Exception as e:
            logger.error(f"取消報到(ID: {doc_id})時出錯: {e}")
            return None, "error"

    def get_dialogue_state(self, collection: str, user_id: str):
        """獲取使用者的對話狀態。"""
        try:
            doc_ref = self.db.collection(collection).document(user_id)
            doc = doc_ref.get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            logger.error(f"獲取對話狀態失敗 (user_id: {user_id}): {e}")
            return None

    def set_dialogue_state(self, collection: str, user_id: str, state_payload: dict):
        """設定使用者的對話狀態。"""
        try:
            self.db.collection(collection).document(user_id).set(state_payload)
            return True
        except Exception as e:
            logger.error(f"設定對話狀態失敗 (user_id: {user_id}): {e}")
            return False

    def delete_dialogue_state(self, collection: str, user_id: str):
        """刪除使用者的對話狀態。"""
        try:
            self.db.collection(collection).document(user_id).delete()
            return True
        except Exception as e:
            logger.error(f"刪除對話狀態失敗 (user_id: {user_id}): {e}")
            return False
        
    def batch_import_data(self, collection_name: str, data_list: list, unique_key_fields: list = None):
        if not data_list:
            logger.warning(f"沒有資料可以匯入到 '{collection_name}'。")
            return 0, 0

        batch = self.db.batch()
        count_new, count_updated = 0, 0

        for item in data_list:
            if unique_key_fields:
                query = self.db.collection(collection_name)
                for field in unique_key_fields:
                    if field in item:
                        query = query.where(field, '==', item[field])
                
                if list(query.limit(1).stream()):
                    doc_ref = list(query.limit(1).stream())[0].reference
                    batch.set(doc_ref, item, merge=True)
                    count_updated += 1
                else:
                    doc_ref = self.db.collection(collection_name).document()
                    batch.set(doc_ref, item)
                    count_new += 1
            else:
                doc_ref = self.db.collection(collection_name).document()
                batch.set(doc_ref, item)
                count_new += 1
        try:
            batch.commit()
            logger.info(f"成功批次匯入資料到 '{collection_name}' (新增: {count_new}, 更新: {count_updated})。")
            return count_new, count_updated
        except Exception as e:
            logger.error(f"批次寫入 Firestore 失敗: {e}")
            return 0, 0