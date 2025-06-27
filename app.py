# app.py 約650行
import os
import time
import logging
import re
import threading
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from flask import Flask, request, abort
from linebot.v3.webhook import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, ReplyMessageRequest,
    TextMessage, ImageMessage, QuickReply, QuickReplyItem, MessageAction
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from thefuzz import process as fuzzy_process
from google.cloud.firestore import SERVER_TIMESTAMP

import config
from services.firestore_handler import FirestoreHandler
from services.gcs_handler import GCSHandler
from core.data_provider import DataProvider
from core.image_generator import ImageGenerator

# --- 初始化 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(process)d - %(module)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- 服務延遲初始化 ---
_services = {}
_locks = {
    "firestore": threading.Lock(),
    "gcs": threading.Lock(),
    "data_provider": threading.Lock(),
    "image_generator": threading.Lock(),
    "line_api": threading.Lock(),
    "webhook_handler": threading.Lock(),
}

# --- Service Getters ---
def get_firestore_handler() -> FirestoreHandler:
    with _locks["firestore"]:
        if "firestore" not in _services:
            logger.info("Initializing FirestoreHandler...")
            _services["firestore"] = FirestoreHandler(project_id=config.GCP_PROJECT_ID)
    return _services["firestore"]

def get_gcs_handler() -> GCSHandler:
    with _locks["gcs"]:
        if "gcs" not in _services:
            logger.info("Initializing GCSHandler...")
            _services["gcs"] = GCSHandler(project_id=config.GCP_PROJECT_ID, bucket_name=config.GCS_BUCKET_NAME)
    return _services["gcs"]

def get_data_provider() -> DataProvider:
    with _locks["data_provider"]:
        if "data_provider" not in _services:
            logger.info("Initializing DataProvider...")
            _services["data_provider"] = DataProvider(mode='cloud', firestore_handler=get_firestore_handler())
    return _services["data_provider"]

def get_image_generator() -> ImageGenerator:
    with _locks["image_generator"]:
        if "image_generator" not in _services:
            logger.info("Initializing ImageGenerator...")
            _services["image_generator"] = ImageGenerator(gcs_handler=get_gcs_handler())
    return _services["image_generator"]

def get_line_bot_api() -> MessagingApi:
    with _locks["line_api"]:
        if "line_api" not in _services:
            logger.info("Initializing LINE MessagingApi...")
            _services["line_api"] = MessagingApi(ApiClient(Configuration(access_token=config.LINE_CHANNEL_ACCESS_TOKEN)))
    return _services["line_api"]

def get_webhook_handler() -> WebhookHandler:
    with _locks["webhook_handler"]:
        if "webhook_handler" not in _services:
            logger.info("Initializing LINE WebhookHandler...")
            _services["webhook_handler"] = WebhookHandler(config.LINE_CHANNEL_SECRET)
    return _services["webhook_handler"]

# --- Webhook  ---
@app.route("/")
def home():
    return f"Wedding Seat Bot for project '{config.PROJECT_ID}' is running."

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        get_webhook_handler().handle(body, signature)
    except InvalidSignatureError:
        logger.error("LINE Signature 驗證失敗。")
        abort(400)
    except Exception as e:
        logger.error(f"處理請求時發生未預期錯誤: {e}", exc_info=True)
        abort(500)
    return 'OK'

# --- 訊息處理核心 ---
@get_webhook_handler().add(MessageEvent, message=TextMessageContent)
def handle_message(event: MessageEvent):
    user_id = event.source.user_id
    text = event.message.text.strip()
    reply_token = event.reply_token
    logger.info(f"處理來自 user_id: {user_id} 的訊息: '{text}'")

    # [NEW] 最高優先級：處理 "座位查詢" 指令
    if text == '座位查詢':
        handle_seat_inquiry(user_id, reply_token)
        return
    
    try:
        # 優先處理需要上下文的、有狀態的對話
        if handle_stateful_reply(user_id, text, reply_token):
            return
        
        # 檢查訊息是否包含在不回覆的關鍵字清單中
        if handle_no_reply(text):
            logger.info(f"訊息 '{text}' 在不回覆清單中，已忽略")
            return
    
        # 其次處理管理員指令
        if user_id in config.ADMIN_USER_IDS and handle_admin_commands(user_id, reply_token, text):
            return
        # 再處理一般關鍵字指令
        if handle_keyword_commands(reply_token, text):
            return
        
        # 最後處理一般查詢
        handle_general_query(user_id, reply_token, text)
        
    except Exception as e:
        logger.error(f"在 handle_message 中發生未捕獲的錯誤 (user_id: {user_id}): {e}", exc_info=True)
        try:
            get_line_bot_api().reply_message(ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text="抱歉，系統暫時忙碌中，請稍後再試")]
            ))
        except Exception as api_e:
            logger.error(f"連回覆錯誤訊息都失敗了: {api_e}")

# 處理 "座位查詢" 關鍵字
def handle_seat_inquiry(user_id: str, reply_token: str):
    logger.info(f"使用者 {user_id} 觸發了 '座位查詢' 功能")
    try:
        # 1. 透過 user_id 呼叫 Get Profile API 取得使用者個人資料
        profile = get_line_bot_api().get_profile(user_id)
        display_name = profile.display_name
        
        logger.info(f"成功取得使用者名稱: {display_name}，將以此名稱進行查詢")
        
        # 2. 將獲取的 display_name 作為查詢文字，交給通用的查詢處理器
        handle_general_query(user_id, reply_token, display_name)

    except Exception as e:
        logger.error(f"為 {user_id} 獲取 Profile 或處理座位查詢時發生錯誤: {e}", exc_info=True)
        reply_text = "很抱歉，無法自動讀取您的名稱\n請直接輸入您的【中文全名】來查詢座位"
        get_line_bot_api().reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )

# 檢查訊息是否包含在不回覆的關鍵字清單中
def handle_no_reply(text: str) -> bool:
    # 將使用者輸入的文字與設定檔中的關鍵字比對
    if text.lower() in config.NO_REPLY_KEYWORDS:
        return True
    
    return False

# 處理需要上下文的、有狀態的回覆 (包含一般使用者和管理員)
def handle_stateful_reply(user_id: str, text: str, reply_token: str) -> bool:
    firestore_handler = get_firestore_handler()
    state_doc = firestore_handler.get_dialogue_state(config.DIALOGUE_STATE_COLLECTION, user_id)

    if not state_doc:
        return False

    # --- 逾時檢查邏輯 ---
    state_timestamp = state_doc.get('timestamp')
    if isinstance(state_timestamp, datetime):
        now_utc = datetime.now(timezone.utc)
        if now_utc - state_timestamp > timedelta(seconds=config.STATE_EXPIRATION_SECONDS):
            logger.info(f"使用者 {user_id} 的對話狀態因逾時({config.STATE_EXPIRATION_SECONDS}秒)而被清除")
            firestore_handler.delete_dialogue_state(config.DIALOGUE_STATE_COLLECTION, user_id)
            
            timeout_message = "您的操作等待時間過長，對話已自動結束\n請重新開始，例如：直接輸入您的【中文全名】"
            get_line_bot_api().reply_message(ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=timeout_message)]
            ))
            return True

    # 處理需要上下文的、有狀態的回覆
    if text in config.EXIT_COMMANDS:
        firestore_handler.delete_dialogue_state(config.DIALOGUE_STATE_COLLECTION, user_id)
        get_line_bot_api().reply_message(ReplyMessageRequest(reply_token=reply_token, messages=[TextMessage(text="好的，操作已取消")]))
        return True

    try:
        choice_index = int(text) - 1
        options = state_doc.get('options', [])
        action = state_doc.get('action', 'query')

        if not (0 <= choice_index < len(options)):
            raise ValueError("Index out of range")

        selected_option = options[choice_index]
        reply = ""

        # 根據 action 執行不同操作
        if action == 'query':
            send_seat_image_to_line(reply_token, selected_option)
        elif action == 'force_regenerate':
            send_seat_image_to_line(reply_token, selected_option, force_regenerate=True)

        # 清理狀態並回覆
        firestore_handler.delete_dialogue_state(config.DIALOGUE_STATE_COLLECTION, user_id)
        if reply: # 如果有需要回覆的文字訊息
            get_line_bot_api().reply_message(ReplyMessageRequest(reply_token=reply_token, messages=[TextMessage(text=reply)]))
        return True

    except (ValueError, TypeError):
        get_line_bot_api().reply_message(ReplyMessageRequest(reply_token=reply_token, messages=[TextMessage(text="無效的數字選項，請重新輸入數字\n若要重新查詢，請先輸入【取消】，再直接輸入您的【中文全名】")]))
        return True
    
# 處理管理員專用指令
def handle_admin_commands(user_id: str, reply_token: str, text: str) -> bool:
    # --- 處理動作指令 (報到/取消報到/重新生成) ---
    action, name_to_process, count = None, "", 0
    if text.startswith("報到_"):
        action = "check_in"
        parts = text.split('_')
        name_to_process = parts[1].strip() if len(parts) > 1 else ""
        count = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1
    elif text.startswith("取消報到_"):
        action = "cancel_check_in"
        name_to_process = text[5:].strip()
    elif text.startswith("重新生成_"):
        action = "force_regenerate"
        name_to_process = text[5:].strip()
    if action:
        if not name_to_process:
            get_line_bot_api().reply_message(ReplyMessageRequest(reply_token=reply_token, messages=[TextMessage(text="請輸入要處理的賓客【中文全名】")]))
            return True

        guest_docs = get_firestore_handler().find_guests_by_name(config.GUESTS_COLLECTION, config.PROJECT_ID, name_to_process)
        if not guest_docs:
            get_line_bot_api().reply_message(ReplyMessageRequest(reply_token=reply_token, messages=[TextMessage(text=f"找不到名為【{name_to_process}】的賓客")]))
            return True

        guest_doc = guest_docs[0]
        reply = ""

        if action == "check_in":
            data, status = get_firestore_handler().check_in_guest_by_id(config.GUESTS_COLLECTION, guest_doc.id, count)
            if status == "success":
                get_data_provider().refresh_data()
                reply = f"✅ 完成！賓客【{data['name']}】({data['seat']}桌) 已報到，人數：{data['checked_in_count']} 位"
            else: reply = "❌ 報到時發生錯誤"
        elif action == "cancel_check_in":
            data, status = get_firestore_handler().cancel_check_in_by_id(config.GUESTS_COLLECTION, guest_doc.id)
            if status == "success":
                get_data_provider().refresh_data()
                reply = f"✅ 完成！【{data['name']}】({data['seat']}) 的報到已被取消"
            else: reply = "❌ 取消報到時發生錯誤"
        elif action == "force_regenerate":
            send_seat_image_to_line(reply_token, guest_doc.to_dict(), force_regenerate=True)
            return True
        
        get_line_bot_api().reply_message(ReplyMessageRequest(reply_token=reply_token, messages=[TextMessage(text=reply)]))
        return True

    # --- 處理查詢指令: 未報到/出席率/空位  ---
    if text in ["未報到" , "出席率", "空位"]:
        data_provider = get_data_provider()
        data_provider.refresh_data() 
        
        all_guests = data_provider.get_all_guests()

        total_invitations = len(all_guests)
        total_expected_guests = sum(int(g.get('expected_count', 1)) for g in all_guests)
        
        checked_in_groups = sum(1 for g in all_guests if g.get('checked_in'))
        checked_in_total_count = sum(int(g.get('checked_in_count', 0)) for g in all_guests if g.get('checked_in'))

        if text in ["未報到"]:
            logger.info(f"管理員 {user_id} 正在查詢未報到賓客...")

            # 1. 篩選出尚未報到的賓客
            unchecked_in_guests = [g for g in all_guests if not g.get('checked_in')]

            # 2. 根據篩選結果，組合回覆訊息
            if not unchecked_in_guests:
                reply = "恭喜！所有賓客均已完成報到！"
            else:
                # 依照桌號對未報到賓客列表進行排序
                unchecked_in_guests.sort(key=lambda g: natural_sort_key(g.get('seat', 'Z')))

                # 準備要顯示的每一行資訊
                info_lines = []
                total_unchecked_count = 0
                grouped_guests = defaultdict(list)
                total_unchecked_count = 0

                # 分組 guests
                for guest in unchecked_in_guests:
                    seat = guest.get('seat', '')
                    category = guest.get('category', '')
                    name = guest.get('name', '')
                    expected_count = int(guest.get('expected_count', 1))
                    total_unchecked_count += expected_count

                    key = (seat, category)
                    grouped_guests[key].append((name, expected_count))

                # 組合訊息
                info_lines = []
                for (seat, category), guest_list in grouped_guests.items():
                    info_lines.append(f"{seat} {category}")
                    for name, count in guest_list:
                        info_lines.append(f" - {name} {count}位")

                # 組合最終回覆
                reply = "尚未報到賓客列表：\n"
                reply += "\n".join(info_lines)
                reply += f"\n總計 {len(unchecked_in_guests)} 組、約 {total_unchecked_count} 位賓客尚未報到。"

            # 4. 回傳訊息給使用者
            get_line_bot_api().reply_message(ReplyMessageRequest(reply_token=reply_token, messages=[TextMessage(text=reply)]))
            return True
        
        elif text == "出席率":
            percentage = (checked_in_total_count / total_expected_guests * 100) if total_expected_guests > 0 else 0
            reply = (f"已到場總人數：{checked_in_total_count} / {total_expected_guests} 位\n"
                     f"已報到組數：{checked_in_groups} / {total_invitations} 組\n\n"
                     f"目前出席率(依人數)：{percentage:.2f}%")
            
        elif text == "空位":
            # 1. 直接從 DataProvider 獲取已經整理好的桌子字典
            all_tables_from_provider = data_provider.get_all_tables()

            # 2. 計算每桌已報到人數
            checked_in_by_table = {}
            for guest in all_guests:
                # 只計算已報到的賓客
                if guest.get('checked_in'):
                    seat_id = guest.get('seat') # seat_id 會是 'T1', 'T2' 等
                    if seat_id:
                        # 將 guest 的 checked_in_count (字串) 轉為數字並累加
                        checked_in_by_table[seat_id] = checked_in_by_table.get(seat_id, 0) + int(guest.get('checked_in_count', 0))

            # 3. 準備最終要顯示的資訊列表
            seats_info = []

            # 4. 遍歷排序後的桌子，並產生顯示字串
            #    使用 all_tables_from_provider.items() 進行遍歷
            for seat_id, table_info in sorted(all_tables_from_provider.items(), key=lambda item: natural_sort_key(item[0])):
                
                # 如果您希望顯示所有桌子（包含 'blocked' 的主桌），可以移除或修改此行。
                if table_info.get('type') != 'normal': continue

                # 從 table_info 中獲取所需資訊
                capacity = int(table_info.get('capacity', 10))
                occupied = checked_in_by_table.get(seat_id, 0)
                display_name = table_info.get('displayName', seat_id)
                
                # 組合狀態文字
                status_text = f"{occupied}/{capacity}"
                
                # 判斷是否到齊
                if occupied >= capacity:
                    status_text += " 到齊"
                    
                # 組合最終的單行訊息
                seats_info.append(f"{seat_id} {display_name} {status_text}")

            # 5. 組合最終回覆
            reply = "各桌次即時狀態如下：\n" + "\n".join(seats_info) if seats_info else ""


        get_line_bot_api().reply_message(ReplyMessageRequest(reply_token=reply_token, messages=[TextMessage(text=reply)]))
        return True
    
    # --- 處理桌號反查 ---
    if re.fullmatch(r"^[A-Z]\d{1,2}$", text, re.IGNORECASE):
        data_provider = get_data_provider()
        guests_at_table = data_provider.get_guests_by_table(text)
        if guests_at_table:
            names = [g['name'] for g in guests_at_table]
            reply = f"查詢 {text.upper()} 桌的同桌賓客有：\n- " + "\n- ".join(names)
        else:
            reply = f"找不到【{text.upper()}】桌的賓客資訊，請確認桌號"
        get_line_bot_api().reply_message(ReplyMessageRequest(reply_token=reply_token, messages=[TextMessage(text=reply)]))
        return True

    # --- 處理重新生成 ---
    regenerate_match = re.fullmatch(r"重新生成[:_ ](.+)", text, re.IGNORECASE)
    if regenerate_match:
        name_to_process = regenerate_match.group(1).strip()
        logger.info(f"管理員 {user_id} 觸發對 '{name_to_process}' 的圖片重新生成指令")
        
        data_provider = get_data_provider()
        found_guests = data_provider.get_guests_by_name(name_to_process)
        
        if not found_guests:
            reply = f"找不到名為【{name_to_process}】的賓客，無法重新生成圖片"
            get_line_bot_api().reply_message(ReplyMessageRequest(reply_token=reply_token, messages=[TextMessage(text=reply)]))
            return True
        
        guest_data = found_guests[0]
        logger.info(f"找到唯一賓客【{guest_data['name']}】，直接重新生成圖片")
        send_seat_image_to_line(reply_token, guest_data, force_regenerate=True)
        return True
    
    return False

# 處理一般關鍵字指令
def handle_keyword_commands(reply_token: str, text: str) -> bool:
    text_lower = text.lower()
    if text_lower in ["幫助", "help", "你好", "hi", "hello"]:
        reply = "您好，我是彥良岱倫的婚禮小幫手！😊\n請直接輸入您的【中文全名】來查詢座位！\n\n您也可以試試看輸入：\n📜【時程】查看婚禮開始時間\n🔔【QA】查看停車折抵說明\n🌟【提醒】查看婚禮入場溫馨提醒"
        get_line_bot_api().reply_message(ReplyMessageRequest(reply_token=reply_token, messages=[TextMessage(text=reply)]))
        return True

    keyword_map = {
        "時程": "📜 今日婚禮時程 📜\n12:00 賓客入場，期待你的蒞臨\n12:30 準時開席，新人即將登場",
        "qa": "🔔 停車折抵說明\n若有停車於飯店內\n喜宴結束前工作人員會發放停車折抵券\n請賓客離開前再於繳費機台折抵或線上折抵唷！",
        "提醒": "🌟 婚禮入場溫馨提醒\n\n1. 婚禮時程\n12:00 賓客入場，期待你的蒞臨\n12:30 準時開席，新人即將登場\n\n2. 婚禮現場有專業攝影師，看到鏡頭不用害羞盡情微笑比✌️呦！\n\n3. 歡迎大家拍照錄影，IG限動打卡分享給我們❤️❤️\n分享標記婚禮專屬hashtag\n#幸福良緣無與倫比\n\n4. 婚禮現場有拍立得留言祝福活動，快來留言妳想對新人說的話吧～～\n\n期待與大家見面，享受美好相聚時光😛😛😛"
    }
    if text_lower in keyword_map:
        get_line_bot_api().reply_message(ReplyMessageRequest(reply_token=reply_token, messages=[TextMessage(text=keyword_map[text_lower])]))
        return True

    return False

# 處理所有非指令的一般查詢，主要是姓名或桌號
def handle_general_query(user_id: str, reply_token: str, text: str):
    data_provider = get_data_provider()
    
    # 電話查詢
    if re.fullmatch(r"^09\d{8}$", text):
        found_guests = data_provider.get_guests_by_phone(text)
        process_query_results(user_id, reply_token, found_guests, text)
        return

    # 批次查詢 (用頓號、逗號、空格分隔)
    delimiters = ['、', ',', ' ']
    if any(d in text for d in delimiters):
        names = [name for name in re.split(r'[、,\s]+', text) if name]
        if len(names) > 1:
            all_results = []
            for name in names:
                all_results.extend(data_provider.get_guests_by_name(name))

            if not all_results:
                reply = f"批次查詢的賓客【{'、'.join(names)}】均不在名單中。"
            else:
                result_texts = [f"- {g['name']} ({g.get('category', '')}) 位於 {g['seat']} 桌" for g in all_results]
                reply = "為您查詢到以下賓客的座位：" + "\n".join(result_texts)
            get_line_bot_api().reply_message(ReplyMessageRequest(reply_token=reply_token, messages=[TextMessage(text=reply)]))
            return

    # --- 姓名/綽號/模糊查詢 ---
    # 精確姓名/綽號查詢
    found_guests = data_provider.get_guests_by_name(text) or data_provider.get_guests_by_nickname(text)
    if process_query_results(user_id, reply_token, found_guests, text, is_exact_search=True):
        return

    # 模糊比對
    all_guests = data_provider.get_all_guests()
    choices_dict = {g['name']: g for g in all_guests if g.get('name')}
    choices_dict.update({g['nickname']: g for g in all_guests if g.get('nickname')})

    fuzzy_matches = fuzzy_process.extractBests(text, choices_dict.keys(), score_cutoff=75, limit=5)
    if fuzzy_matches:
        unique_guests = {}
        for match in fuzzy_matches:
            matched_key = match[0]
            guest_data = choices_dict[matched_key]
            unique_guests[guest_data['name']] = guest_data

        fuzzy_guests = list(unique_guests.values())
        process_query_results(user_id, reply_token, fuzzy_guests, text, is_exact_search=False)
    else:
        reply = "很抱歉，找不到您的名字。\n請問您是與哪位親友一同前來？\n請試著輸入同行主要聯絡人的【中文全名】"
        get_line_bot_api().reply_message(ReplyMessageRequest(reply_token=reply_token, messages=[TextMessage(text=reply)]))

# 根據查詢結果數量決定下一步動作
def process_query_results(user_id: str, reply_token: str, guests: list, query: str, is_exact_search: bool = True) -> bool:
    """
    - 0筆：回傳 False，讓主流程繼續。
    - 1筆：直接發送座位圖。
    - 多筆：將狀態存入 Firestore，並向使用者發送選項。
    """
    if not guests:
        return False

    if len(guests) == 1:
        send_seat_image_to_line(reply_token, guests[0])
        return True

    # --- 找到多筆結果，進入多選項詢問流程 ---
    intro_text = (
        f"我們找到了幾位名為【{query}】的賓客，請問您是哪一位？"
        if is_exact_search
        else f"我們找到了幾位與【{query}】名字相似的賓客，請問您是要找..."
    )
    
    send_multiple_choice_reply(
        reply_token=reply_token,
        user_id=user_id,
        intro_text=intro_text,
        options=guests,
        action='query'
    )

    # 將對話狀態儲存到 Firestore
    db = get_firestore_handler().db
    state_payload = {
        "options": guests,
        "timestamp": SERVER_TIMESTAMP
    }
    db.collection(config.DIALOGUE_STATE_COLLECTION).document(user_id).set(state_payload)
    logger.info(f"為使用者 {user_id} 在 Firestore 中儲存了 {len(guests)} 個選項")

    return True

# 多選項回覆
def send_multiple_choice_reply(reply_token: str, user_id: str, intro_text: str, options: list, action: str, extra_state_payload: dict = None):
    # 1. 組合選項文字
    options_lines = [f"{i+1}. {g.get('name')} ({g.get('category', '無分類')}, {g.get('seat')}桌)" for i, g in enumerate(options)]
    options_text = '\n'.join(options_lines)
    reply_text = f"{intro_text}\n\n{options_text}\n\n請直接回覆【數字】選項或輸入【取消】。"

    # 2. 準備要存儲的對話狀態
    state_payload = {
        "action": action,
        "options": options,
        "timestamp": SERVER_TIMESTAMP  # 使用 Firestore 伺服器時間戳
    }
    # 如果有額外資訊 (例如報到人數)，也一併加入
    if extra_state_payload:
        state_payload.update(extra_state_payload)
    
    get_firestore_handler().set_dialogue_state(config.DIALOGUE_STATE_COLLECTION, user_id, state_payload)
    logger.info(f"為使用者 {user_id} 在 Firestore 中儲存了 {len(options)} 個 '{action}' 選項。")

    # 3. 發送帶有快速回覆的訊息
    # LINE 的 QuickReply 上限為 13 個選項
    quick_reply_items = [QuickReplyItem(action=MessageAction(label=str(i+1), text=str(i+1))) for i in range(len(options))][:13]
    get_line_bot_api().reply_message(
        ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text=reply_text, quick_reply=QuickReply(items=quick_reply_items))]
        )
    )

# 產生並發送座位圖給使用者
def send_seat_image_to_line(reply_token: str, guest_data: dict, force_regenerate: bool = False):
    guest_name = guest_data.get("name")
    target_seat_id = guest_data.get("seat")

    if not all([guest_name, target_seat_id]):
        logger.error(f"缺少賓客資料，無法處理: {guest_data}")
        get_line_bot_api().reply_message(ReplyMessageRequest(reply_token=reply_token, messages=[TextMessage(text="查詢資料不完整，無法處理")]))
        return

    # 使用 get() 方法取得服務實例
    image_generator = get_image_generator()
    data_provider = get_data_provider()
    gcs_handler = get_gcs_handler()
    line_bot_api = get_line_bot_api()

    # 1. 生成 GCS 檔名
    image_gcs_path = image_generator.generate_gcs_filename(
        guest_name=guest_name,
        guest_category=guest_data.get("category"),
        name_counts=data_provider.get_guest_name_counts()
    )
    image_url = f"https://storage.googleapis.com/{config.GCS_BUCKET_NAME}/{image_gcs_path}"

    # 2. 檢查 GCS 快取
    if not force_regenerate and gcs_handler.check_exists(image_gcs_path):
        logger.info(f"GCS 快取命中，直接使用圖片: {image_url}")
    else:
        logger.info(f"GCS 快取未命中或強制生成，為 '{guest_name}' 產生新圖片。")
        all_tables = data_provider.get_all_tables()
        if target_seat_id not in all_tables:
            logger.warning(f"請求的座位ID '{target_seat_id}' 在資料中不存在。")
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=reply_token, messages=[TextMessage(text="抱歉，您的桌位資訊有誤，請洽詢現場服務人員")]))
            return

        # 3. 生成新圖片
        image_io = image_generator.create_seat_image(
            all_tables_data=all_tables,
            target_seat_id=target_seat_id,
            guest_name=guest_name
        )
        if not image_io:
            logger.error(f"為 '{guest_name}' 產生座位圖失敗")
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=reply_token, messages=[TextMessage(text="抱歉，為您產生座位圖時發生錯誤")]))
            return

        # 4. 上傳到 GCS
        gcs_handler.upload(image_io, image_gcs_path)

    # 5. 回覆 LINE 訊息
    # 加上 cache busting 參數確保 LINE 不會快取舊圖
    final_image_url = f"{image_url}?t={int(time.time())}"
    try:
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[
                    TextMessage(text=f"您好，{guest_name}！\n彥良與岱倫誠摯歡迎您的蒞臨\n您的座位在此為您引導："),
                    ImageMessage(original_content_url=final_image_url, preview_image_url=final_image_url)
                ]
            )
        )
        logger.info(f"座位圖已成功發送給 '{guest_name}'.")
    except Exception as e:
        logger.error(f"透過 LINE 發送圖片失敗 ({final_image_url}): {e}", exc_info=True)
        # 嘗試只用文字回覆
        line_bot_api.reply_message(ReplyMessageRequest(reply_token=reply_token, messages=[TextMessage(text="抱歉，發送座位圖時遇到問題，請聯繫服務人員")]))

# 提供自然排序的鍵，例如 T2 會在 T10 之前
def natural_sort_key(s: str):
    import re
    return [int(t) if t.isdigit() else t.lower() for t in re.split('([0-9]+)', s)]

# --- App 啟動 ---
if __name__ == '__main__':
    # 此區塊僅在本地直接執行 `python app.py` 時才會運行
    # Gunicorn 或 Cloud Run 等正式環境不會執行這裡的程式碼
    logger.info("以本地開發模式啟動 Flask 伺服器...")
    port = int(os.environ.get("PORT", 8080))
    # debug=True 會使 Flask 啟動兩個進程，可能導致初始化日誌打印兩次，此為正常現象。
    app.run(host="0.0.0.0", port=port, debug=True)