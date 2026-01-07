import requests
import json
import time
from datetime import datetime

# ================= 設定區 =================
CLIENT_ID = '你的CLIENT_ID' 
CLIENT_SECRET = '你的CLIENT_SECRET'

# 車站代碼 (屏東=5000, 潮州=5050)
ORIGIN_ID = '5000'      
DEST_ID = '5050'        
TODAY = datetime.now().strftime('%Y-%m-%d') 

# 【關鍵修正】：把 'Inclusive' 加回來了！這是正確的 V3 OD 查詢路徑
URL = f"https://tdx.transportdata.tw/api/basic/v3/Rail/TRA/DailyTrainTimetable/OD/Inclusive/{ORIGIN_ID}/to/{DEST_ID}/{TODAY}"

# ================= 函式區 =================

def get_auth_token():
    auth_url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
    headers = {'content-type': 'application/x-www-form-urlencoded'}
    data = {
        'grant_type': 'client_credentials',
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET
    }
    try:
        response = requests.post(auth_url, headers=headers, data=data)
        response.raise_for_status()
        return response.json()['access_token']
    except Exception as e:
        print(f"取得 Token 失敗: {e}")
        return None

def get_train_data(token):
    headers = {'authorization': f'Bearer {token}'}
    try:
        print(f"正在連線 TDX (V3 OD Inclusive)...")
        response = requests.get(URL, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            trains_list = data.get('TrainTimetables', [])
            print(f"✅ API 連線成功！共抓到 {len(trains_list)} 筆原始車次資料。")
            return trains_list
        else:
            print(f"❌ API 請求失敗: {response.status_code}")
            return []
    except Exception as e:
        print(f"連線發生錯誤: {e}")
        return []

def parse_and_sort_trains(train_data):
    schedule = []
    print("正在解析資料...")
    
    for item in train_data:
        try:
            info = item['TrainInfo']
            train_no = info['TrainNo']
            
            # 安全讀取中文名稱
            train_type = info.get('TrainTypeName', {}).get('Zh_tw', '不明車種')
            dest_name = info.get('EndingStationName', {}).get('Zh_tw', '未知終點')
            
            # 關鍵：在所有停靠站中，找到「屏東(5000)」的「發車時間」
            departure_time = ""
            for stop in item['StopTimes']:
                if stop['StationID'] == ORIGIN_ID: # 找到屏東站
                    departure_time = stop['DepartureTime']
                    break
            
            # 如果這班車資料怪怪的，沒寫屏東時間，就跳過
            if not departure_time:
                continue

            schedule.append({
                'type': train_type,
                'no': train_no,
                'time': departure_time,
                'dest': dest_name
            })
            
        except Exception as e:
            print(f"解析單筆失敗: {e}")
            continue

    # 依照時間排序
    schedule.sort(key=lambda x: x['time'])
    return schedule

def generate_html(schedule):
    current_time = datetime.now().strftime('%H:%M')
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>屏東往潮州火車</title>
        <style>
            body {{ font-family: sans-serif; padding: 20px; background: #f4f4f4; color: #333; }}
            h2 {{ text-align: center; margin-bottom: 20px; }}
            .card {{ background: white; padding: 15px; margin-bottom: 15px; border-radius: 10px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); display: flex; justify-content: space-between; align-items: center; border-left: 5px solid #007bff; }}
            .past-train {{ opacity: 0.6; border-left-color: #ccc; display: none; }} /* 隱藏已過期的車 */
            .time {{ font-size: 1.6em; font-weight: bold; }}
            .info {{ text-align: right; }}
            .dest {{ color: #007bff; font-weight: bold; }}
            .type {{ font-size: 0.9em; color: #666; }}
            .status {{ font-size: 0.8em; color: #28a745; margin-top: 5px; }}
        </style>
    </head>
    <body>
        <h2>🚆 屏東 ➔ 潮州 ({current_time} 更新)</h2>
    """
    
    valid_count = 0
    for train in schedule:
        # 標記過期的車
        is_past = train['time'] < current_time
        css_class = "card past-train" if is_past else "card"
        
        # 只生成「未來」的車次到 HTML (若想看全部，可把 if 拿掉)
        if not is_past:
            valid_count += 1
            html_content += f"""
            <div class="{css_class}">
                <div class="time">{train['time']}</div>
                <div class="info">
                    <div class="dest">往 {train['dest']}</div>
                    <div class="type">{train['type']} ({train['no']}次)</div>
                </div>
            </div>
            """
    
    if valid_count == 0:
        html_content += "<p style='text-align:center'>今天剩下的時間沒有車囉！</p>"

    html_content += "</body></html>"
    
    with open("train_schedule.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"✅ 成功！已生成 train_schedule.html (包含 {valid_count} 班未發車次)")

# ================= 主程式 =================
if __name__ == "__main__":
    token = get_auth_token()
    if token:
        raw_data = get_train_data(token)
        if raw_data:
            clean_schedule = parse_and_sort_trains(raw_data)
            generate_html(clean_schedule)
