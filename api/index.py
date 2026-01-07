import requests
import json
import time
from datetime import datetime

# ================= 設定區 =================
CLIENT_ID = '你的CLIENT_ID' 
CLIENT_SECRET = '你的CLIENT_SECRET'

# 車站代碼
STATION_ID = '5000'     # 屏東站
TODAY = datetime.now().strftime('%Y-%m-%d') 

# 【關鍵改變】：改回使用「車站時刻表」API (一定抓得到資料)
URL = f"https://tdx.transportdata.tw/api/basic/v3/Rail/TRA/DailyTrainTimetable/Station/{STATION_ID}/{TODAY}"

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
        print(f"正在抓取屏東站 ({TODAY}) 所有車次...")
        response = requests.get(URL, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            # 注意：車站 API 的 Key 叫做 'StationTimetables'
            trains_list = data.get('StationTimetables', [])
            print(f"✅ API 連線成功！共抓到 {len(trains_list)} 筆資料 (包含南北向)。")
            return trains_list
        else:
            print(f"❌ API 請求失敗: {response.status_code}")
            return []
    except Exception as e:
        print(f"連線發生錯誤: {e}")
        return []

def parse_and_sort_trains(train_data):
    schedule = []
    print("正在過濾往潮州方向的車次...")
    
    for item in train_data:
        try:
            info = item['TrainInfo']
            
            # 1. 過濾方向：0 = 順行 (通常是往潮州/台東)，1 = 逆行 (往高雄/台北)
            # 在屏東站，Direction 0 絕大多數是往南(潮州)
            direction = info.get('Direction', -1)
            if direction != 0: 
                continue # 跳過往北的車

            train_no = info['TrainNo']
            
            # 2. 安全讀取中文名稱
            train_type = info.get('TrainTypeName', {}).get('Zh_tw', '一般車')
            dest_name = info.get('EndingStationName', {}).get('Zh_tw', '未知終點')

            # 3. 取得發車時間
            # Station API 的時間通常在 StopTimes 列表裡，且通常只有一筆(就是本站)
            departure_time = ""
            if 'StopTimes' in item:
                for stop in item['StopTimes']:
                    if stop['StationID'] == STATION_ID:
                        departure_time = stop['DepartureTime']
                        break
            
            if not departure_time:
                continue

            schedule.append({
                'type': train_type,
                'no': train_no,
                'time': departure_time,
                'dest': dest_name
            })
            
        except Exception as e:
            # 稍微印出錯誤方便除錯，但不中斷
            # print(f"略過一筆: {e}")
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
        <title>屏東往南時刻表</title>
        <style>
            body {{ font-family: sans-serif; padding: 20px; background: #fafafa; color: #333; }}
            h2 {{ text-align: center; color: #444; }}
            .card {{ background: white; padding: 15px; margin-bottom: 12px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); display: flex; justify-content: space-between; align-items: center; border-left: 5px solid #28a745; }}
            .time {{ font-size: 1.6em; font-weight: 700; color: #2c3e50; }}
            .info {{ text-align: right; }}
            .dest {{ color: #007bff; font-weight: bold; font-size: 1.1em; }}
            .type {{ font-size: 0.85em; color: #777; }}
            .past {{ opacity: 0.5; border-left-color: #ccc; filter: grayscale(100%); }}
        </style>
    </head>
    <body>
        <h2>🚆 屏東 ➔ 潮州/台東 ({current_time} 更新)</h2>
    """
    
    valid_count = 0
    for train in schedule:
        # 標記已過期的車
        is_past = train['time'] < current_time
        css_class = "card past" if is_past else "card"
        
        # 這裡設定：只顯示未來的車 (若想測試可把 if 拿掉)
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
        html_content += "<p style='text-align:center; padding:20px;'>今天剩下的時間沒有往南的車囉！</p>"

    html_content += "</body></html>"
    
    with open("train_schedule.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"✅ 成功生成網頁！(篩選後剩餘 {valid_count} 班車)")

# ================= 主程式 =================
if __name__ == "__main__":
    token = get_auth_token()
    if token:
        raw_data = get_train_data(token)
        if raw_data:
            clean_schedule = parse_and_sort_trains(raw_data)
            generate_html(clean_schedule)
