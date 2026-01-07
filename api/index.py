from http.server import BaseHTTPRequestHandler
import requests
import os
import json
from datetime import datetime, timedelta, timezone

CLIENT_ID = os.environ.get('TDX_ID')
CLIENT_SECRET = os.environ.get('TDX_SECRET')
START_STATION_ID = '5000' # 屏東

# Token 快取
CACHED_TOKEN = None
TOKEN_EXPIRY = datetime.min.replace(tzinfo=timezone.utc)

class handler(BaseHTTPRequestHandler):
    def get_token(self):
        global CACHED_TOKEN, TOKEN_EXPIRY
        now = datetime.now(timezone.utc)
        if CACHED_TOKEN and now < TOKEN_EXPIRY - timedelta(seconds=600):
            return CACHED_TOKEN, None
        try:
            res = requests.post("https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token", data={
                'grant_type': 'client_credentials', 'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET
            })
            if res.status_code != 200: return None, f"Token Error"
            data = res.json()
            CACHED_TOKEN = data.get('access_token')
            TOKEN_EXPIRY = now + timedelta(seconds=data.get('expires_in', 3600))
            return CACHED_TOKEN, None
        except Exception as e: return None, str(e)

    def do_GET(self):
        # 設定台灣時間
        tz_taiwan = timezone(timedelta(hours=8))
        now_dt = datetime.now(tz_taiwan)
        today_str = now_dt.strftime('%Y-%m-%d')

        logs = []
        logs.append(f"台灣時間: {now_dt.strftime('%H:%M:%S')}")
        
        token, error_msg = self.get_token()
        if not token:
            self.send_response(500)
            self.wfile.write(f"Auth Fail".encode('utf-8'))
            return

        headers = {'authorization': f'Bearer {token}'}
        
        url = f"https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/DailyTimetable/Station/{START_STATION_ID}/{today_str}"
        
        try:
            res = requests.get(url, headers=headers).json()
            
            if isinstance(res, list):
                logs.append(f"API 回傳: {len(res)} 筆")
            else:
                logs.append(f"API 錯誤: {str(res)}")
                res = []

            processed = []
            
            # 白名單
            SOUTH_DESTS = ['潮州', '枋寮', '臺東', '台東', '花蓮', '知本', '玉里', '南州', '林邊', '大武', '枋野', '太麻里']
            
            # 收集所有抓到的終點站名稱 (除錯用)
            found_destinations = set()

            for t in res:
                # 嘗試兩種常見的欄位結構
                info = t.get('DailyTrainInfo', {})
                if not info: info = t.get('TrainInfo', {}) # 防呆
                
                train_no = info.get('TrainNo', 'Unknown')
                
                # 抓取終點站
                dest_node = info.get('EndingStationName', {})
                dest = dest_node.get('Zh_tw', '未知')
                
                # 記錄下來
                found_destinations.add(dest)

                # 找出屏東發車時間
                stop_times = t.get('StopTimes', [])
                dep_time = ""
                for s in stop_times:
                    if s['StationID'] == START_STATION_ID:
                        dep_time = s['DepartureTime']
                        break
                
                if not dep_time: continue

                # 時間處理
                sch_dep = dep_time[:5]
                try:
                    dep_dt = datetime.strptime(f"{today_str} {sch_dep}", "%Y-%m-%d %H:%M").replace(tzinfo=tz_taiwan)
                    
                    # 只顯示「現在 - 30分鐘」以後的車 (寬鬆一點，讓我們看到車)
                    if dep_dt < now_dt - timedelta(minutes=30):
                        continue
                except: continue

                t_type = info.get('TrainTypeName', {}).get('Zh_tw', '').replace("自強(3000)", "自強3000")
                
                # 判斷是否往南
                is_south = dest in SOUTH_DESTS
                
                # 顏色設定
                if is_south:
                    # 往南顯示亮色
                    color = "#ffffff"
                    if "區間" in t_type: color = "#0076B2"
                    elif "3000" in t_type: color = "#85a38f"
                    elif "自強" in t_type: color = "#DF3F1F"
                    elif "普悠瑪" in t_type: color = "#9C1637"
                else:
                    # 往北顯示暗灰色
                    color = "#444444" 

                processed.append({
                    "no": train_no, "type": t_type, "color": color,
                    "sch_dep": sch_dep, "dest": dest, "sort_key": dep_dt,
                    "is_south": is_south
                })

            data = sorted(processed, key=lambda x: x['sort_key'])
            
            # 診斷資訊
            logs.append(f"抓到的終點站清單: {list(found_destinations)[:10]} ...") # 只印前10個

            cards_html = ""
            for t in data:
                # 往北的車字體調暗
                opacity = "1" if t['is_south'] else "0.5"
                dir_tag = "(南下)" if t['is_south'] else "(北上)"
                
                cards_html += f"""
                <div class="card" style="border-left-color: {t['color']}; opacity: {opacity};">
                    <div class="train-info" style="color: {t['color']};">{t['type']} {t['no']} 次 (往{t['dest']})</div>
                    <div class="main-time">{t['sch_dep']} <small style="font-size:0.5em">{dir_tag}</small></div>
                </div>"""

            if not data:
                cards_html = f'<div style="text-align:center; padding:50px; color:#444;">無資料</div>'
            
            debug_html = "<br>".join(logs)

            html = f"""
            <!DOCTYPE html>
            <html lang="zh-TW">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
                <meta http-equiv="refresh" content="60">
                <title>屏東車站診斷</title>
                <style>
                    body {{ background: #000; color: #fff; font-family: -apple-system, sans-serif; padding: 10px; margin: 0; }}
                    .container {{ max-width: 500px; margin: 0 auto; }}
                    .header {{ padding: 0 5px; margin-bottom: 12px; }}
                    .card {{ background: #151517; border-radius: 12px; padding: 10px 16px; margin-bottom: 8px; border-left: 5px solid #333; }}
                    .train-info {{ font-size: 0.82rem; font-weight: 700; margin-bottom: 2px; }}
                    .main-time {{ font-size: 1.5rem; font-weight: 700; }}
                    details {{ margin-top: 30px; border: 1px solid #333; padding: 10px; background: #111; }}
                    pre {{ color: #0f0; font-size: 0.7rem; white-space: pre-wrap; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header"><h3>🔍 無濾網模式 (Show All)</h3></div>
                    {cards_html}
                    <details open><summary>診斷資訊</summary><pre>{debug_html}</pre></details>
                </div>
            </body>
            </html>
            """
            
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 's-maxage=60, stale-while-revalidate')
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))

        except Exception as e:
            self.send_response(200)
            self.wfile.write(f"Error: {str(e)}".encode('utf-8'))
