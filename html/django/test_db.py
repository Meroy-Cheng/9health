
# MySQL 安裝及使用基本教學 https://hackmd.io/@MLwithbc/H1Dl6BYa_

import pymysql
#import charts
from datetime import datetime

# 資料庫參數設定
db_settings = {
    "host": "140.134.25.68",
    "port": 3308,
    "user": "root",
    "password": "fcu@selab@232",
    "db": "django_db",
    "charset": "utf8"
}

def testConnection():
    try:
        # 建立Connection物件
        conn = pymysql.connect(**db_settings)
        
        curr_time = datetime.now().replace(microsecond=0)

        print(f"Connection established at {curr_time}")
        # 建立Cursor物件
        # with conn.cursor() as cursor:
        #     command = "INSERT INTO User_Information VALUES (%s, %s, %s, %s, %s)"
        #     cursor.execute(command, ('22sttesttestesadsdttttttttttttttt', '0918123456', 2, curr_time, None))
        # # 儲存變更
        #     conn.commit()
        #     #result = cursor.detall()
        #     #print(result)
        
        print(datetime.now().replace(microsecond=0))
        print(datetime.today())
    except Exception as ex:
       print(f"Error: {ex}")

if __name__ == '__main__':
    testConnection()


