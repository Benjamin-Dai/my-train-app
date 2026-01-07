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
# 取得今天日期 (格式 YYYY-MM-DD)
TODAY = datetime.now().strftime('%Y-%m-%d') 

# 【關鍵修正】：切換回最穩定的 V2 API
# V2 的路徑結構簡單且穩定，不易出錯
URL = f"https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/DailyTrainTimetable/OD/{ORIGIN_ID}/to/{DEST_ID}/{TODAY}"

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
        print(f"正在連線 V2 API: {URL}")
        response = requests.get(URL, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            # V2 的資料結構通常直接就是列表，或是包在 TrainTimetables 裡
            # 為了保險，我們做個檢查
            if isinstance(data, list):
                trains_list = data
            else:
                trains_list = data.get('TrainTimetables', [])
                
            print(f"✅ API 連線成功！共抓到 {len(trains_list)} 班車。")
            return trains_list
        else:
            print(f"❌ API 請求失敗: {response.status_code}")
            print(f"錯誤訊息: {response.text}")
            return []
    except Exception as e:
        print(f"連線發生錯誤: {e}")
        return []

def parse_and_sort_trains(train_data):
    schedule = []
    print("正在解析資料...")
    
    for item in train_data:
        try:
            info = item.get('TrainInfo', {})
            train_no = info.get('TrainNo', '未知')
            
            # V2 與 V3 的欄位名稱大同小異，但保險起見使用 .get
            train_type = info.get('TrainTypeName', {}).get('Zh_tw', '不明車種')
            dest_name = info.get('EndingStationName', {}).get('Zh_tw', '未知終點')
            
            # V2 OD API 回傳的 StopTimes 通常包含「起點」與「終點」的時刻
            departure_time = ""
            stop_times = item.get('StopTimes', [])
            
            for stop in stop_times:
                if stop.get('StationID') == ORIGIN_ID:
                    departure_time = stop.get('DepartureTime')
                    break
            
            # 如果沒抓到時間，可能是資料格式稍微不同，嘗試直接抓
            if not departure_time and len(stop_times) > 0:
                 # 有時候 OD API 的第一筆就是出發站
                 if stop_times[0].get('StationID') == ORIGIN_ID:
                     departure_time = stop_times[0].get('DepartureTime')

            if not departure_time:
                continue

            schedule.append({
                'type': train_type,
                'no': train_no,
                'time': departure_time,
                'dest': dest_name
            })
            
        except Exception as e:
            print(f"解析失敗 (跳過): {e}")
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
        <title>屏東 -> 潮州 (V2)</title>
        <style>
            body {{ font-family: -apple-system, sans-serif; padding: 20px; background: #eef2f5; color: #333; }}
            h2 {{ text-align: center; color: #2c3e50; }}
            .card {{ background: white; padding: 16px; margin-bottom: 12px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); display: flex; justify-content: space-between; align-items: center; }}
            .time {{ font-size: 1.8em; font-weight: 800; color: #333; }}
            .info {{ text-align: right; }}
            .dest {{ color: #007aff; font-weight: 600; font-size: 1.1em; }}
            .type {{ font-size: 0.85em; color: #888; margin-top: 4px; }}
            .past {{ opacity: 0.4; filter: grayscale(1); }}
        </style>
    </head>
    <body>
        <h2>🚆 屏東 ➔ 潮州 ({current_time})</h2>
    """
    
    valid_count = 0
    for train in schedule:
        is_past = train['time'] < current_time
        # 只顯示未來的車
        if not is_past:
            valid_count += 1
            html_content += f"""
            <div class="card">
                <div class="time">{train['time']}</div>
                <div class="info">
                    <div class="dest">往 {train['dest']}</div>
                    <div class="type">{train['type']} ({train['no']}次)</div>
                </div>
            </div>
            """
    
    if valid_count == 0:
        html_content += "<p style='text-align:center; margin-top:30px;'>目前時段已無發車。</p>"

    html_content += "</body></html>"
    
    with open("train_schedule.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"✅ 成功生成網頁！(train_schedule.html)")

# ================= 主程式 =================
if __name__ == "__main__":
    token = get_auth_token()
    if token:
        raw_data = get_train_data(token)
        if raw_data:
            clean_schedule = parse_and_sort_trains(raw_data)
            generate_html(clean_schedule)
