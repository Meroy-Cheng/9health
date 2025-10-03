import datetime
import traceback
import os, io, json, hashlib
from PIL import Image
from . import my_db
import pandas as pd
import numpy as np
import base64
import dataframe_image as dfi
import tempfile
#import logging
import re
from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt

from linebot import LineBotApi, WebhookParser
# https://medium.com/@pearl3904/linebot%E5%AF%A6%E4%BD%9C-%E6%A9%9F%E5%99%A8%E4%BA%BA%E5%82%B3%E9%80%81%E7%9A%84%E8%A8%8A%E6%81%AF%E7%A8%AE%E9%A1%9E%E5%A4%A7%E5%BD%99%E6%95%B4-89201c2167fd#c258
# from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from linebot.models import (
    MessageEvent, TextSendMessage, StickerSendMessage, TemplateSendMessage,
    ConfirmTemplate, MessageAction, ButtonsTemplate, URIAction,
    ImageSendMessage, CarouselTemplate, CarouselColumn,
    #  QuickReply, QuickReplyButton,
    # PostbackAction, DatetimePickerAction,
)
# print("TOKEN:", settings.LINE_CHANNEL_ACCESS_TOKEN)
# print("SECRET:", settings.LINE_CHANNEL_KEY)
line_bot_api = LineBotApi(settings.LINE_CHANNEL_ACCESS_TOKEN)
parser = WebhookParser(settings.LINE_CHANNEL_KEY)
# handler = WebhookHandler(settings.LINE_CHANNEL_KEY)

flag_inp_phone_number = False
# Webhook 使用 9health-test，圖片 URL 使用 9health-hash
webhook_base_url = "https://selab-service.iecs.fcu.edu.tw/9health-test"
image_base_url = "https://selab-service.iecs.fcu.edu.tw/9health-test"

def get_static_dir():
    # 使用伺服器的實際儲存路徑
    return settings.STATIC_ROOT

def stable_png_bytes(src_bytes: bytes, max_side: int = 1024) -> bytes:
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

def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def ensure_dir(p: str):
    os.makedirs(p, exist_ok=True)


def input_phone_number_and_2DB(msg, user_id, DB_cls):    # 輸入電話號碼
    global flag_inp_phone_number
    #print('電話flag', flag_inp_phone_number)
    #return TextSendMessage(text=f'輸入的是 {msg}，長度={len(msg)}')

    # Todo: a bug -> 0920370048 (似乎是太多0造成的?)
    if len(msg) != 10:
        flag_inp_phone_number = True
        return TextSendMessage(text='手機號碼（例如：0918123456）的長度錯誤，請重新輸入。')
    elif msg[:2] != '09':
        flag_inp_phone_number = True
        return TextSendMessage(text='手機號碼（例如：0918123456）的前兩碼為09，請重新輸入。')
    elif msg.isnumeric():   # Check if all characters are numeric
        flag_inp_phone_number = False
        curr_time = datetime.datetime.now().replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")

        if DB_cls.check_user_exist(user_id):
            DB_cls.update_one_by_id('User_Information', 'Phone_number', msg, user_id)
            DB_cls.update_one_by_id('User_Information', 'Flag_update_data', 1, user_id)
        else:
            data = [user_id, msg, 1, curr_time, 0, curr_time]
            DB_cls.insert_one('User_Information', data)

        buttons_template = ButtonsTemplate(
            title='點擊按鈕可開啟問卷網頁',
            # thumbnail_image_url='https://storage.googleapis.com/你的圖片連結.png',
            text='要瀏覽問卷首頁的「隱私權條款」',
            actions = [
                # DatetimePickerAction(label='選擇日期', data='date', mode='date')
                # PostbackAction(label='打開鍵盤', data='button_clicked', text="您的輸入：", inputOption="openKeyboard")
                URIAction(label='前往填寫問卷', uri='https://ppt.cc/fNWiSx')
                ]
        )
        return TemplateSendMessage(alt_text='出生年', template=buttons_template)
    else:
        flag_inp_phone_number = True
        return TextSendMessage(text='手機號碼（例如：0918123456）錯誤，請重新輸入。')

def show_comment(type_, user_id, DB_cls):
    if type_ == "感興趣主題":
        item = DB_cls.select_one_by_id('User_Questionnaire', '健康目標', user_id, order='Time_fill_out')
        return f"您感興趣主題是『{item}』，建議如下：\n {DB_cls.select_one_by_id(type_, item)}"
    elif type_ == "日常小困擾":
        item = DB_cls.select_one_by_id('User_Questionnaire', '日常小困擾', user_id, order='Time_fill_out')
        return f"您日常小困擾是『{item}』，建議如下：\n {DB_cls.select_one_by_id(type_, item)}"
    elif type_ == "常吃的飲食":
        item = DB_cls.select_one_by_id('User_Questionnaire', '常吃飲食搭配', user_id, order='Time_fill_out')
        lst = [x.strip() for x in item.split(",")]
        comment = f"您常吃的飲食種類有 {len(lst)} 項，建議如下：\n\n"
        for x in lst:
            comment = comment + DB_cls.select_one_by_id(type_, x) + "\n"

        return comment

def handle_text_message(msg, user_id, DB_cls, use_chinese):
    global flag_inp_phone_number
    #print("===訊息:", msg)
    print(f"=== handle_text_message 收到: {msg} from {user_id}")
    print("KEY=", repr(settings.LINE_CHANNEL_KEY))
    print("TOKEN=", repr(settings.LINE_CHANNEL_ACCESS_TOKEN))


    if msg == '!文字':
        text_msg = TextSendMessage(text='~ 測試：文字訊息 ~')
        sticker_msg = StickerSendMessage(package_id=6136, sticker_id=10551378)
        return [text_msg, sticker_msg]

    # 填問卷(確認模板)
    elif msg == '＞＞填問卷 ':    # 確認模板只能有兩個選項！
        confirm_template = ConfirmTemplate(
            text='能請您協助「營養及飲食習慣調查問卷」嗎？'if use_chinese else 'Could you please help us with the questionnaire?',
            actions=[
                MessageAction(label='是' if use_chinese else 'Yes', text='＞＞進行調查問卷：是 '),
                MessageAction(label='否' if use_chinese else 'No', text='＞＞進行調查問卷：否 ')
            ]
        )
        return TemplateSendMessage(alt_text='是否進行問卷' if use_chinese else 'Conduct questionnaire', template=confirm_template)
    elif msg == '＞＞進行調查問卷：是 ':
        flag_inp_phone_number = True
        #print('===電話flag:', flag_inp_phone_number)
        return_text = '感謝您的配合，請先輸入手機號碼（例如：0918123456）。此號碼僅做連結調查問卷之用，請安心輸入。' if use_chinese else 'Thank you for your cooperation. Please enter your mobile phone number first. This number is only used to link to the questionnaire.'
        return TextSendMessage(text=return_text)
    elif msg == '＞＞進行調查問卷：否 ':
        flag_inp_phone_number = False
        return_text = '實在太可惜了！問卷填答結果可協助我們提供更好的服務。' if use_chinese else 'What a shame! The questionnaire results can help us provide better service.'
        return TextSendMessage(text=return_text)
    elif flag_inp_phone_number:  # 輸入電話號碼
        return input_phone_number_and_2DB(msg, user_id, DB_cls)
    elif (len(msg)==10) and (msg[0]=='0'):  # 輸入電話號碼
        return input_phone_number_and_2DB(msg, user_id, DB_cls)

    # 看建議(輪播模板)
    elif msg == '＞＞看建議 ':    # 輪播模板(Carousel Template)
        # check user data (retrieve from Google or not)
        if not DB_cls.check_update_user_questionnaire(user_id):
            return TextSendMessage(text='~ 請先填寫問卷([圖文選單]->[填問卷]) ~' if use_chinese else '~ Please fill in the questionnaire first ~')

        carousel_template = CarouselTemplate(columns=[
            CarouselColumn(
                text='依問卷填答結果，給予個人化建議',  # 這個一定要有
                #title='感興趣主題',
                thumbnail_image_url='https://selab-service.iecs.fcu.edu.tw/9health/static/CarouselTemplate_img1.jpg',
                actions=[
                    MessageAction(label='感興趣主題', text='＞＞看建議：感興趣主題 ')
                ]
            ),
            CarouselColumn(
                text='依問卷填答結果，給予個人化建議',
                #title='常吃的飲食',
                thumbnail_image_url='https://selab-service.iecs.fcu.edu.tw/9health/static/CarouselTemplate_img2.jpg',
                actions=[
                    MessageAction(label='常吃的飲食', text='＞＞看建議：常吃的飲食 ')
                ]
            ),
            CarouselColumn(
                text='依問卷填答結果，給予個人化建議',
                #title='日常小困擾',
                thumbnail_image_url='https://selab-service.iecs.fcu.edu.tw/9health/static/CarouselTemplate_img3.jpg',
                actions=[
                    MessageAction(label='日常小困擾', text='＞＞看建議：日常小困擾 ')
                ]
            )
        ])
        return TemplateSendMessage(alt_text='依問卷填答結果的建議', template=carousel_template)
    elif msg == '＞＞看建議：感興趣主題 ':
        return TextSendMessage(text=f"{show_comment('感興趣主題', user_id, DB_cls)} \n\n 💡 可用『AI:』開頭來發問，例如：輸入『AI:要如何瘦身？』(發問後請稍等AI回覆)")
    elif msg == '＞＞看建議：常吃的飲食 ':
        return TextSendMessage(text=f"{show_comment('常吃的飲食', user_id, DB_cls)} \n\n 💡 可用『AI:』開頭來發問，例如：輸入『AI:要如何瘦身？』(發問後請稍等AI回覆)")
    elif msg == '＞＞看建議：日常小困擾 ':
        return TextSendMessage(text=f"{show_comment('日常小困擾', user_id, DB_cls)} \n\n 💡 可用『AI:』開頭來發問，例如：輸入『AI:要如何瘦身？』(發問後請稍等AI回覆)")

    # 估熱量(ChatGPT)
    elif msg == '＞＞估熱量 ':
        if not DB_cls.check_update_user_questionnaire(user_id):
            return TextSendMessage(text='~ 請先填寫問卷([圖文選單]->[填問卷]) ~')

        return TextSendMessage(text='＞＞請上傳一張餐食圖片 ')
        # text_msg = TextSendMessage(text='本功能未上線，敬請期待')
        # sticker_msg = StickerSendMessage(package_id=8525, sticker_id=16581290)
        # return [text_msg, sticker_msg]


    elif msg == '＞＞當日飲食分析 ':
        today_str = datetime.datetime.now().strftime("%Y%m%d")
        today_str_slash = datetime.datetime.now().strftime("%Y/%m/%d")

        static_dir = get_static_dir()
        user_prefix = user_id[:10]

        print(f"[DEBUG] 今日日期: {today_str}")
        print(f"[DEBUG] static 資料夾: {static_dir}")
        print(f"[DEBUG] user_prefix: {user_prefix}")

        # 找出今日符合 user 的所有分析結果圖
        pattern = re.compile(rf"^{today_str}.*{user_prefix}_result\.jpg$")
        matched_files = [f for f in os.listdir(static_dir) if pattern.match(f)]

        print(f"[DEBUG] 找到符合條件的檔案: {matched_files}")

        if not matched_files:
            return TextSendMessage(text="今天尚未上傳任何餐食圖片，請先拍照上傳餐點~")

        all_data = []  # 存放所有圖片解析後的結果

        # === 每張圖片分開丟 GPT 分析，避免漏資料 ===
        for file in matched_files:
            img_path = os.path.join(static_dir, file)
            print(f"[DEBUG] 準備讀取圖片: {img_path}")
            try:
                with open(img_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                gpt_images = [{
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
                }]

                completion = DB_cls.openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "你是一位專業營養師。請根據餐食的營養表格圖片，"
                                "逐一讀取表格中的數據，回傳 JSON 陣列。"
                                "結構必須是：[{\"名稱\":\"食物1 (FoodName)\",\"熱量\":float,"
                                "\"脂肪\":float,\"蛋白質\":float,\"碳水\":float,"
                                "\"纖維值\":float,\"鈣質\":float},...]。"
                                "不要加總，也不要產生【總計】。"
                                "每筆資料的名稱都要附上英文翻譯，例如：馬鈴薯 (Potato)。"
                            )
                        },
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "以下是餐食營養表格圖片，請輸出為 JSON："}
                            ] + gpt_images
                        }
                    ],
                    response_format={"type": "json_object"}
                )

                raw_reply = completion.choices[0].message.content
                print(f"[DEBUG] GPT 原始回覆 ({file}): {raw_reply[:200]}...")

                nutrition_list = json.loads(raw_reply)
                if isinstance(nutrition_list, dict):
                    # 偵測外層 key（例如 foods, data）
                    for key, value in nutrition_list.items():
                        if isinstance(value, list):
                            nutrition_list = value
                            break

                if isinstance(nutrition_list, list):
                    all_data.extend(nutrition_list)
                else:
                    print(f"[WARN] GPT 回傳格式非 list，跳過: {file}")

            except Exception as e:
                print(f"[ERROR] GPT 解析失敗 ({file}): {e}")

        if not all_data:
            return TextSendMessage(text="AI 分析失敗，請稍後再試。")

        # === DataFrame & 資料清理 ===
        df = pd.DataFrame(all_data)
        expected_cols = ['名稱','熱量','脂肪','蛋白質','碳水','纖維值','鈣質']
        for col in expected_cols:
            if col not in df.columns:
                df[col] = 0
                print(f"[DEBUG] 缺少欄位 {col}，補 0")
        df = df[expected_cols]

        # 🚨 移除 GPT 可能誤抓的「總計/小計」row
        df = df[~df['名稱'].str.contains("總計|小計", case=False, na=False)]

        # 🚀 相同名稱合併
        df_grouped = df.groupby("名稱", as_index=False).sum(numeric_only=True)

        # 🚀 最後加總一行
        total_row = df_grouped.drop(columns=["名稱"]).sum(numeric_only=True).to_dict()
        total_row["名稱"] = "【總計（Total）】"
        df_grouped = pd.concat([df_grouped, pd.DataFrame([total_row])], ignore_index=True)

        print(f"[DEBUG] 最終 DataFrame（含總計）:\n{df_grouped}")

        # === 匯出 summary 圖片（固定檔名）===
        summary_name = f"{today_str}_{user_prefix}_summary.jpg"
        summary_path = os.path.join(static_dir, summary_name)

        df_grouped = df_grouped.round(1).astype(str)
        df_style = df_grouped.style.hide(axis="index") \
            .set_caption(f"{today_str_slash} 飲食總結（Estimated Daily Nutrition）")

        dfi.export(
            obj=df_style,
            filename=summary_path,
            dpi=150,
            table_conversion='matplotlib',
            fontsize=12,
            max_cols=-1,
            max_rows=-1
        )

        full_image_url = f"{image_base_url}/static/{summary_name}"
        print(f"[DEBUG] 匯出 summary 圖片: {summary_path}")
        print(f"[DEBUG] 圖片可用 URL: {full_image_url}")

        # === GPT 一句飲食建議 ===
        totals_dict = df_grouped.iloc[-1].to_dict()
        completion_advice = DB_cls.openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "你是一位專業營養師，請根據數據只輸出一句簡短的飲食建議。"},
                {"role": "user", "content": f"今日總攝取量：{totals_dict}"}
            ]
        )
        gpt_reply = completion_advice.choices[0].message.content.strip()

        print(f"[DEBUG] GPT 建議: {gpt_reply}")

        return [
            ImageSendMessage(
                original_content_url=full_image_url,
                preview_image_url=full_image_url
            ),
            TextSendMessage(text=gpt_reply)
        ]


    if re.match(r'^\s*ai[:：]', msg, re.IGNORECASE):
        if not DB_cls.check_update_user_questionnaire(user_id):
            return TextSendMessage(
                text='~ 請先填寫問卷([圖文選單]->[填問卷]) ~' if use_chinese else '~ Please fill in the questionnaire first ~'
            )

        normalized_msg = msg.replace("：", ":").strip()
        question = normalized_msg.split(":", 1)[1].strip()
        return TextSendMessage(text=DB_cls.inquire_GPT(user_id, question))

    # --- 新增 fallback：其他文字也當成問題 ---
    if DB_cls.check_update_user_questionnaire(user_id):
        return TextSendMessage(text=DB_cls.inquire_GPT(user_id, msg))
    else:
        return TextSendMessage(
            text='~ 請先填寫問卷([圖文選單]->[填問卷]) ~' if use_chinese else '~ Please fill in the questionnaire first ~'
        )

@csrf_exempt
def callback(request):
    print("=== 有進入 callback ===")
    try:
        if request.method == 'POST':
            print("== 收到一個 webhook 事件 ==") 
            signature = request.META['HTTP_X_LINE_SIGNATURE']
            body = request.body.decode('utf-8')
            # DB = my_db.cls_db_helper(base_url)
            DB = my_db.cls_db_helper()


            try:
                events = parser.parse(body, signature)
            except InvalidSignatureError:
                print("Invalid signature. Please check your channel access token/channel secret.")
                return HttpResponseForbidden()
            except LineBotApiError:
                print("Line Bot Api Error.")
                return HttpResponseBadRequest()

            for event in events:
                print(f"== event: {event}")    
                if isinstance(event, MessageEvent):
                    user_id = event.source.user_id
                    profile = line_bot_api.get_profile(user_id)
                    user_name = profile.display_name
                    user_lang = profile.language
                    curr_time = datetime.datetime.now().replace(microsecond=0)
                    print(f"收到 user_id: {user_id}")
                    print(f"== profile 內容: {profile}")

                    use_chinese = True if 'zh' in user_lang else False

                    if DB.check_user_exist(user_id):
                        DB.update_one_by_id(
                            'User_Information',
                            'Time_send_msg',
                            curr_time.strftime("%Y-%m-%d %H:%M:%S"),
                            user_id
                        )

                    # === 處理文字訊息 ===
                    if event.message.type == "text":
                        print(f"== 收到訊息內容: {event.message.text}")
                        reply_msg = handle_text_message(event.message.text, user_id, DB, use_chinese)
                        if reply_msg:
                            line_bot_api.reply_message(event.reply_token, reply_msg)

                    # === 處理圖片訊息 ===
                    elif event.message.type == "image":
                        if not DB.check_update_user_questionnaire(user_id):
                            return_text = '~ 請先填寫問卷([圖文選單]->[填問卷]) ~' if use_chinese else '~ Please fill in the questionnaire first ~'
                            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=return_text))
                            continue

                        # 呼叫 process_image：自動生成檔名 + 檢查 hash 快取
                        image_name, cache_hit = DB.process_image(line_bot_api, event, user_id, curr_time)

                        if cache_hit:
                            # 快取命中，直接使用快取結果
                            result_img_name = image_name[:-4] + "_result.jpg"
                            print(f"[DEBUG] 使用快取結果: {result_img_name}")
                        else:
                            # 沒有快取，呼叫 ChatGPT 分析
                            result_img_name = DB.inquire_ChatGPT(
                                image_name,
                                user_id,
                                curr_time.strftime("%Y-%m-%d %H:%M:%S")
                            )

                        # 回傳結果
                        full_image_url = f"{image_base_url}/static/{result_img_name}"
                        print(f"[DEBUG] 準備傳送圖片 URL: {full_image_url}")

                        # 檢查圖片檔案是否存在
                        from django.conf import settings as django_settings
                        if hasattr(django_settings, 'STATIC_ROOT') and django_settings.STATIC_ROOT:
                            static_dir = django_settings.STATIC_ROOT
                        else:
                            static_dir = "/var/www/html/django/9health/static"

                        image_path = os.path.join(static_dir, result_img_name)
                        print(f"[DEBUG] 檢查圖片路徑: {image_path}")
                        if os.path.exists(image_path):
                            file_size = os.path.getsize(image_path)
                            print(f"[DEBUG] 圖片檔案存在，大小: {file_size} bytes")

                            # LINE Bot 圖片要求：HTTPS, 檔案大小 < 10MB, 格式 JPG/PNG
                            if file_size > 10 * 1024 * 1024:  # 10MB
                                print(f"[ERROR] 圖片太大: {file_size} bytes > 10MB")
                                line_bot_api.reply_message(event.reply_token,
                                    TextSendMessage(text="圖片檔案過大，無法傳送"))
                                continue
                        else:
                            print(f"[ERROR] 圖片檔案不存在: {image_path}")
                            line_bot_api.reply_message(event.reply_token,
                                TextSendMessage(text="圖片檔案產生失敗，請稍後再試"))
                            continue

                        try:
                            line_bot_api.reply_message(
                                event.reply_token,
                                ImageSendMessage(
                                    original_content_url = full_image_url,
                                    preview_image_url    = full_image_url
                                )
                            )
                            print(f"[DEBUG] 圖片傳送成功")
                        except Exception as e:
                            print(f"[ERROR] 圖片傳送失敗: {e}")
                            line_bot_api.reply_message(event.reply_token,
                                TextSendMessage(text=f"圖片傳送失敗: {str(e)}"))
                        continue

                elif event.type == "follow":
                    user_id = event.source.user_id
                    profile = line_bot_api.get_profile(user_id)
                    user_name = profile.display_name

                    if use_chinese:
                        confirm_template = ConfirmTemplate(
                            text = f'您好，{user_name}，歡迎加入『9健康』，能請您協助「營養及飲食習慣調查問卷」嗎？',
                            actions=[
                                MessageAction(label='是', text='進行調查問卷：是'),
                                MessageAction(label='否', text='進行調查問卷：否')
                            ]
                        )
                        reply_msg = TemplateSendMessage(alt_text='是否進行問卷', template=confirm_template)
                    else:
                        confirm_template = ConfirmTemplate(
                            text = f'Hello, {user_name}. Welcome to join『9健康』. Could you please help us with the questionnaire?',
                            actions=[
                                MessageAction(label='Yes', text='進行調查問卷：是'),
                                MessageAction(label='No', text='進行調查問卷：否')
                            ]
                        )
                        reply_msg = TemplateSendMessage(alt_text='Conduct questionnaire', template=confirm_template)

                    line_bot_api.reply_message(event.reply_token, reply_msg) 

                elif event.type == "unfollow":
                    print("unfollow")
                elif event.type == "join":
                    print("加入群組")
                elif event.type == "leave":
                    print("離開群組")

            return HttpResponse()
        else:
            print("POST only.")
            return HttpResponseBadRequest()
    except Exception as e:
        print("== webhook 處理錯誤 ==")
        traceback.print_exc()
        return HttpResponse("Internal Server Error", status=500)