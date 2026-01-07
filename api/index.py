from http.server import BaseHTTPRequestHandler
import json
import requests
from datetime import datetime, timedelta
import os

# ================= 設定區 =================
# 修正時區：Vercel 是 UTC，我們要加 8 小時變成台灣時間
def get_taiwan_time():
    return datetime.utcnow() + timedelta(hours=8)

# 嘗試讀取環境變數
ENV_ID = os.environ.get('TDX_ID')
ENV_SECRET = os.environ.get('TDX_SECRET')

# 你的車站代碼
STATION_ID = '5000' # 屏東

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()

        # 取得台灣時間
        tw_now = get_taiwan_time()
        current_time_str = tw_now.strftime('%H:%M')
        today_date = tw_now.strftime('%Y-%m-%d')

        # === 自我檢查報告 ===
        report = []
        
        # 1. 檢查變數名稱 (這是最常見的錯誤點)
        # 我們檢查變數是否存在，不顯示內容以保安全
        if ENV_ID:
            report.append(f"✅ TDX_ID: 讀取成功 (長度 {len(ENV_ID)} 字元)")
        else:
            report.append("❌ TDX_ID: 讀取失敗 (是 None)")
            
        if ENV_SECRET:
            report.append(f"✅ TDX_SECRET: 讀取成功 (長度 {len(ENV_SECRET)} 字元)")
        else:
            report.append("❌ TDX_SECRET: 讀取失敗 (是 None)")

        # 2. 嘗試取得 Token
        token = None
        if ENV_ID and ENV_SECRET:
            try:
                auth_url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
                headers = {'content-type': 'application/x-www-form-urlencoded'}
                data = {'grant_type': 'client_credentials', 'client_id': ENV_ID, 'client_secret': ENV_SECRET}
                r = requests.post(auth_url, headers=headers, data=data)
                if r.status_code == 200:
                    token = r.json().get('access_token')
                    report.append("✅ Token: 取得成功！帳號密碼正確")
                else:
                    report.append(f"❌ Token: 取得失敗 (錯誤碼 {r.status_code})。請檢查帳號密碼是否正確")
            except Exception as e:
                report.append(f"❌ Token: 連線錯誤 ({str(e)})")
        else:
            report.append("⚠️ Token: 跳過 (因為沒有帳號密碼)")

        # 3. 抓取火車資料
        trains = []
        if token:
            url = f"https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/DailyTrainTimetable/Station/{STATION_ID}/{today_date}"
            try:
                r = requests.get(url, headers={'authorization': f'Bearer {token}'})
                if r.status_code == 200:
                    data = r.json()
                    raw_list = data.get('StationTimetables', [])
                    report.append(f"✅ 資料 API: 成功連線，抓到 {len(raw_list)} 筆原始資料")
                    
                    # 整理資料
                    for item in raw_list:
                        info = item.get('TrainInfo', {})
                        # 只顯示順行 (往潮州/南下)
                        if info.get('Direction') == 0:
                            stop_time = item.get('StopTimes', [{}])[0].get('DepartureTime', '')
                            if stop_time and stop_time >= current_time_str:
                                trains.append({
                                    'time': stop_time,
                                    'type': info.get('TrainTypeName', {}).get('Zh_tw', ''),
                                    'no': info.get('TrainNo', ''),
                                    'dest': info.get('EndingStationName', {}).get('Zh_tw', '')
                                })
                    trains.sort(key=lambda x: x['time'])
                else:
                    report.append(f"❌ 資料 API: 失敗 (錯誤碼 {r.status_code})")
            except:
                report.append("❌ 資料 API: 連線發生例外錯誤")

        # 生成 HTML
        report_html = "<br>".join(report)
        
        list_html = ""
        if trains:
            for t in trains:
                list_html += f"""
                <div class="card">
                    <div class="time">{t['time']}</div>
                    <div class="info">{t['type']} ({t['no']}次) 往 {t['dest']}</div>
                </div>"""
        else:
            list_html = "<div style='text-align:center; padding:20px'>目前沒有後續車次</div>"

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>除錯模式</title>
            <style>
                body {{ font-family: sans-serif; padding: 20px; background: #eee; }}
                .debug {{ background: #333; color: #fff; padding: 15px; margin-bottom: 20px; border-radius: 5px; font-family: monospace; line-height: 1.5; }}
                .card {{ background: white; padding: 15px; margin-bottom: 10px; border-radius: 8px; display: flex; justify-content: space-between; align-items: center; border-left: 5px solid #009688; }}
                .time {{ font-size: 1.5em; font-weight: bold; }}
            </style>
        </head>
        <body>
            <h2 style="text-align:center">台灣時間: {current_time_str}</h2>
            
            <div class="debug">
                <strong>系統檢查日誌：</strong><br>
                {report_html}
            </div>

            {list_html}
        </body>
        </html>
        """
        self.wfile.write(html.encode('utf-8'))
