from http.server import BaseHTTPRequestHandler
import json
import requests
from datetime import datetime, timedelta
import os

# ================= 設定區 =================
# 1. 取得台灣時間 (UTC+8)
def get_taiwan_time():
    return datetime.utcnow() + timedelta(hours=8)

# 2. 讀取環境變數 (TDX_ID, TDX_SECRET)
CLIENT_ID = os.environ.get('TDX_ID')
CLIENT_SECRET = os.environ.get('TDX_SECRET')

# 3. 車站設定 (屏東 -> 潮州)
STATION_ID = '5000' 
DEST_ID = '5050'

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()

        # 取得當下台灣日期與時間
        tw_now = get_taiwan_time()
        today_date = tw_now.strftime('%Y-%m-%d')
        current_time_str = tw_now.strftime('%H:%M')

        # 1. 取得 Token
        token = self.get_auth_token()
        if not token:
            self.wfile.write("<h1>❌ 錯誤：無法取得 Token</h1><p>請確認 Vercel 環境變數 TDX_ID 與 TDX_SECRET 是否正確。</p>".encode('utf-8'))
            return

        # 2. 自動尋找可用資料 (萬能鑰匙邏輯)
        raw_data = self.fetch_data_auto(token, today_date)
        
        # 3. 生成網頁
        html = self.generate_html(raw_data, current_time_str)
        self.wfile.write(html.encode('utf-8'))

    def get_auth_token(self):
        try:
            auth_url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
            headers = {'content-type': 'application/x-www-form-urlencoded'}
            data = {'grant_type': 'client_credentials', 'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET}
            r = requests.post(auth_url, headers=headers, data=data)
            if r.status_code == 200:
                return r.json().get('access_token')
            return None
        except:
            return None

    def fetch_data_auto(self, token, date_str):
        headers = {'authorization': f'Bearer {token}'}
        
        # 準備四種網址，一個一個試
        urls = [
            # 路徑 1: V2 車站 (最常用)
            f"https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/DailyTrainTimetable/Station/{STATION_ID}/{date_str}",
            # 路徑 2: V2 起迄 (OD)
            f"https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/DailyTrainTimetable/OD/{STATION_ID}/to/{DEST_ID}/{date_str}",
            # 路徑 3: V3 車站
            f"https://tdx.transportdata.tw/api/basic/v3/Rail/TRA/DailyTrainTimetable/Station/{STATION_ID}/{date_str}",
            # 路徑 4: V3 起迄
            f"https://tdx.transportdata.tw/api/basic/v3/Rail/TRA/DailyTrainTimetable/OD/Inclusive/{STATION_ID}/to/{DEST_ID}/{date_str}"
        ]

        for url in urls:
            try:
                r = requests.get(url, headers=headers)
                if r.status_code == 200:
                    data = r.json()
                    # 只要抓到資料，轉成統一格式並回傳
                    if isinstance(data, list): return data
                    if 'StationTimetables' in data: return data['StationTimetables']
                    if 'TrainTimetables' in data: return data['TrainTimetables']
            except:
                continue
        return []

    def generate_html(self, raw_data, current_time):
        schedule = []
        
        # 解析資料 (相容各種格式)
        for item in raw_data:
            try:
                # 取得車次資訊
                info = item.get('TrainInfo', {})
                if not info: info = item # 有些格式直接就是 info
                
                # 過濾方向 (0=順行/南下, 1=逆行/北上)
                # 如果是 OD API，通常不需要濾方向，若是 Station API 則需要
                direction = info.get('Direction')
                if direction is not None and int(direction) != 0:
                    continue 

                # 取得時間
                departure_time = ""
                stop_times = item.get('StopTimes', [])
                
                # 策略: 找屏東站(5000)的發車時間
                if len(stop_times) == 1:
                    departure_time = stop_times[0].get('DepartureTime')
                else:
                    for stop in stop_times:
                        if stop.get('StationID') == STATION_ID:
                            departure_time = stop.get('DepartureTime')
                            break
                
                if not departure_time: continue

                # 取得名稱
                train_no = info.get('TrainNo', '')
                
                # 處理名稱可能是字典或字串的情況
                def get_name(obj, key):
                    val = obj.get(key)
                    if isinstance(val, dict): return val.get('Zh_tw', '')
                    return str(val) if val else ''

                train_type = get_name(info, 'TrainTypeName')
                dest = get_name(info, 'EndingStationName')

                schedule.append({
                    'time': departure_time,
                    'no': train_no,
                    'type': train_type,
                    'dest': dest
                })
            except:
                continue

        # 排序
        schedule.sort(key=lambda x: x['time'])

        # 生成卡片 HTML
        cards = ""
        count = 0
        for t in schedule:
            if t['time'] >= current_time:
                count += 1
                cards += f"""
                <div class="card">
                    <div class="time">{t['time']}</div>
                    <div class="info">
                        <div class="dest">往 {t['dest']}</div>
                        <div class="type">{t['type']} ({t['no']}次)</div>
                    </div>
                </div>
                """
        
        if count == 0:
            cards = "<div style='text-align:center; padding:20px; color:#666'>今天剩下的時間沒有車囉 (或資料讀取中)</div>"

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>屏東火車時刻</title>
            <style>
                body {{ font-family: "Microsoft JhengHei", sans-serif; padding: 20px; background: #eee; }}
                .container {{ max-width: 600px; margin: 0 auto; }}
                h2 {{ text-align: center; color: #333; }}
                .card {{ background: white; padding: 15px; margin-bottom: 10px; border-radius: 8px; 
                         box-shadow: 0 2px 4px rgba(0,0,0,0.1); display: flex; justify-content: space-between; align-items: center; 
                         border-left: 5px solid #009688; }}
                .time {{ font-size: 1.5em; font-weight: bold; color: #333; }}
                .info {{ text-align: right; }}
                .dest {{ color: #007bff; font-weight: bold; font-size: 1.1em; }}
                .type {{ font-size: 0.9em; color: #666; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>屏東 ➔ 潮州 ({current_time})</h2>
                {cards}
            </div>
        </body>
        </html>
        """
