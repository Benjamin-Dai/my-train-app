import requests
import json
import time
from datetime import datetime

# ================= 設定區 =================
CLIENT_ID = '你的CLIENT_ID' 
CLIENT_SECRET = '你的CLIENT_SECRET'

# 車站代碼 (屏東=5000)
STATION_ID = '5000'
TODAY = datetime.now().strftime('%Y-%m-%d')

# 使用 V2 車站時刻表 (最基礎的 API)
# 並且加上 ?format=JSON 確保伺服器知道我們要什麼
URL = f"https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/DailyTrainTimetable/Station/{STATION_ID}/{TODAY}?format=JSON"

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
    
    print(f"🔹 嘗試連線 URL: {URL}") # 印出來讓你檢查
    
    try:
        response = requests.get(URL, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            trains_list = data.get('StationTimetables', [])
            print(f"✅ 成功！抓到 {len(trains_list)} 筆資料 (含南北向)。")
            return trains_list
        else:
            print(f"❌ API 請求失敗: {response.status_code}")
            # 嘗試印出伺服器回傳的詳細錯誤訊息
            try:
                print(f"錯誤內容: {response.text}") 
            except:
                pass
            return []
    except Exception as e:
        print(f"連線發生錯誤: {e}")
        return []

def parse_and_sort_trains(train_data):
    schedule = []
    print("正在過濾往潮州 (南下) 的車次...")
    
    for item in train_data:
        try:
            # V2 Station API 的結構
            info = item.get('TrainInfo', {})
            direction = info.get('Direction', -1)
            
            # 屏東站：Direction 0 = 順行 (往潮州/台東/枋寮)
            # 我們只留順行的車
            if direction != 0:
                continue

            train_no = info.get('TrainNo', '未知')
            train_type = info.get('TrainTypeName', {}).get('Zh_tw', '一般車')
            dest_name = info.get('EndingStationName', {}).get('Zh_tw', '未知終點')
            
            # 取得時間
            departure_time = ""
            stop_times = item.get('StopTimes', [])
            if stop_times:
                # Station API 的 StopTimes 通常只有一筆(本站)，直接拿
                departure_time = stop_times[0].get('DepartureTime', '')

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
        <title>屏東南下時刻表</title>
        <style>
            body {{ font-family: sans-serif; padding: 20px; background: #fafafa; color: #333; }}
            h2 {{ text-align: center; }}
            .card {{ background: white; padding: 15px; margin-bottom: 10px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); display: flex; justify-content: space-between; align-items: center; border-left: 5px solid #28a745; }}
            .time {{ font-size: 1.5em; font-weight: bold; }}
            .info {{ text-align: right; }}
            .dest {{ color: #007bff; font-weight: bold; }}
            .type {{ font-size: 0.9em; color: #666; }}
        </style>
    </head>
    <body>
        <h2>屏東 ➔ 潮州/台東 ({current_time})</h2>
    """
    
    count = 0
    for train in schedule:
        # 只顯示現在以後的車
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
        html_content += "<p style='text-align:center'>今天沒車了或資料讀取完畢。</p>"
        
    html_content += "</body></html>"
    
    with open("train_schedule.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"✅ 網頁生成完畢！共列出 {count} 班未來車次。")

# ================= 主程式 =================
if __name__ == "__main__":
    token = get_auth_token()
    if token:
        raw_data = get_train_data(token)
        if raw_data:
            clean_schedule = parse_and_sort_trains(raw_data)
            generate_html(clean_schedule)
