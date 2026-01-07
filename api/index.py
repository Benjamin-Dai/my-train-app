import requests
import json
import time
from datetime import datetime

# ================= 設定區 =================
# 請在此輸入你的 TDX API 金鑰
CLIENT_ID = '你的CLIENT_ID' 
CLIENT_SECRET = '你的CLIENT_SECRET'

# 車站代碼 (屏東=5000, 潮州=5050)
ORIGIN_ID = '5000'      # 起點：屏東
DEST_ID = '5050'        # 終點：潮州
TODAY = datetime.now().strftime('%Y-%m-%d') 

# 【修正處】：移除了錯誤的 "Inclusive" 路徑
# 正確的 OD (起點-終點) 查詢網址
URL = f"https://tdx.transportdata.tw/api/basic/v3/Rail/TRA/DailyTrainTimetable/OD/{ORIGIN_ID}/to/{DEST_ID}/{TODAY}"

# ================= 函式區 =================

def get_auth_token():
    """取得 TDX Access Token"""
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
    """抓取火車資料"""
    headers = {'authorization': f'Bearer {token}'}
    
    try:
        print(f"正在抓取 {TODAY} 從 屏東(5000) 往 潮州(5050) 的車次...")
        response = requests.get(URL, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            trains_list = data.get('TrainTimetables', [])
            print(f"API 回傳成功！共抓到 {len(trains_list)} 班車。")
            return trains_list
        else:
            print(f"API 請求失敗: {response.status_code}")
            print(f"錯誤訊息: {response.text}") # 印出詳細錯誤以便除錯
            return []
    except Exception as e:
        print(f"連線發生錯誤: {e}")
        return []

def parse_and_sort_trains(train_data):
    """解析資料並整理成我們需要的格式"""
    schedule = []
    
    for item in train_data:
        try:
            # 1. 取得車次基本資訊
            info = item['TrainInfo']
            train_no = info['TrainNo']
            train_type = info['TrainTypeName']['Zh_tw']
            dest_name = info['EndingStationName']['Zh_tw']
            
            # 2. 找到「屏東站」的發車時間
            departure_time = "未知"
            # 在 OD API 中，StopTimes 通常只會包含 起點 跟 終點 的資訊
            for stop in item['StopTimes']:
                if stop['StationID'] == ORIGIN_ID: 
                    departure_time = stop['DepartureTime']
                    break
            
            # 3. 存入列表
            schedule.append({
                'type': train_type,
                'no': train_no,
                'time': departure_time,
                'dest': dest_name
            })
            
        except KeyError as e:
            print(f"解析錯誤 (跳過一筆): 缺少欄位 {e}")
            continue

    # 依照時間排序
    schedule.sort(key=lambda x: x['time'])
    return schedule

def generate_html(schedule):
    """生成 HTML 檔案"""
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>屏東 -> 潮州 時刻表</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; padding: 20px; background: #f2f2f2; }}
            h2 {{ text-align: center; color: #333; }}
            .card {{ background: white; padding: 15px; margin-bottom: 12px; border-radius: 12px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); display: flex; justify-content: space-between; align-items: center; }}
            .time {{ font-size: 1.8em; font-weight: 800; color: #2c3e50; font-variant-numeric: tabular-nums; }}
            .info {{ text-align: right; }}
            .type {{ font-size: 0.9em; color: #666; margin-top: 4px; }}
            .dest {{ color: #007aff; font-weight: bold; font-size: 1.1em; }}
            .no-train {{ text-align: center; color: #888; margin-top: 30px; }}
        </style>
    </head>
    <body>
        <h2>屏東 ➔ 潮州 ({datetime.now().strftime('%H:%M')} 更新)</h2>
        <div id="list">
    """
    
    current_time = datetime.now().strftime('%H:%M')
    count = 0
    
    for train in schedule:
        # 只顯示目前時間之後的車
        if train['time'] >= current_time: 
            html_content += f"""
            <div class="card">
                <div class="time">{train['time']}</div>
                <div class="info">
                    <div class="dest">往 {train['dest']}</div>
                    <div class="type">{train['type']} ({train['no']}次)</div>
                </div>
            </div>
            """
            count += 1
    
    if count == 0:
        html_content += "<div class='no-train'>今天剩下的時間沒有車囉！<br>(或是尚未抓到資料)</div>"

    html_content += """
        </div>
    </body>
    </html>
    """
    
    with open("train_schedule.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"成功生成網頁！共列出 {count} 班有效車次。請開啟 train_schedule.html")

# ================= 主程式執行 =================
if __name__ == "__main__":
    token = get_auth_token()
    if token:
        raw_data = get_train_data(token)
        if raw_data:
            clean_schedule = parse_and_sort_trains(raw_data)
            generate_html(clean_schedule)
        else:
            print("沒有資料可顯示。")
