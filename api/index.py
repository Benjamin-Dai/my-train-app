from http.server import BaseHTTPRequestHandler
import json
import requests
from datetime import datetime, timedelta
import os

# ================= 設定區 =================
CLIENT_ID = os.environ.get('TDX_ID')
CLIENT_SECRET = os.environ.get('TDX_SECRET')
STATION_ID = '5000' # 屏東
DEST_ID = '5050'    # 潮州

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()

        # 1. 取得台灣時間
        tw_now = datetime.utcnow() + timedelta(hours=8)
        today_date = tw_now.strftime('%Y-%m-%d')
        current_time = tw_now.strftime('%H:%M')

        # 2. 取得 Token
        token = self.get_auth_token()
        if not token:
            self.wfile.write("<h1>❌ Token 錯誤</h1>".encode('utf-8'))
            return

        # 3. 抓取資料 (直接用 OD 起迄站查詢，最準)
        # 網址：OD/屏東/to/潮州
        url = f"https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/DailyTrainTimetable/OD/{STATION_ID}/to/{DEST_ID}/{today_date}"
        
        raw_data = []
        try:
            r = requests.get(url, headers={'authorization': f'Bearer {token}'})
            if r.status_code == 200:
                data = r.json()
                raw_data = data.get('TrainTimetables', [])
        except:
            pass

        # 4. 解析資料 (寬鬆模式)
        schedule = []
        debug_log = f"原始資料: {len(raw_data)} 筆"

        for item in raw_data:
            try:
                info = item.get('TrainInfo', {})
                stop_times = item.get('StopTimes', [])
                
                # 找發車時間 (這裡做了修改：強制轉字串比較，避免格式錯誤)
                departure_time = ""
                for stop in stop_times:
                    # 不管是 int 還是 str，通通轉成 str 再比對 '5000'
                    if str(stop.get('StationID')) == STATION_ID:
                        departure_time = stop.get('DepartureTime')
                        break
                
                # 如果找不到發車時間，試試看有沒有可能是第一站
                if not departure_time and len(stop_times) > 0:
                     if str(stop_times[0].get('StationID')) == STATION_ID:
                         departure_time = stop_times[0].get('DepartureTime')

                if departure_time:
                    # 取得名稱
                    train_no = info.get('TrainNo', '')
                    train_type = info.get('TrainTypeName', {}).get('Zh_tw', '')
                    dest = info.get('EndingStationName', {}).get('Zh_tw', '')

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

        # 生成 HTML
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
            msg = f"目前沒有車次<br><small style='color:#999'>({debug_log}，但皆已離站)</small>"
            if len(raw_data) == 0: msg = "⚠️ 抓不到資料 (請確認日期或 API)"
            cards = f"<div style='text-align:center; padding:20px; color:#666'>{msg}</div>"

        html = f"""
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
        self.wfile.write(html.encode('utf-8'))

    def get_auth_token(self):
        try:
            auth_url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
            data = {'grant_type': 'client_credentials', 'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET}
            r = requests.post(auth_url, data=data)
            return r.json().get('access_token')
        except:
            return None
