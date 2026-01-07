import requests
import json
import time
from datetime import datetime, timedelta

# ================= 設定區 =================
CLIENT_ID = '你的CLIENT_ID' 
CLIENT_SECRET = '你的CLIENT_SECRET'

# 車站代碼 (屏東=5000, 潮州=5050)
STATION_ID = '5000'
DEST_ID = '5050'

# 確保日期正確 (格式 YYYY-MM-DD)
TODAY = datetime.now().strftime('%Y-%m-%d')

# ================= 候選網址清單 (自動嘗試) =================
# 程式會依序嘗試這些網址，直到成功為止
CANDIDATE_URLS = [
    # 1. V2 車站時刻表 (最穩，您一開始應該就是用這個)
    f"https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/DailyTrainTimetable/Station/{STATION_ID}/{TODAY}",
    
    # 2. V3 車站時刻表 (新版)
    f"https://tdx.transportdata.tw/api/basic/v3/Rail/TRA/DailyTrainTimetable/Station/{STATION_ID}/{TODAY}",
    
    # 3. V2 起點-終點 (OD)
    f"https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/DailyTrainTimetable/OD/{STATION_ID}/to/{DEST_ID}/{TODAY}",
    
    # 4. V3 起點-終點 (OD Inclusive)
    f"https://tdx.transportdata.tw/api/basic/v3/Rail/TRA/DailyTrainTimetable/OD/Inclusive/{STATION_ID}/to/{DEST_ID}/{TODAY}"
]

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
        print(f"Token 取得失敗: {e}")
        return None

def fetch_data_auto(token):
    headers = {'authorization': f'Bearer {token}'}
    
    print(f"🔍 開始自動尋找可用的 API 網址 (日期: {TODAY})...")
    
    for i, url in enumerate(CANDIDATE_URLS):
        print(f"👉 嘗試第 {i+1} 條路徑...")
        try:
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                print(f"✅ 成功連線！使用路徑: {url}")
                data = response.json()
                
                # 統一資料格式：不管是哪種 API，都嘗試把它轉成列表
                if isinstance(data, list):
                    return data
                elif 'StationTimetables' in data:
                    return data['StationTimetables']
                elif 'TrainTimetables' in data:
                    return data['TrainTimetables']
                else:
                    print("⚠️ 格式無法識別，嘗試直接回傳...")
                    return data
            elif response.status_code == 404:
                print(f"❌ 失敗 (404 Not Found) - 跳過")
            else:
                print(f"❌ 失敗 (代碼 {response.status_code}) - 跳過")
                
        except Exception as e:
            print(f"❌ 連線錯誤: {e}")
            
    print("⛔ 所有路徑都嘗試失敗。請檢查日期或網路。")
    return []

def parse_and_fix(train_data):
    schedule = []
    print(f"📥 正在解析 {len(train_data)} 筆資料並修復欄位...")
    
    for item in train_data:
        try:
            # 兼容不同 API 的結構
            info = item.get('TrainInfo', {})
            if not info:
                # 有些 API 結構比較淺，直接就是 info
                info = item 
            
            # 1. 取得基本資訊
            train_no = info.get('TrainNo', '未知')
            
            # 2. 強力修復：車種 & 終點站
            # 有時候是字典 {'Zh_tw': '自強'}，有時候直接是字串 '自強'
            def safe_get_name(obj, key):
                val = obj.get(key)
                if isinstance(val, dict):
                    return val.get('Zh_tw', '未知')
                return str(val) if val else '未知'

            train_type = safe_get_name(info, 'TrainTypeName')
            dest_name = safe_get_name(info, 'EndingStationName')
            
            # 3. 取得發車時間 (屏東站 5000)
            departure_time = ""
            stop_times = item.get('StopTimes', [])
            
            # 策略 A: 如果 StopTimes 只有一筆 (Station API)，直接拿
            if len(stop_times) == 1:
                departure_time = stop_times[0].get('DepartureTime')
            # 策略 B: 如果有很多筆 (OD API)，找 StationID=5000
            else:
                for stop in stop_times:
                    if stop.get('StationID') == STATION_ID:
                        departure_time = stop.get('DepartureTime')
                        break
            
            # 4. 方向過濾 (如果有的話)
            # 0=順行(往南), 1=逆行(往北)
            direction = info.get('Direction')
            if direction is not None and int(direction) != 0:
                continue # 跳過往北的車

            # 如果沒抓到時間，就跳過
            if not departure_time:
                continue

            schedule.append({
                'type': train_type,
                'no': train_no,
                'time': departure_time,
                'dest': dest_name
            })
            
        except Exception as e:
            # print(f"解析略過: {e}")
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
        <title>屏東往潮州 (自動修復版)</title>
        <style>
            body {{ font-family: sans-serif; padding: 20px; background: #eee; }}
            .container {{ max-width: 600px; margin: 0 auto; }}
            .card {{ background: white; padding: 15px; margin-bottom: 10px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); display: flex; justify-content: space-between; align-items: center; border-left: 5px solid #009688; }}
            .time {{ font-size: 1.5em; font-weight: bold; color: #333; }}
            .info {{ text-align: right; }}
            .dest {{ color: #007bff; font-weight: bold; font-size: 1.1em; }}
            .type {{ font-size: 0.9em; color: #666; }}
            h2 {{ text-align: center; color: #555; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>屏東 ➔ 潮州 ({current_time})</h2>
    """
    
    count = 0
    for train in schedule:
        # 顯示未來的車
        if train['time'] >= current_time:
            count += 1
            html_content += f"""
            <div class="card">
                <div class="time">{train['time']}</div>
                <div class="info">
                    <div class="dest">往 {train['dest']}</div>
                    <div class="type">{train['type']} ({train['no']}次)</div>
                </div>
            </div>
            """
    
    if count == 0:
        html_content += "<p style='text-align:center'>今天剩下的時間沒有車囉！</p>"

    html_content += """
        </div>
    </body>
    </html>
    """
    
    with open("train_schedule.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"🎉 網頁生成成功！共列出 {count} 班車。請開啟 train_schedule.html")

# ================= 主程式 =================
if __name__ == "__main__":
    token = get_auth_token()
    if token:
        # 1. 自動尋找可用資料
        raw_data = fetch_data_auto(token)
        
        if raw_data:
            # 2. 解析並修復
            clean_schedule = parse_and_fix(raw_data)
            
            # 3. 生成網頁
            generate_html(clean_schedule)
        else:
            print("❌ 所有 API 都嘗試過了，無法取得資料。")
