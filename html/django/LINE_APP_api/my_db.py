import pymysql, pygsheets, json, os
import pandas as pd
import numpy as np
import dataframe_image as dfi
import re

from django.conf import settings
from openai import OpenAI
from PIL import Image
from io import StringIO
import io, hashlib, base64
from pydantic import BaseModel
from dotenv import load_dotenv

import matplotlib.font_manager as fm
import matplotlib.pyplot as plt


noto_font_path = '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
myfont = fm.FontProperties(fname=noto_font_path)
plt.rcParams['font.family'] = myfont.get_name()
plt.rcParams['font.family'] = ['Noto Sans CJK TC', 'Noto Sans CJK JP', 'Noto Sans CJK SC', myfont.get_name()]

# print([f.name for f in fm.fontManager.ttflist if "Noto" in f.name])
# print("myfont.get_name():", myfont.get_name())

# def dfi_export_with_font(df_style, filename):
#     dfi.export(
#         obj=df_style,
#         filename=filename,
#         dpi=150,
#         table_conversion='matplotlib',
#         font_properties=myfont,  # 關鍵在這裡
#     )


db_settings = {
    "host": "140.134.25.68",
    "port": 3308,
    "user": "root",
    "password": "fcu@selab@232",
    "db": "django_db",
    "charset": "utf8"
}

load_dotenv(encoding="utf-8")
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

class cls_db_helper:
    def __init__(self):
        self.db_conn = pymysql.connect(**db_settings)
        self.openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
        self.base_url = "https://selab-service.iecs.fcu.edu.tw/9health-test"
        self.static_dir = settings.STATIC_ROOT
        print(f"[DEBUG] 使用伺服器 static 路徑: {self.static_dir}")
        os.makedirs(self.static_dir, exist_ok=True)

    def stable_png_bytes(self, src_bytes: bytes, max_side: int = 1024) -> bytes:
        """將影像決定性轉檔成 PNG，避免 EXIF/壓縮差異造成同圖不同雜湊。"""
        im = Image.open(io.BytesIO(src_bytes)).convert("RGB")
        w, h = im.size
        if max(w, h) > max_side:
            if w >= h:
                new_w, new_h = max_side, int(h * max_side / w)
            else:
                new_h, new_w = max_side, int(w * max_side / h)
            im = im.resize((new_w, new_h), Image.BILINEAR)
        buf = io.BytesIO()
        im.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    def check_user_exist(self, user_id):
        try:
            with self.db_conn.cursor() as cursor:
                sql = f"Select Exists(Select * From User_Information Where User_ID='{user_id}')"
                cursor.execute(sql)
                if (cursor.fetchone()[0] >= 1):  # exist in db
                    return True
                else:
                    return False
        except Exception as ex:
            print("=== ERROR", ex)
            print("===", sql)
            self.db_conn.rollback()

    def update_one_by_id(self, table, column, new_data, user_id):
        try:
            with self.db_conn.cursor() as cursor:
                sql = f"Update {table} Set {column}='{new_data}' Where User_ID='{user_id}'"
                cursor.execute(sql)
                self.db_conn.commit()
        except Exception as ex:
            print("=== ERROR", ex)
            print("===", sql)
            self.db_conn.rollback()

    def select_one_by_id(self, table, column, user_id="", order=""):
        try:
            with self.db_conn.cursor() as cursor:
                if user_id == "":
                    sql = f"Select Comment From Show_Comment Where Type='{table}' And Item='{column}'"
                else:
                    if order:
                        sql = f"Select {column} From {table} Where User_ID='{user_id}' Order by Time_fill_out Desc"
                    else:
                        sql = f"Select {column} From {table} Where User_ID='{user_id}'"
                cursor.execute(sql)
                return cursor.fetchone()[0]     # cursor returns as ('111',)
        except Exception as ex:
            print("=== ERROR", ex)
            print("===", sql)
            self.db_conn.rollback()

    def insert_one(self, table, data):
        try:
            data = [f"'{x}'" for x in data]

            with self.db_conn.cursor() as cursor:
                sql = f"Insert Into {table} Values({','.join(data)})"
                cursor.execute(sql)
                self.db_conn.commit()
        except Exception as ex:
            print("=== ERROR", ex)
            print("===", sql)
            self.db_conn.rollback()

    def time_conversion(self, time):
        # google datetime: yyyy/M/dd tt h:mm:ss
        t = time.strip().split(' ')

        if "上午" in time:
            if len(t[2]) == 7:
                return t[0] + " 0" + t[2]
            else:
                return t[0] + " " + t[2]
        else:
            if t[2][:2] == "12":
                return t[0] + " " + t[2]
            else:
                tmp = t[2].split(':')
                tmp[0] = str(int(tmp[0]) + 12)
                t[2] = ':'.join(tmp)
                return t[0] + " " + t[2]

    def check_update_user_questionnaire(self, user_id):
        if self.check_user_exist(user_id):
            if self.select_one_by_id('User_Information', 'Flag_update_data', user_id):
                try:
                    with self.db_conn.cursor() as cursor:
                        phone_number = self.select_one_by_id('User_Information', 'Phone_number', user_id)
                        # Python 串接 GoogleSheet 新增、讀取、更新和刪除 https://www.maxlist.xyz/2018/09/25/python_googlesheet_crud/
                        # gc = pygsheets.authorize(service_account_file=r'/var/www/html/django/LINE_APP_api/google_sheet_key.json')
                        gc = pygsheets.authorize(service_account_file='/app/LINE_APP_api/google_sheet_key.json')
                        worksheet = gc.open_by_url("https://docs.google.com/spreadsheets/d/1KloBZ-2WHKIaRmrXDC5f6MXz_rErQG0_pGbeMOiek9Q/edit?gid=1209608055#gid=1209608055")[0]
                        df = pd.DataFrame(worksheet.get_all_records())
                        df_result = df[df.iloc[:, 7] == int(phone_number[1:])]
                        if df_result.empty: # 在 google sheet 沒找到手機號碼
                            return False
                        else:
                            time = self.time_conversion(df_result.iloc[-1, 0])
                            questionnaire_data = [f"'0'", f"'{user_id}'", f"'{time}'"] + [f"'{x}'" for x in df_result.iloc[-1, 2:]]
                            questionnaire_data[8] = f"'{phone_number}'"
                            sql = f"Insert Into User_Questionnaire Values({','.join(questionnaire_data)})"
                            #print("===", sql)
                            cursor.execute(sql)
                            self.db_conn.commit()

                        sql = f"Update User_Information Set Flag_update_data=0 Where User_ID='{user_id}'"
                        cursor.execute(sql)
                        self.db_conn.commit()
                        return True
                except Exception as ex:
                    print("=== ERROR", ex)
                    print("===", sql)
                    self.db_conn.rollback()
            else:
                return True

        else:   # 回應填寫問卷先
            return False


    def inquire_ChatGPT(self, image_name, user_id, curr_time):
        # === 檔案命名 ===
        new_name = image_name[:-4] + '_result.jpg'
        result_path = os.path.join(self.static_dir, new_name)

        # 如果結果圖已存在 → 直接回傳
        if os.path.exists(result_path):
            print(f"[DEBUG] 快取命中: {new_name}")
            return new_name

        # === 讀取本地圖片並轉成 Base64 ===
        img_path = os.path.join(self.static_dir, image_name)
        with open(img_path, "rb") as f:
            image_bytes = f.read()
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        # === 定義回傳格式 ===
        class Nutrition(BaseModel):
            名稱: str
            熱量: float
            脂肪: float
            蛋白質: float
            碳水: float
            纖維值: float
            鈣質: float

        class Food(BaseModel):
            內容物: list[Nutrition]

        # === 呼叫 GPT ===
        completion = self.openai_client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是一位專業營養師與圖像分析專家，擅長評估圖片中食材的熱量與營養成分。"
                        "請嚴格按照以下規則分析：\n"
                        "1. 未檢出比例參考物或標準容器時，不要猜絕對大小，只能做「相對份量估計」，並必須附上假設條件與推估的不確定性。\n"
                        "2. 若偵測到品牌、常見便當盒、紙碗等標準容器，需以既定尺寸推估體積與份量。\n"
                        "3. 當拍攝角度非正上方，需說明可能的低估偏差並給出合理的校正區間（如+5%~+50%）。\n"
                        "4. 若辨識到便當盒/紙盒或貼紙上有可辨識的店家名稱、品牌、Logo，必須使用網路查詢官方網站或菜單，引用官方公布的營養成分資料；若有找到，直接以官方數據為主，並註明來源。\n"
                        "5. 回答時，**請先列出你判斷出的假設條件、參考依據與不確定性，再給出各項食材營養成分明細，最後給出總計。**\n"
                        "6. 回答需分步驟推理並詳細說明每個推論依據。\n"
                        "7. 請遵守格式：每個食材標明名稱、熱量、脂肪、蛋白質、碳水、纖維值、鈣質。\n"
                        "8. 名稱必須為：中（英文)格式。\n"
                        "【分析推理過程】(詳述你的判斷、假設、依據，務必寫得詳細)\n"
                    )
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "請根據上述規則分析這張圖片內所有可見食材，列出名稱(中英文)、熱量、脂肪、蛋白質、碳水、纖維值、鈣質。"
                                "名稱必須為：中（英文)格式。"
                                "表個最下方加入「－般成人每日應攝取約1,000毫克鈣質；膳食纖維的每日建議量則為25至35公克。」"
                                "對每一個項目都需說明推理過程與來源。"
                            )
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_b64}"
                            }
                        }
                    ]
                }
            ],
            response_format=Food
        )

        # === 解析 GPT 結果 ===
        try:
            # 使用 parse 方法時，內容已經是結構化的
            parsed_result = completion.choices[0].message.parsed
            # print("[DEBUG] GPT 結構化結果:", parsed_result)

            # 轉換 Pydantic 物件為字典列表，再序列化為 JSON
            nutrition_list = [item.model_dump() for item in parsed_result.內容物]
            result = json.dumps(nutrition_list, ensure_ascii=False)
            # print("[DEBUG] 轉換後的 JSON:", result)

        except Exception as e:
            print(f"[ERROR] GPT 結果解析失敗: {e}")
            # 嘗試舊方法作為備援
            content = completion.choices[0].message.content
            print("[DEBUG] GPT 原始回傳:", content)
            json_2_dct = json.loads(content)
            result = json.dumps(json_2_dct["內容物"], ensure_ascii=False)

        # === DataFrame + 匯出成圖片 ===
        try:
            print(f"[DEBUG] 準備建立 DataFrame，數據: {result[:200]}...")
            df = pd.read_json(StringIO(result))
            print(f"[DEBUG] DataFrame 形狀: {df.shape}")
            print(f"[DEBUG] DataFrame 欄位: {df.columns.tolist()}")

            # 確保有資料
            if df.empty:
                raise ValueError("DataFrame 是空的")

            df.columns = pd.MultiIndex.from_arrays([
                ['食物', '熱量(kcal)', '脂肪(g)', '蛋白質(g)', '碳水(g)', '纖維值(g)', '鈣質(mg)'],
                ['Food', 'Calories (kcal)', 'Fat (g)', 'Protein (g)', 'Carbohydrates (g)', 'Fiber (g)', 'Calcium (mg)']
            ])

            # 計算總計（只對數值欄位）
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            total_row = ['【總計（total）】']
            for i in range(1, len(df.columns)):
                try:
                    total_row.append(df.iloc[:, i].sum())
                except:
                    total_row.append(0)

            df.loc[len(df)] = total_row

            df = df.round(1).astype(str)
            df_style = df.style.hide(axis="index") \
                .set_caption("估算結果僅供參考（The estimated results are for reference only.）")

            print(f"[DEBUG] 開始匯出圖片到: {result_path}")

            # 確保目錄存在
            os.makedirs(os.path.dirname(result_path), exist_ok=True)

            # 確保匯出為 JPG 格式，符合 LINE Bot 要求
            dfi.export(
                obj=df_style,
                filename=result_path,
                dpi=150,
                table_conversion='matplotlib',
                fontsize=12,
                max_cols=-1,
                max_rows=-1
            )

            # 檢查檔案是否成功建立
            if os.path.exists(result_path):
                file_size = os.path.getsize(result_path)
                print(f"[DEBUG] 圖片匯出成功! 檔案大小: {file_size} bytes")
            else:
                raise FileNotFoundError(f"圖片檔案建立失敗: {result_path}")

        except Exception as e:
            print(f"[ERROR] DataFrame 處理失敗: {e}")
            print(f"[DEBUG] 原始結果: {result}")
            raise e

        # === 存入資料庫 ===
        data = ['0', user_id, curr_time, new_name, result]
        self.insert_one('Food_Recognition', data)

        # === 建立 hash 快取副本（供未來相同圖片使用）===
        # 重新計算圖片 hash 以建立快取檔名
        img_path = os.path.join(self.static_dir, image_name)
        if os.path.exists(img_path):
            with open(img_path, "rb") as f:
                img_bytes = f.read()
            # 轉為標準格式再計算 hash
            png_bytes = self.stable_png_bytes(img_bytes)
            img_hash = self.sha256_hex(png_bytes)
            hash_prefix = img_hash[:16]

            # 建立 hash 快取檔案
            cache_result_name = f"{hash_prefix}_result.jpg"
            cache_result_path = os.path.join(self.static_dir, cache_result_name)

            if not os.path.exists(cache_result_path):
                import shutil
                shutil.copy2(result_path, cache_result_path)
                print(f"[DEBUG] 已建立快取副本: {cache_result_name}")

        return new_name
    
    def stable_png_bytes(self, src_bytes: bytes, max_side: int = 1024) -> bytes:
        """將影像決定性轉檔成 PNG，避免 EXIF/壓縮差異造成同圖不同雜湊。"""
        im = Image.open(io.BytesIO(src_bytes)).convert("RGB")
        w, h = im.size
        if max(w, h) > max_side:
            if w >= h:
                new_w, new_h = max_side, int(h * max_side / w)
            else:
                new_h, new_w = max_side, int(w * max_side / h)
            im = im.resize((new_w, new_h), Image.BILINEAR)
        buf = io.BytesIO()
        im.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    def sha256_hex(self, b: bytes) -> str:
        return hashlib.sha256(b).hexdigest()

    def process_image(self, line_bot_api, event, user_id, curr_time):
        # 下載圖片 bytes
        image_content = line_bot_api.get_message_content(event.message.id)
        raw_bytes = b''.join(chunk for chunk in image_content.iter_content())

        # 轉為標準 PNG bytes（避免 EXIF / 格式差異）
        png_bytes = self.stable_png_bytes(raw_bytes)
        img_hash = self.sha256_hex(png_bytes)

        # === 檔名設定 ===
        image_name = curr_time.strftime('%Y%m%d%H%M%S') + user_id[:10] + ".jpg"
        result_name = curr_time.strftime('%Y%m%d%H%M%S') + user_id[:10] + "_result.jpg"
        hash_txt_name = f"{img_hash}.txt"

        image_path = os.path.join(self.static_dir, image_name)
        result_path = os.path.join(self.static_dir, result_name)
        hash_txt_path = os.path.join(self.static_dir, hash_txt_name)

        # === Step 1: 檢查是否已有對應 hash.txt ===
        if os.path.exists(hash_txt_path):
            print(f"[DEBUG] 發現既有 hash.txt: {hash_txt_name}")
            with open(hash_txt_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # 從檔案找「分析結果檔名」
            result_file = None
            for line in lines:
                if line.startswith("分析結果檔名:"):
                    result_file = line.split(":", 1)[1].strip()
                    break

            if result_file:
                cached_result_path = os.path.join(self.static_dir, result_file)
                if os.path.exists(cached_result_path):
                    print(f"[DEBUG] 已找到對應分析結果圖: {result_file}")
                    if not os.path.exists(result_path):
                        import shutil
                        shutil.copy2(cached_result_path, result_path)
                        print(f"[DEBUG] 已複製 {result_file} → {result_name}")
                    return image_name, True

        # === Step 2: 沒有 hash.txt，檢查是否有快取圖片 ===
        cache_result_name = f"{img_hash}_result.jpg"
        cache_result_path = os.path.join(self.static_dir, cache_result_name)

        print(f"[DEBUG] Image hash = {img_hash}")
        print(f"[DEBUG] 檢查快取檔案: {cache_result_name}")

        if os.path.exists(cache_result_path):
            print(f"[DEBUG] Hash 快取命中！")
            if not os.path.exists(result_path):
                import shutil
                shutil.copy2(cache_result_path, result_path)
                print(f"[DEBUG] 已從快取複製到: {result_name}")

            # 生成完整 hash 名稱的紀錄檔
            with open(hash_txt_path, 'w', encoding='utf-8') as f:
                f.write(f"完整 Hash: {img_hash}\n")
                f.write(f"原始檔名: {image_name}\n")
                f.write(f"分析結果檔名: {result_name}\n")
                f.write(f"快取檔名: {cache_result_name}\n")
                f.write(f"用戶ID: {user_id}\n")
                f.write(f"上傳時間: {curr_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"快取狀態: 命中快取\n")
            print(f"[DEBUG] 已生成 hash 記錄檔: {hash_txt_name}")

            return image_name, True

        # Step 3: 沒有快取，存原圖
        print(f"[DEBUG] Hash 新圖片，開始AI分析")
        os.makedirs(os.path.dirname(image_path), exist_ok=True)
        im = Image.open(io.BytesIO(png_bytes)).convert("RGB")
        im.save(image_path, format="JPEG", quality=70, optimize=True)

        # 生成完整 hash 名稱的紀錄檔（先寫入原圖資訊，之後 AI 分析完成會再補結果圖）
        with open(hash_txt_path, 'w', encoding='utf-8') as f:
            f.write(f"完整 Hash: {img_hash}\n")
            f.write(f"原始檔名: {image_name}\n")
            f.write(f"分析結果檔名: {result_name}\n")
            f.write(f"快取檔名: {cache_result_name}\n")
            f.write(f"用戶ID: {user_id}\n")
            f.write(f"上傳時間: {curr_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        print(f"[DEBUG] 已生成 hash 記錄檔: {hash_txt_name}")

        return image_name, False

    def inquire_GPT(self, user_id, msg):
            try:
                with self.db_conn.cursor() as cursor:
                    sql = f"Select Sex,Birthday,Height,Weight From User_Questionnaire Where User_ID='{user_id}' Order by Time_fill_out Desc"
                    cursor.execute(sql)
                    #user_data = cursor.fetchone()[1]     # cursor returns as ('111',)
                    result = cursor.fetchone()
                    user_data = f"{result[0]}、生日{result[1]}、身高{result[2]}、體重{result[3]}"
            except Exception as ex:
                # print("=== ERROR", ex)
                # print("===", sql)
                # self.db_conn.rollback()
                user_data = ""

            #print('\n=== User_Data:', user_data, " ===\n")

            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "你是一個專業營養師，能精準且簡短的回覆與營養、健康、食品相關類型的問題，其餘類型問題一律回覆『抱歉、我只能回答與營養、健康相關問題』，若提問語言為英文則用英文回覆"},
                    {"role": "user", "content": f"我的資料：{user_data}，請問{msg}"},
                ],
                stream=False
            )

            #print(response.choices[0].message.content)
            return "" + response.choices[0].message.content

