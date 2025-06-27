# config.py 約250行
"""
統一管理所有設定值，包含環境變數、GCP 配置、LINE Bot 設定以及應用程式常數。
"""
import os
from dotenv import load_dotenv

# 在本地開發時，從 .env 檔案載入環境變數
load_dotenv()

# --- GCP Project Settings ---
GCP_PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'marryme-461108')
GCS_BUCKET_NAME = os.environ.get('GCS_BUCKET_NAME', 'marryme1140629')
GCS_SERVICE_ACCOUNT_PATH = os.environ.get('GCS_SERVICE_ACCOUNT_PATH', 'marryme-461108-8529a8cd30d8') # 本地執行時需要

# --- LINE Bot Settings ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')

# --- Application Settings ---
PROJECT_ID = os.environ.get('PROJECT_ID', 'yenliang_dailun_20250629')
ADMIN_USER_IDS = os.environ.get('ADMIN_USER_IDS', 'Ua15360183377f4c4de54ebe40d3ac251').split(',')

# --- Firestore Collection Names ---
GUESTS_COLLECTION = 'guests'
TABLES_COLLECTION = 'tables'

# --- Local Data File Paths (for local mode) ---
LOCAL_DATA_DIR = os.path.dirname(__file__)
LOCAL_GUESTS_FILE = os.path.join(LOCAL_DATA_DIR, 'customer_list.json')
LOCAL_TABLES_FILE = os.path.join(LOCAL_DATA_DIR, 'table_locations.json')
LOCAL_FONT_FILES = {
    'medium': os.path.join(LOCAL_DATA_DIR, 'assets', 'NotoSansTC-Medium.ttf'),
    'bold': os.path.join(LOCAL_DATA_DIR, 'assets', 'NotoSansTC-Bold.ttf'),
    'thin': os.path.join(LOCAL_DATA_DIR, 'assets', 'NotoSansTC-Thin.ttf'),
}


# --- Image Generation Settings ---
# GCS paths for assets
GCS_IMAGE_DIR = "generated_seat_maps"
LOGO_IMAGE_GCS_PATH = "assets/your_event_logo.png"
BACKGROUND_IMAGE_GCS_PATH = "assets/your_background_image.png"

# Drawing constants
DEFAULT_IMAGE_BACKGROUND_COLOR = "#fffcf7"
LOGO_AREA_HEIGHT_PX = 150
LOGO_PADDING_PX = 10
IMG_SCALE = 62
IMG_OFFSET_X = 70
IMG_OFFSET_Y_TOP = 30
IMG_OFFSET_Y_TOP_GRID = 60
IMG_OFFSET_Y_BOTTOM = 40
TABLE_RADIUS_PX = int(IMG_SCALE * 0.45)
HIGHLIGHT_THICKNESS_PX = 6
MIN_CANVAS_WIDTH = 480
MIN_CANVAS_HEIGHT = 320

# Table colors
TABLE_COLOR_MAP = {
    "normal":     "#cba6c3",
    "stage":      "#9b8281",
    "head_table": "#e7ded9",
    "blocked":    "#fffcf7"
}
HIGHLIGHT_COLOR = "#ffdd30"
HIGHLIGHT_TEXT_COLOR = "#534847"
TEXT_COLOR_ON_TABLE = "#ffffff"
TEXT_COLOR_ON_TABLE_DISPLAYNAME = "#ffffff"
TEXT_COLOR_PROMPT = "#534847"

STATE_EXPIRATION_SECONDS = 30  # 狀態保留 1 分鐘
DIALOGUE_STATE_COLLECTION = "dialogue_states" # 用於儲存對話狀態的 Firestore 集合
EXIT_COMMANDS = {"取消", "離開", "算了", "不用了", "幫助", "help"}

# 不觸發回覆的關鍵字設定
# ==============================================================================
# 當收到的訊息完全符合以下任何一個字詞時，機器人將不會做出任何回應。
# 建議使用小寫，程式會自動將使用者輸入轉為小寫進行比對。
# 使用 set 結構以獲得更快的查找速度。
NO_REPLY_KEYWORDS = {
    # 關鍵字回復
    "廠商資訊",
    "電子喜帖",
    "照片上傳",
    "路線引導",
    "導航",
    "路線指南",

    # LINE 內建訊息
    "[貼圖]",
    "[照片]",
    "[影片]",
    "[檔案]",
    "[語音訊息]",
    "[讚]",
    "[like]",
    "(emoji)",
    "[收回訊息]",

    # 同意與確認
    "ok",
    "okey",
    "k",
    "okkk",
    "ok,",
    "好",
    "好的",
    "好喔",
    "好啊",
    "好呀",
    "好滴",
    "豪",
    "行",
    "可以",
    "可",
    "中",
    "嗯",
    "嗯嗯",
    "嗯哼",
    "對",
    "沒錯",
    "正是",
    "是的",
    "是",
    "對的",
    "對喔",
    "對呀",
    "沒問題",
    "no problem",
    "np",
    "correct",

    # 了解與收到
    "了解",
    "瞭解",
    "收到",
    "明白",
    "懂了",
    "我懂了",
    "我了解了",
    "我明白了",
    "知道了",
    "我知道了",
    "get",
    "got it",
    "noted",
    "roger",
    "roger that",

    # 感謝與讚美
    "謝謝",
    "感謝",
    "感恩",
    "謝啦",
    "謝了",
    "多謝",
    "謝謝你",
    "謝謝您",
    "感謝你",
    "感謝您",
    "太感謝了",
    "非常感謝",
    "3q",
    "thanks",
    "thank you",
    "thx",
    "ty",
    "讚",
    "棒",
    "優",
    "水喔",
    "太棒了",
    "真棒",
    "厲害",
    "cool",
    "great",
    "nice",
    "well done",

    # 禮貌性回應與結尾
    "不客氣",
    "不會",
    "別客氣",
    "免客氣",
    "you're welcome",
    "yw",
    "辛苦了",
    "麻煩您了",
    "麻煩了",
    "掰掰",
    "bye bye",
    "byebye",
    "再見",

    # 感嘆與語助詞
    "哦",
    "喔",
    "喔喔",
    "哦哦",
    "哇",
    "哇喔",
    "原來如此",
    "原來是這樣",
    "這樣啊",
    "是喔",
    "醬子",
    "也是",
    "也對",
    "還好",
    "還行",
    
    # 笑聲與表情符號
    "哈",
    "哈哈",
    "哈哈哈",
    "嘻嘻",
    "呵呵",
    "XD",
    ":d",
    ":p",
    ":)",
    ";)",
    "^^",
    "^_^",
    ":-)",
    "cc",
    
    # 其他簡短回應
    "有",
    "在",
    "沒事",
    "沒事了",
    "沒關係",
    "沒差",
    "我看看",
    "看看",
    "再說",
    "晚點說",
}