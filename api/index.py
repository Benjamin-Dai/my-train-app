import requests
import json
import time
from datetime import datetime

# ================= 設定區 =================
# 請記得填入你的 ID 和 Secret
CLIENT_ID = '你的CLIENT_ID' 
CLIENT_SECRET = '你的CLIENT_SECRET'

# 車站代碼 (屏東=5000, 潮州=5050)
STATION_ID = '5000'
DEST_ID = '5050'

# 確保日期正確 (格式 YYYY-MM-DD)
TODAY = datetime.now().strftime('%Y-%m-%d')

# ================= 候選網址清單 (自動嘗試) =================
CANDIDATE_URLS = [
    # 1. V2 車站時刻表 (最穩)
    f"https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/DailyTrainTimetable/Station/{STATION_ID}/{TODAY}",
    # 2. V2 起點-終點 (OD)
    f"https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/DailyTrainTimetable/OD/{STATION_ID}/to/{DEST_ID}/{TODAY}",
    # 3. V3 車站時刻表
    f"https://tdx.transportdata.tw/api/basic/v3/Rail/TRA/DailyTrainTimetable/Station/{STATION_ID}/{TODAY}"
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
    print(f"🔍 正在尋找可用的 API 網址...")
    
    for url in CANDIDATE_URLS:
        try:
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                print(f"✅ 成功連線！")
                data = response.json()
                # 統一格式：轉成列表回傳
                if isinstance(data, list): return data
                elif 'StationTimetables' in data: return data['StationTimetables']
                elif 'TrainTimetables' in data: return data['TrainTimetables']
                else: return data
        except:
            continue
            
    print("❌ 所有路徑都失敗，無法取得資料。")
    return []

def parse_and_fix(train_data):
    schedule = []
    
    for item in train_data:
        try:
            # 兼容不同 API 結構
            info = item.get('TrainInfo', {})
            if not info: info = item 
            
            # 1. 取得基本資訊
            train_no = info.get('TrainNo', '未知')
            
            # 2. 安全取得中文名稱
            def safe_name(obj, key):
                val = obj.get(key)
                if isinstance(val, dict): return val.get('Zh_tw', '未知')
                return str(val) if val else '未知'

            train_type = safe_name(info, 'TrainTypeName')
            dest_name = safe_name(info, 'EndingStationName')
            
            # 3. 取得發車時間
            departure_time = ""
            stop_times = item.get('StopTimes', [])
            
            if len(stop_times) == 1: # 車站 API
                departure_time = stop_times[0].get('DepartureTime')
            else: # OD API
                for stop in stop_times:
                    if stop.get('StationID') == STATION_ID:
                        departure_time = stop.get('DepartureTime')
                        break
            
            # 4. 過濾：只留往南 (Direction=0)
            direction = info.get('Direction')
            if direction is not None and int(direction) != 0:
                continue 

            if departure_time:
                schedule.append({
                    'type': train_type,
                    'no': train_no,
                    'time': departure_time,
                    'dest': dest_name
                })
            
        except:
            continue

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
        <title>屏東往潮州</title>
        <style>
            body {{ font-family: sans-serif; padding: 20px; background: #eee; }}
            .card {{ background: white; padding: 15px; margin-bottom: 10px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); display: flex; justify-content: space-between; align-items: center; border-left: 5px solid #009688; }}
            .time {{ font-size: 1.5em; font-weight: bold; color: #333; }}
            .info {{ text-align: right; }}
            .dest {{ color: #007bff; font-weight: bold; font-size: 1.1em; }}
            .type {{ font-size: 0.9em; color: #666; }}
            h2 {{ text-align: center; color: #555; }}
        </style>
    </head>
    <body>
        <h2>屏東 ➔ 潮州 ({current_time})</h2>
    """
    
    count = 0
    for train in schedule:
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

    html_content += "</body></html>"
    
    # 【關鍵修改】：這裡直接存成 "index.html"
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"🎉 成功！已生成 index.html (包含 {count} 班車)。請上傳這個檔案！")

# ================= 主程式 =================
if __name__ == "__main__":
    token = get_auth_token()
    if token:
        raw_data = fetch_data_auto(token)
        if raw_data:
            clean_schedule = parse_and_fix(raw_data)
            generate_html(clean_schedule)
        else:
            print("無法取得資料。")
