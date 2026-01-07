import requests
import json
import time
from datetime import datetime

# ================= 設定區 =================
CLIENT_ID = '你的CLIENT_ID' 
CLIENT_SECRET = '你的CLIENT_SECRET'

# 車站代碼：屏東 (5000)
STATION_ID = '5000'
TODAY = datetime.now().strftime('%Y-%m-%d')

# 【關鍵】：這是最標準、最不可能出錯的 V2 車站時刻表網址
# (這應該就是你一開始抓到 197 筆資料的那個來源)
URL = f"https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/DailyTrainTimetable/Station/{STATION_ID}/{TODAY}"

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
    print(f"嘗試連線: {URL}")
    
    try:
        response = requests.get(URL, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            # 處理 V2 可能的回傳結構
            trains = data.get('StationTimetables', [])
            print(f"✅ 成功連線！共抓到 {len(trains)} 筆資料。")
            return trains
        else:
            print(f"❌ API 失敗: {response.status_code}")
            return []
    except Exception as e:
        print(f"連線錯誤: {e}")
        return []

def parse_and_sort_trains(train_data):
    schedule = []
    print("正在進行資料解析...")
    
    for item in train_data:
        try:
            # 1. 取得 TrainInfo，如果沒有就跳過
            info = item.get('TrainInfo', {})
            if not info: continue

            # 2. 過濾方向：屏東站 (5000)，Direction 0 是順行 (往潮州/台東)
            # 如果是 1 (逆行往高雄)，就跳過
            direction = info.get('Direction', -1)
            if direction != 0:
                continue

            # 3. 取得車次
            train_no = info.get('TrainNo', '未知')

            # 4. 【關鍵修復】：強力解析終點站
            # 嘗試從不同層級尋找中文站名，避免 ['未知']
            dest_name = "未知終點"
            if 'EndingStationName' in info:
                # 檢查是不是字典格式 {'Zh_tw': '潮州', ...}
                if isinstance(info['EndingStationName'], dict):
                    dest_name = info['EndingStationName'].get('Zh_tw', '未知')
                # 檢查是不是直接就是字串
                elif isinstance(info['EndingStationName'], str):
                    dest_name = info['EndingStationName']
            
            # 5. 取得車種
            train_type = "火車"
            if 'TrainTypeName' in info:
                if isinstance(info['TrainTypeName'], dict):
                    train_type = info['TrainTypeName'].get('Zh_tw', '火車')
            
            # 6. 取得發車時間 (屏東站的時間)
            departure_time = ""
            # V2 Station API 的 StopTimes 通常是一個清單，裡面只有本站的資料
            stop_times = item.get('StopTimes', [])
            if stop_times:
                departure_time = stop_times[0].get('DepartureTime', '')

            # 如果還是沒有時間，就跳過
            if not departure_time:
                continue

            # 加入清單
            schedule.append({
                'type': train_type,
                'no': train_no,
                'time': departure_time,
                'dest': dest_name
            })

        except Exception as e:
            # 遇到單筆資料異常不中斷，只印出錯誤
            print(f"解析略過一筆: {e}")
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
            body {{ font-family: sans-serif; padding: 20px; background: #f5f5f5; color: #333; }}
            h2 {{ text-align: center; margin-bottom: 20px; }}
            .card {{ background: white; padding: 15px; margin-bottom: 12px; border-radius: 8px; 
                     box-shadow: 0 2px 4px rgba(0,0,0,0.1); display: flex; justify-content: space-between; align-items: center; 
                     border-left: 5px solid #007bff; }}
            .time {{ font-size: 1.6em; font-weight: bold; color: #333; }}
            .info {{ text-align: right; }}
            .dest {{ color: #007bff; font-weight: bold; font-size: 1.1em; }}
            .type {{ font-size: 0.9em; color: #666; }}
            .no-data {{ text-align: center; padding: 20px; color: #777; }}
        </style>
    </head>
    <body>
        <h2>🚆 屏東 ➔ 潮州/台東 ({current_time})</h2>
    """
    
    count = 0
    for train in schedule:
        # 只顯示目前時間之後的車
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
        html_content += "<div class='no-data'>今天剩下的時間沒有往南的車囉！<br>(或是尚未抓到資料)</div>"

    html_content += "</body></html>"
    
    with open("train_schedule.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"✅ 網頁生成完畢！共列出 {count} 班未來車次。請開啟 train_schedule.html")

# ================= 主程式 =================
if __name__ == "__main__":
    token = get_auth_token()
    if token:
        # 1. 抓取資料
        raw_data = get_train_data(token)
        
        if raw_data:
            # 2. 解析資料 (這一步之前會出錯，現在修復了)
            clean_schedule = parse_and_sort_trains(raw_data)
            
            # 3. 檢查結果
            print(f"過濾後剩下 {len(clean_schedule)} 班往潮州方向的車。")
            
            # 4. 生成網頁
            generate_html(clean_schedule)
        else:
            print("沒有抓到原始資料 (API 回傳空值)。")
