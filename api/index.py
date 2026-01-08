from http.server import BaseHTTPRequestHandler
import json
import requests
import os
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

# ================= 設定區 =================
# 注意：在 Vercel 部署時，務必在後台 Environment Variables 設定這兩個變數
CLIENT_ID = os.environ.get('TDX_ID')
CLIENT_SECRET = os.environ.get('TDX_SECRET')

DEFAULT_START = '屏東'
DEFAULT_END = '潮州'

API_BASE_V3 = "https://tdx.transportdata.tw/api/basic/v3/Rail/TRA"
API_BASE_V2 = "https://tdx.transportdata.tw/api/basic/v2/Rail/TRA"
# =========================================

class handler(BaseHTTPRequestHandler):
    
    def get_token(self, cid, csecret):
        auth_url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
        try:
            res = requests.post(auth_url, data={
                'grant_type': 'client_credentials',
                'client_id': cid,
                'client_secret': csecret
            })
            if res.status_code == 200:
                return res.json().get('access_token')
            return None
        except:
            return None

    def get_station_ids(self, token, start_name, end_name):
        url = f"{API_BASE_V3}/Station"
        headers = {'authorization': f'Bearer {token}'}
        station_map = {}
        
        try:
            res = requests.get(url, headers=headers)
            if res.status_code != 200: return None, None
            
            data = res.json()
            # V3 結構兼容處理
            stations = data.get('Stations', []) if isinstance(data, dict) else data

            for s in stations:
                if not isinstance(s, dict): continue
                name = s.get('StationName', {}).get('Zh_tw')
                sid = s.get('StationID')
                if name and sid:
                    station_map[name] = sid
            
            return station_map.get(start_name), station_map.get(end_name)
        except:
            return None, None

    def do_GET(self):
        # 解析參數
        parsed_path = urlparse(self.path)
        params = parse_qs(parsed_path.query)
        
        start_station = params.get('start', [DEFAULT_START])[0]
        end_station = params.get('end', [DEFAULT_END])[0]

        if not CLIENT_ID or not CLIENT_SECRET:
            self.send_error_response("Missing Environment Variables")
            return

        token = self.get_token(CLIENT_ID, CLIENT_SECRET)
        if not token:
            self.send_error_response("Auth Failed")
            return

        start_id, end_id = self.get_station_ids(token, start_station, end_station)
        if not start_id or not end_id:
            self.send_error_response("Station Not Found")
            return

        # Vercel 時區修正 (+8)
        now = datetime.now() + timedelta(hours=8)
        today_str = now.strftime('%Y-%m-%d')
        headers = {'authorization': f'Bearer {token}'}

        try:
            # 1. V3 時刻表 (OD)
            timetable_url = f"{API_BASE_V3}/DailyTrainTimetable/OD/{start_id}/to/{end_id}/{today_str}"
            res = requests.get(timetable_url, headers=headers)
            timetable_data = res.json()
            raw_list = timetable_data.get('TrainTimetables', []) if isinstance(timetable_data, dict) else []

            # 2. V2 誤點資訊
            delay_url = f"{API_BASE_V2}/LiveTrainDelay"
            delay_res = requests.get(delay_url, headers=headers)
            delays = {}
            if delay_res.status_code == 200:
                d_data = delay_res.json()
                d_list = d_data.get('LiveTrainDelay', []) if isinstance(d_data, dict) else d_data
                for t in d_list:
                    delays[t.get('TrainNo')] = t.get('DelayTime', 0)

            # 3. 資料整合
            processed = []
            for item in raw_list:
                info = item.get('TrainInfo', {})
                no = info.get('TrainNo')
                raw_type = info.get('TrainTypeName', {}).get('Zh_tw', '')
                
                stop_times = item.get('StopTimes', [])
                dep_time, arr_time = None, None
                for stop in stop_times:
                    s_id = stop.get('StationID')
                    if s_id == start_id: dep_time = stop.get('DepartureTime')
                    elif s_id == end_id: arr_time = stop.get('ArrivalTime')
                
                if not dep_time or not arr_time: continue 

                # 車種顏色
                display_type = raw_type
                type_color = "#ffffff" 
                if "區間快" in raw_type: display_type, type_color = "區間快", "#0076B2"
                elif "區間" in raw_type: display_type, type_color = "區間車", "#0076B2"
                elif "普悠瑪" in raw_type: display_type, type_color = "普悠瑪", "#9C1637"
                elif "3000" in raw_type: display_type, type_color = "自強3000", "#85a38f"
                elif "自強" in raw_type: display_type, type_color = "自強號", "#DF3F1F"
                elif "太魯閣" in raw_type: display_type, type_color = "太魯閣", "#9C1637"

                delay = int(delays.get(no, 0))
                
                # 時間計算
                dep_dt = datetime.strptime(f"{today_str} {dep_time}", "%Y-%m-%d %H:%M")
                arr_dt = datetime.strptime(f"{today_str} {arr_time}", "%Y-%m-%d %H:%M")
                real_dep = dep_dt + timedelta(minutes=delay)
                real_arr = arr_dt + timedelta(minutes=delay)

                # 過濾：只顯示目前時間 - 10分鐘以後的車
                if real_dep > now - timedelta(minutes=10):
                    processed.append({
                        "no": no, 
                        "type": display_type, 
                        "delay": delay, 
                        "color": type_color,
                        "act_dep": real_dep.strftime("%H:%M"),
                        "act_arr": real_arr.strftime("%H:%M"),
                        "sch_dep": dep_time, 
                        "sch_arr": arr_time,
                        "sort_key": real_dep.timestamp()
                    })

            result = sorted(processed, key=lambda x: x['sort_key'])

            # 回傳 JSON
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            # 快取 60 秒 (重要：省額度關鍵)
            self.send_header('Cache-Control', 'public, max-age=60, s-maxage=60')
            self.end_headers()
            self.wfile.write(json.dumps({
                "update_time": now.strftime("%H:%M:%S"),
                "start": start_station,
                "end": end_station,
                "trains": result
            }).encode())

        except Exception as e:
            self.send_error_response(str(e))

    def send_error_response(self, msg):
        self.send_response(500)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps({"error": msg}).encode())
