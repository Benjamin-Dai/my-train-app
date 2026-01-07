from http.server import BaseHTTPRequestHandler
import json
import requests
from datetime import datetime
import os

# ================= 設定區 =================
# 程式會嘗試讀取這些變數
# 如果你的 Vercel 設定是用別的名字，請在這裡修改
ENV_ID_NAME = 'TDX_ID'
ENV_SECRET_NAME = 'TDX_SECRET'

CLIENT_ID = os.environ.get(ENV_ID_NAME)
CLIENT_SECRET = os.environ.get(ENV_SECRET_NAME)
STATION_ID = '5000' # 屏東

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()

        logs = [] # 用來記錄檢查過程
        
        # --- 檢查 1: 環境變數 ---
        has_id = "✅ 讀取成功" if CLIENT_ID else f"❌ 失敗 (找不到名為 {ENV_ID_NAME} 的變數)"
        has_secret = "✅ 讀取成功" if CLIENT_SECRET else f"❌ 失敗 (找不到名為 {ENV_SECRET_NAME} 的變數)"
        logs.append(f"環境變數檢查: ID={has_id}, Secret={has_secret}")

        # --- 檢查 2: 取得 Token ---
        token = None
        if CLIENT_ID and CLIENT_SECRET:
            token = self.get_auth_token(CLIENT_ID, CLIENT_SECRET)
            logs.append(f"Token 狀態: {'✅ 取得成功' if token else '❌ 取得失敗 (帳號密碼可能錯誤)'}")
        else:
            logs.append("Token 狀態: ⛔ 跳過 (因為沒有帳號密碼)")

        # --- 檢查 3: 抓取資料 ---
        raw_data = []
        if token:
            raw_data = self.fetch_data(token)
            logs.append(f"API 連線: {'✅ 成功' if raw_data else '❌ 失敗或無資料'}")
            logs.append(f"原始資料筆數: {len(raw_data) if raw_data else 0} 筆")

        # --- 生成網頁 (不管有沒有資料都顯示) ---
        html = self.generate_html(raw_data, logs)
        self.wfile.write(html.encode('utf-8'))

    def get_auth_token(self, client_id, client_secret):
        try:
            auth_url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
            headers = {'content-type': 'application/x-www-form-urlencoded'}
            data = {'grant_type': 'client_credentials', 'client_id': client_id, 'client_secret': client_secret}
            resp = requests.post(auth_url, headers=headers, data=data)
            if resp.status_code == 200:
                return resp.json().get('access_token')
            return None
        except:
            return None

    def fetch_data(self, token):
        today = datetime.now().strftime('%Y-%m-%d')
        headers = {'authorization': f'Bearer {token}'}
        # 使用 V2 Station 介面 (最穩)
        url = f"https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/DailyTrainTimetable/Station/{STATION_ID}/{today}"
        try:
            r = requests.get(url, headers=headers)
            if r.status_code == 200:
                data = r.json()
                return data.get('StationTimetables', [])
        except:
            pass
        return []

    def generate_html(self, raw_data, logs):
        current_time = datetime.now().strftime('%H:%M')
        
        # 準備日誌區塊 HTML
        log_html = "<ul style='background:#333; color:#fff; padding:15px; border-radius:5px; font-family:monospace;'>"
        for log in logs:
            log_html += f"<li>{log}</li>"
        log_html += "</ul>"

        # 解析火車資料
        cards_html = ""
        count = 0
        
        if raw_data:
            sorted_data = []
            for item in raw_data:
                try:
                    info = item.get('TrainInfo', {})
                    # 這裡先不過濾方向，全部顯示出來，確定資料有沒有進來
                    direction = info.get('Direction') 
                    dir_str = "(順行/南下)" if direction == 0 else "(逆行/北上)"
                    
                    departure_time = item.get('StopTimes', [{}])[0].get('DepartureTime', '')
                    if not departure_time: continue

                    train_no = info.get('TrainNo', '')
                    train_type = info.get('TrainTypeName', {}).get('Zh_tw', '')
                    dest = info.get('EndingStationName', {}).get('Zh_tw', '')
                    
                    sorted_data.append({
                        'time': departure_time,
                        'str': f"{train_type} {train_no}次 - 往 {dest} <span style='font-size:0.8em;color:#777'>{dir_str}</span>"
                    })
                except:
                    continue
            
            # 排序
            sorted_data.sort(key=lambda x: x['time'])

            for train in sorted_data:
                if train['time'] >= current_time:
                    count += 1
                    cards_html += f"""
                    <div class="card">
                        <div class="time">{train['time']}</div>
                        <div class="info">{train['str']}</div>
                    </div>
                    """
        
        if count == 0:
            cards_html = f"<div style='text-align:center; padding:20px; color:#666;'>⚠️ 目前沒有顯示任何班次 (請查看上方的檢查日誌)</div>"

        # 回傳完整 HTML
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>連線診斷模式</title>
            <style>
                body {{ font-family: "Microsoft JhengHei", sans-serif; padding: 20px; background: #f0f2f5; }}
                h2 {{ text-align: center; color: #333; }}
                .card {{ background: white; padding: 15px; margin-bottom: 10px; border-radius: 8px; 
                         box-shadow: 0 2px 4px rgba(0,0,0,0.1); display: flex; justify-content: space-between; align-items: center;
                         border-left: 5px solid #28a745; }}
                .time {{ font-size: 1.4em; font-weight: bold; color: #333; min-width: 80px; }}
                .info {{ flex-grow: 1; text-align: right; color: #555; }}
                .debug-box {{ margin-bottom: 20px; }}
            </style>
        </head>
        <body>
            <h2>🚆 系統連線診斷 ({current_time})</h2>
            
            <div class="debug-box">
                <h4>🔧 系統檢查日誌 (除錯用)</h4>
                {log_html}
            </div>

            <div id="list">
                {cards_html}
            </div>
        </body>
        </html>
        """
