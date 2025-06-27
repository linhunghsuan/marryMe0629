# core/image_generator.py 約350行
"""
純粹的圖片渲染引擎，負責繪製座位圖。
不處理資料來源，只接收資料並回傳圖片。
"""
import io
import os
import re
import hashlib
import logging
from PIL import Image, ImageDraw, ImageFont
from pypinyin import pinyin, Style
from services.gcs_handler import GCSHandler
import config

logger = logging.getLogger(__name__)

class ImageGenerator:
    def __init__(self, gcs_handler: GCSHandler):
        """
        初始化圖片生成器。
        Args:
            gcs_handler (GCSHandler): 用於下載 Logo、背景等素材。
        """
        self.gcs = gcs_handler
        self._load_assets()

    def _load_assets(self):
        """從 GCS 下載並載入必要的素材 (Logo, 背景圖, 字型)。"""
        # 讀取在 config.py 中設定的字型路徑字典
        self.font_path = config.LOCAL_FONT_FILES
        
        # 將 'medium' 字型路徑作為所有字型的預設備援
        default_font_path = self.font_path.get('medium')

        try:
            if not default_font_path:
                raise IOError("預設的 'medium' 字型路徑未在 config 中設定。")

            # --- 載入語意化的字型物件 ---
            # 根據我們在 draw_multiline_text 邏輯中使用的名稱來建立字型
            
            # 大字型 (例如桌號、標題)，使用粗體效果更佳
            self.font_large = ImageFont.truetype(self.font_path.get('bold', default_font_path), 28)
            
            # 中等字型 (例如 displayName 的預設大小)
            self.font_medium = ImageFont.truetype(default_font_path, 12)

            # 小字型 (用於文字較多或需要縮小的場景)
            self.font_small = ImageFont.truetype(default_font_path, 10)

            # 細字型
            self.font_thin = ImageFont.truetype(self.font_path.get('thin', default_font_path), 12)
            
            # 您原有的 prompt 字型
            self.font_prompt_small = ImageFont.truetype(default_font_path, 18)

            logger.info("成功載入所有自訂字型。")
        except Exception as e:
            logger.critical(f"載入字型時發生嚴重錯誤", exc_info=True)
            self.font_path = None
            self.font_large = ImageFont.load_default(size=28)
            self.font_table_id = ImageFont.load_default(size=14)
            self.font_table_displayname = ImageFont.load_default(size=12)
            self.font_prompt_small = ImageFont.load_default(size=18)

        # 載入 Logo 和背景
        logo_io = self.gcs.download(config.LOGO_IMAGE_GCS_PATH)
        self.logo_image = Image.open(logo_io).convert("RGBA") if logo_io else None
        if not self.logo_image:
            logger.error(f"載入 LOGO 失敗: {config.LOGO_IMAGE_GCS_PATH}")

        bg_io = self.gcs.download(config.BACKGROUND_IMAGE_GCS_PATH)
        self.background_image = Image.open(bg_io).convert("RGBA") if bg_io else None
        if not self.background_image:
            logger.warning(f"載入 背景圖片 失敗: {config.BACKGROUND_IMAGE_GCS_PATH}")

    def generate_gcs_filename(self, guest_name: str, guest_category: str, name_counts: dict) -> str:
        """根據賓客資訊生成 GCS 上的唯一檔名。"""
        pinyin_name = self._to_pinyin_string(guest_name)
        
        if name_counts.get(guest_name, 0) > 1 and guest_category:
            pinyin_category = self._to_pinyin_string(guest_category)
            readable_prefix = f"{pinyin_name}_{pinyin_category}"
        else:
            readable_prefix = pinyin_name

        unique_key = f"{guest_name}::{guest_category or ''}"
        unique_hash = hashlib.md5(unique_key.encode('utf-8')).hexdigest()[:6]
        
        filename = f"{readable_prefix}_{unique_hash}.png"
        return os.path.join(config.GCS_IMAGE_DIR, filename).replace('\\', '/')

    def _to_pinyin_string(self, text: str) -> str:
        """將中文字串轉換為安全的拼音字串。"""
        if not text:
            return "unknown"
        try:
            syllables = pinyin(text, style=Style.NORMAL, errors='replace')
            ascii_text = "".join(s[0] for s in syllables if s and s[0])
            ascii_text = ascii_text.lower()
            ascii_text = re.sub(r'[^\w.-]+', '_', ascii_text)
            return re.sub(r'_+', '_', ascii_text).strip('_') or "guest"
        except Exception:
            return hashlib.md5(text.encode('utf-8')).hexdigest()[:10]

    def create_seat_image(self, all_tables_data: dict, target_seat_id: str, guest_name: str, background_alignment: str = "延展") -> io.BytesIO | None:
        """
        核心繪圖函式。
        """
        if not all_tables_data:
            logger.error("未提供桌位資料 (all_tables_data)，無法產生座位圖。")
            return None

        # --- 1. 計算畫布尺寸 ---
        max_x, max_y = 0, 0
        valid_tables = [info for info in all_tables_data.values() if info and isinstance(info.get("position"), list) and len(info["position"]) == 2]
        if valid_tables:
            max_x = max(info["position"][0] for info in valid_tables)
            max_y = max(info["position"][1] for info in valid_tables)

        grid_content_width = (max_x + 1) * config.IMG_SCALE
        grid_content_height = (max_y + 1) * config.IMG_SCALE
        canvas_width = max(grid_content_width + config.IMG_OFFSET_X * 2, config.MIN_CANVAS_WIDTH)
        canvas_height = max(
            config.LOGO_AREA_HEIGHT_PX + config.IMG_OFFSET_Y_TOP_GRID + grid_content_height + config.IMG_OFFSET_Y_BOTTOM + config.IMG_OFFSET_Y_TOP,
            config.MIN_CANVAS_HEIGHT + config.LOGO_AREA_HEIGHT_PX
        )
        
        # --- 2. 建立畫布與繪圖物件 ---
        img = Image.new("RGBA", (int(canvas_width), int(canvas_height)), config.DEFAULT_IMAGE_BACKGROUND_COLOR)
        draw = ImageDraw.Draw(img)

        # --- 3. 繪製背景圖 ---
        if self.background_image:
            try:
                bg_width, bg_height = self.background_image.size
                paste_pos = None
                
                match background_alignment:
                    case "左上角": paste_pos = (0, 0)
                    case "右上角": paste_pos = (canvas_width - bg_width, 0)
                    case "左下角": paste_pos = (0, canvas_height - bg_height)
                    case "右下角": paste_pos = (canvas_width - bg_width, canvas_height - bg_height)
                    case "置中": paste_pos = ((canvas_width - bg_width) // 2, (canvas_height - bg_height) // 2)
                    case "上方置中": paste_pos = ((canvas_width - bg_width) // 2, 0)
                    case "下方置中": paste_pos = ((canvas_width - bg_width) // 2, canvas_height - bg_height)
                    case "左側置中": paste_pos = (0, (canvas_height - bg_height) // 2)
                    case "右側置中": paste_pos = (canvas_width - bg_width, (canvas_height - bg_height) // 2)
                    case "延展":
                        resized_bg = self.background_image.resize((int(canvas_width), int(canvas_height)), Image.Resampling.LANCZOS)
                        img.paste(resized_bg, (0, 0), resized_bg)
                    case _:
                        logger.warning(f"無效的背景對齊參數 '{background_alignment}'，使用預設右下角。")
                        paste_pos = (canvas_width - bg_width, canvas_height - bg_height)
                
                if paste_pos:
                    img.paste(self.background_image, paste_pos, self.background_image)
            except Exception as e:
                logger.error(f"處理背景圖片失敗: {e}", exc_info=True)

        # --- 4. 繪製 Logo ---
        if self.logo_image:
            try:
                logo_available_width = canvas_width - (config.IMG_OFFSET_X + config.LOGO_PADDING_PX) * 2
                logo_available_height = config.LOGO_AREA_HEIGHT_PX - config.LOGO_PADDING_PX * 2
                logo_scaled = self.logo_image.copy()
                logo_scaled.thumbnail((logo_available_width, logo_available_height), Image.Resampling.LANCZOS)
                
                logo_paste_x = (canvas_width - logo_scaled.width) // 2
                logo_paste_y = config.IMG_OFFSET_Y_TOP + config.LOGO_PADDING_PX + (logo_available_height - logo_scaled.height) // 2
                img.paste(logo_scaled, (int(logo_paste_x), int(logo_paste_y)), logo_scaled)
            except Exception as e:
                logger.error(f"繪製 LOGO 失敗: {e}", exc_info=True)
                
        # --- 5. 巢狀輔助函式 ---
        def draw_multiline_text(center_pos, lines, fonts, fills):
            """
            在指定中心點繪製多行文字，支援每行使用不同的字型和顏色。
            """
            center_x, center_y = center_pos
            line_heights = []
            line_spacing = 4 

            for i, line in enumerate(lines):
                if line:
                    try:
                        _, top, _, bottom = fonts[i].getbbox(line)
                        h = bottom - top
                    except AttributeError:
                        _, h = fonts[i].getsize(line)
                    line_heights.append(h)

            total_height = sum(line_heights) + line_spacing * (len(lines) - 1)
            current_y = center_y - total_height / 2

            for i, line in enumerate(lines):
                if line:
                    line_height = line_heights[i]
                    draw_y = current_y + line_height / 2
                    if table_type == "blocked":
                        pass
                    else:
                        draw.text(
                            (center_x, draw_y), 
                            line, 
                            fill=fills[i], 
                            font=fonts[i], 
                            anchor="mm", 
                            align="center"
                        )
                    current_y += line_height + line_spacing

        # --- 6. 繪製桌位 ---
        grid_drawing_origin_y = config.IMG_OFFSET_Y_TOP + config.LOGO_AREA_HEIGHT_PX + config.IMG_OFFSET_Y_TOP_GRID
        
        for table_id, info in all_tables_data.items():
            if not (info and isinstance(info.get("position"), list) and len(info["position"]) == 2):
                continue
                
            grid_x, grid_y = info["position"]
            center_x = config.IMG_OFFSET_X + grid_x * config.IMG_SCALE + config.IMG_SCALE // 2
            center_y = grid_drawing_origin_y + (grid_content_height - (grid_y * config.IMG_SCALE + config.IMG_SCALE // 2))
            
            is_highlighted = (table_id.upper() == target_seat_id.upper())
            table_type = info.get("type", "normal")
            color = config.TABLE_COLOR_MAP.get(table_type, config.TABLE_COLOR_MAP["normal"])
            radius = config.TABLE_RADIUS_PX
            
            bbox = (center_x - radius, center_y - radius, center_x + radius, center_y + radius)

            if is_highlighted and table_type != "blocked":
                outer_bbox = (bbox[0] - config.HIGHLIGHT_THICKNESS_PX, bbox[1] - config.HIGHLIGHT_THICKNESS_PX, 
                              bbox[2] + config.HIGHLIGHT_THICKNESS_PX, bbox[3] + config.HIGHLIGHT_THICKNESS_PX)
                draw.ellipse(outer_bbox, fill=config.HIGHLIGHT_COLOR)

            if table_type == "blocked":
                # 可以選擇繪製一個交叉或其他標記來表示柱子
                pass 
            else:
                draw.ellipse(bbox, fill=color)
        
            table_id_text = f"{table_id.upper()}"
            display_name = info.get("displayName", "")
            text_rules = info.get("text_rules", "default")

            # 準備預設的繪製參數
            base_text_color = config.HIGHLIGHT_TEXT_COLOR if is_highlighted else config.TEXT_COLOR_ON_TABLE
            dn_text_color = config.HIGHLIGHT_TEXT_COLOR if is_highlighted else config.TEXT_COLOR_ON_TABLE_DISPLAYNAME
            
            # --- 規則判斷 ---

            # 規則 1: 只顯示 displayName (唯一會隱藏桌號的規則)
            if "name_only" in text_rules and display_name:
                lines = [display_name]
                fonts = [self.font_medium] 
                fills = [base_text_color]
            
            # 預設情況：顯示桌號和 displayName
            else:
                lines = [table_id_text, display_name]
                fonts = [self.font_medium, self.font_medium]
                fills = [base_text_color, dn_text_color]

                # 如果沒有 displayName，則只顯示桌號
                if not display_name:
                    lines = [table_id_text]
                    fonts = [self.font_large]
                    fills = [base_text_color]
                else:
                    # --- 在此處應用所有針對 displayName 的附加規則 (使用 if 而非 elif 以便疊加) ---

                    # 規則 2: displayName 縮小字型 (例如 > 4 個字)
                    # "text_rules": "shrink_at_4"
                    if "shrink_at_4" in text_rules and len(display_name) > 4:
                        fonts[1] = self.font_small # 將 displayName 字型改為小

                    # 規則 3: displayName 強制換行 (例如在第 2 個字後)
                    # "text_rules": "wrap_at_2" (會將 "女方親戚" 變成 "女方\n親戚")
                    if "wrap_at_2" in text_rules and len(display_name) > 2:
                        lines = [table_id_text, display_name[:2], display_name[2:]]
                        fonts = [self.font_medium, self.font_medium, self.font_medium]
                        fills = [base_text_color, dn_text_color, dn_text_color]

                    if "wrap_at_3" in text_rules and len(display_name) > 3:
                        lines = [table_id_text, display_name[:3], display_name[3:]]
                        fonts = [self.font_medium, self.font_medium, self.font_medium]
                        fills = [base_text_color, dn_text_color, dn_text_color]

                    if "wrap_at_4" in text_rules and len(display_name) > 4:
                        lines = [table_id_text, display_name[:4], display_name[4:]]
                        fonts = [self.font_medium, self.font_medium, self.font_medium]
                        fills = [base_text_color, dn_text_color, dn_text_color]

                    # 規則 4: displayName 使用細體
                    # "text_rules": "thin"
                    if "thin" in text_rules:
                        fonts[1] = self.font_thin

                    # 規則 5: displayName 加上裝飾性符號
                    # "text_rules": "decorate_star"
                    if "decorate_star" in text_rules:
                        lines[1] = f"⭐ {lines[1]} ⭐"

                    # 規則 6: displayName 轉為全大寫 (適用英文)
                    # "text_rules": "uppercase"
                    if "uppercase" in text_rules:
                        lines[1] = lines[1].upper()

                    # 規則 7: 根據關鍵字改變 displayName 顏色 (例如 VIP)
                    # "text_rules": "color_by_vip"
                    if "color_by_vip" in text_rules and "VIP" in lines[1].upper():
                        fills[1] = "gold" # 或者其他你定義的 VIP 顏色

                    # 規則 8: 截斷超長文字 (這是最後的保險)
                    # "text_rules": "truncate_at_8"
                    if "truncate_at_8" in text_rules and len(display_name) > 8:
                        # 如果已經被 wrap_at_2 處理過，lines[1] 可能會變短，此處判斷原始長度
                        lines[1] = display_name[:7] + "…"
                        
                    # --- 統一呼叫繪製函式 ---
                    draw_multiline_text((center_x, center_y), lines, fonts, fills)

        # --- 7. 繪製底部提示文字 ---
        if target_seat_id.upper()== 'T1' :
            prompt = f"{guest_name} 您好，您的座位安排在主桌"
        else:
            prompt = f"{guest_name} 您好，您的座位是 {target_seat_id.upper()}"
        if target_seat_id.upper() not in all_tables_data:
            prompt = f"{guest_name} 您好，座位 {target_seat_id.upper()} 未找到"
        
        prompt_y = canvas_height - (config.IMG_OFFSET_Y_BOTTOM / 2)
        draw.text((canvas_width / 2, prompt_y), prompt, fill=config.TEXT_COLOR_PROMPT, font=self.font_large, anchor="mm")
        
        # --- 8. 儲存並回傳圖片 ---
        image_io = io.BytesIO()
        img.save(image_io, 'PNG')
        image_io.seek(0)
        return image_io
