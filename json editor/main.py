import json
import os
import pandas as pd
import argparse

# --- 集中管理預設結構與預設值 ---
# 在這裡定義兩種資料類型的完整欄位和預設值
# 這樣可以確保無論來源資料如何，輸出的結構都是固定的
DEFAULT_STRUCTURES = {
    "location": {
        "type": "normal",
        "displayName": "",
        "text_rules": "wrap_at_4"
    },
    "customer": {
        "category": "",
        "checked_in": False,
        "group_id": "",
        "name": "",
        "nickname": "",
        "phone": "",
        "pinyin": "",
        "project_id": "",
        "seat": "",
        "expected_count": "0",
        "checked_in_count": "0"
    }
}


def json_to_xlsx(json_file, output_file):
    """
    將 JSON 檔案轉換為 Excel 檔案。
    會根據預設結構補全欄位，確保輸出的 Excel 欄位完整。
    """
    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict):
        print("偵測到字典 (dictionary) 結構的 JSON，進行轉換...")
        result = []
        for key, value in data.items():
            if not isinstance(value, dict):
                continue
            
            entry = value.copy()
            entry["table_no"] = key

            position = entry.pop("position", [None, None])
            entry["position_x"] = position[0] if isinstance(position, list) and len(position) > 0 else None
            entry["position_y"] = position[1] if isinstance(position, list) and len(position) > 1 else None
            
            result.append(entry)
        
        if not result:
            print("❌ JSON 檔案中沒有可轉換的有效資料。")
            return
            
        df = pd.DataFrame(result)
        
        # --- 新增邏輯：確保所有預設欄位都存在於 DataFrame 中 ---
        expected_cols = ['table_no', 'position_x', 'position_y'] + list(DEFAULT_STRUCTURES["location"].keys())
        for col in expected_cols:
            if col not in df.columns:
                # 如果欄位不存在，就用預設值新增一整欄
                if col in ['position_x', 'position_y']:
                    df[col] = 0.0
                else:
                    df[col] = DEFAULT_STRUCTURES["location"].get(col, '')
        df = df[expected_cols] # 依照預設順序排列欄位

    elif isinstance(data, list):
        print("偵測到列表 (list) 結構的 JSON，進行轉換...")
        if not data:
            print("⚠️ JSON 檔案為空列表，將生成一個只有標題列的 Excel。")
            df = pd.DataFrame(columns=list(DEFAULT_STRUCTURES["customer"].keys()))
        else:
            df = pd.DataFrame(data)

        # --- 新增邏輯：確保所有預設欄位都存在於 DataFrame 中 ---
        expected_cols = list(DEFAULT_STRUCTURES["customer"].keys())
        for col in expected_cols:
            if col not in df.columns:
                df[col] = DEFAULT_STRUCTURES["customer"][col]
        df = df[expected_cols] # 依照預設順序排列欄位

    else:
        print(f"❌ 不支援的 JSON 結構類型：{type(data)}")
        return

    df.to_excel(output_file, index=False)
    print(f"✅ JSON 已成功轉換為 Excel，並確保了結構完整性：{output_file}")


def xlsx_to_json(xlsx_file, output_file):
    """
    將 Excel 檔案轉換為 JSON 檔案。
    會根據預設結構補全欄位，確保輸出的 JSON 結構完整。
    """
    try:
        df = pd.read_excel(xlsx_file)
    except FileNotFoundError:
        print(f"❌ 錯誤：找不到 Excel 檔案 '{xlsx_file}'")
        return
        
    df = df.where(pd.notna(df), None) # 將空值先統一為 None
    columns = set(df.columns)
    
    location_format_cols = {"table_no", "position_x", "position_y"}

    if location_format_cols.issubset(columns):
        print("偵測到「位置」格式的 Excel，轉換為字典結構 JSON...")
        output_data = {}
        location_defaults = DEFAULT_STRUCTURES["location"]
        for _, row in df.iterrows():
            if not row.get("table_no"):
                continue
            
            key = str(row["table_no"])
            pos_x = float(row["position_x"]) if row["position_x"] is not None else 0.0
            pos_y = float(row["position_y"]) if row["position_y"] is not None else 0.0
            
            item = {"position": [pos_x, pos_y]}
            
            # --- 新增邏輯：遍歷預設結構，確保每個 key 都存在 ---
            for field, default_value in location_defaults.items():
                # 如果 Excel 中有值且不為空，使用 Excel 的值，否則使用預設值
                item[field] = row.get(field) if row.get(field) is not None else default_value

            output_data[key] = item
    else:
        print("偵測到一般表格格式的 Excel，轉換為列表結構 JSON...")
        customer_defaults = DEFAULT_STRUCTURES["customer"]
        
        # --- 新增邏輯：確保所有預設欄位都存在於 DataFrame 中 ---
        for col, default in customer_defaults.items():
            if col not in df.columns:
                df[col] = default
        
        # 使用預設值字典來填充所有空值
        df = df.fillna(customer_defaults)
        
        # 進行嚴格的型別轉換，以符合原始 JSON 格式
        df['checked_in'] = df['checked_in'].astype(bool)
        df['expected_count'] = df['expected_count'].astype(str)
        df['checked_in_count'] = df['checked_in_count'].astype(str)
        
        output_data = df.to_dict(orient='records')
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=4, ensure_ascii=False)
    print(f"✅ Excel 已成功轉換為 JSON，並確保了結構完整性：{output_file}")


def convert_file(input_file):
    """根據副檔名自動調用對應的轉換函式。"""
    if not os.path.exists(input_file):
        print(f"❌ 錯誤：找不到檔案 '{input_file}'")
        return

    base_name = os.path.splitext(os.path.basename(input_file))[0]
    ext = os.path.splitext(input_file)[-1].lower()
    
    if ext == ".json":
        output_filename = f"{base_name}.xlsx"
        json_to_xlsx(input_file, output_filename)
    elif ext in [".xls", ".xlsx"]:
        output_filename = f"{base_name}.json"
        xlsx_to_json(input_file, output_filename)
    else:
        print(f"❌ 不支援的檔案格式，請提供 .json, .xls 或 .xlsx 結尾的檔案")


data_dir = os.path.dirname(__file__)
# --- 修改這行以測試您的檔案 ---
# file_name = "table_locations.json"
# file_name = "customer_list.json"
file_name = "customer_list.xlsx" # 您也可以用轉換後的 Excel 檔來反向測試

convert_file(os.path.join(data_dir, file_name))