from http.server import BaseHTTPRequestHandler
import json
import requests
from datetime import datetime
import os  # <--- 這裡一定要匯入 os 模組

# ================= 設定區 =================
# 這裡改成從「環境變數」讀取，而不是寫死在程式碼裡
# 如果你在 Vercel 設定的名字不一樣，請修改括號裡的字
CLIENT_ID = os.environ.get('TDX_ID')      
CLIENT_SECRET = os.environ.get('TDX_SECRET')

# 車站代碼
STATION_ID = '5000' # 屏東
DEST_ID = '5050'    # 潮州

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()

        # 檢查是否有抓到環境變數
        if not CLIENT_ID or not CLIENT_SECRET:
            error_msg = "<h1>Error: 找不到環境變數 (Environment Variables)</h1>"
            error_msg += "<p>請確認 Vercel 設定裡的變數名稱是否為 <b>TDX_ID</b> 和 <b>TDX_SECRET</b></p>"
            self.wfile.write(error_msg.encode('utf-8'))
            return

        # 1. 取得 Token
        token = self.get_auth_token()
        if not token:
            self.wfile.write("<h1>Error: 無法取得 Token (帳號密碼可能錯誤)</h1>".encode('utf-8'))
            return

        # 2. 抓取資料
        data = self.fetch_data_auto(token)
        
        # 3. 生成並回傳 HTML
        html = self.generate_html(data)
        self.wfile.write(html.encode('utf-8'))
        return

    def get_auth_token(self):
        try:
            auth_url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
            headers = {'content-type': 'application/x-www-form-urlencoded'}
            data = {'grant_type': 'client_credentials', 'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET}
            resp = requests.post(auth_url, headers=headers, data=data)
            return resp.json().get('access_token')
        except:
            return None

    def fetch_data_auto(self, token):
        today = datetime.now().strftime('%Y-%m-%d')
        headers = {'authorization': f'Bearer {token}'}
        # 嘗試 V2 Station API
        url = f"https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/DailyTrainTimetable/Station/{STATION_ID}/{today}"
        try:
            r = requests.get(url, headers=headers)
            if r.status_code == 200:
                return r.json()
        except:
            pass
        return []

    def generate_html(self, raw_data):
        current_time = datetime.now().strftime('%H:%M')
        schedule = []
        if isinstance(raw_data, dict):
            raw_data = raw_data.get('StationTimetables', [])
            
        for item in raw_data:
            try:
                info = item.get('TrainInfo', {})
                if info.get('Direction') != 0: continue # 只留順行
                
                departure_time = ""
                for stop in item.get('StopTimes', []):
                    if stop.get('DepartureTime'):
                        departure_time = stop.get('DepartureTime')
                        break
                
                train_no = info.get('TrainNo', '')
                train_type = info.get('TrainTypeName', {}).get('Zh_tw', '')
                dest = info.get('EndingStationName', {}).get('Zh_tw', '')
                
                if departure_time:
                    schedule.append({'time': departure_time, 'no': train_no, 'type': train_type, 'dest': dest})
            except:
                continue
                
        schedule.sort(key=lambda x: x['time'])

        list_html = ""
        count = 0
        for train in schedule:
            if train['time'] >= current_time:
                count += 1
                list_html += f"""
                <div class="card">
                    <div class="time">{train['time']}</div>
                    <div class="info">
                        <div class="dest">往 {train['dest']}</div>
                        <div class="type">{train['type']} ({train['no']}次)</div>
                    </div>
                </div>"""
        
        if count == 0:
            list_html = "<p style='text-align:center'>目前沒有車次</p>"

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>屏東火車時刻</title>
            <style>
                body {{ font-family: sans-serif; padding: 20px; background: #eee; }}
                .card {{ background: white; padding: 15px; margin-bottom: 10px; border-radius: 8px; display: flex; justify-content: space-between; align-items: center; border-left: 5px solid #009688; }}
                .time {{ font-size: 1.5em; font-weight: bold; }}
                .info {{ text-align: right; }}
                .dest {{ color: #007bff; font-weight: bold; }}
                .type {{ color: #666; font-size: 0.9em; }}
            </style>
        </head>
        <body>
            <h2 style="text-align:center">屏東 ➔ 潮州 ({current_time})</h2>
            {list_html}
        </body>
        </html>
        """
