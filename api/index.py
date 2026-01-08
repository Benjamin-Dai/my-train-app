from http.server import BaseHTTPRequestHandler
import json
import requests
import os
import time
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

try:
    from .stations import STATION_MAP
except ImportError:
    from stations import STATION_MAP

# ================= 設定區 =================
CLIENT_ID = os.environ.get('TDX_ID')
CLIENT_SECRET = os.environ.get('TDX_SECRET')

DEFAULT_START = '屏東'
DEFAULT_END = '潮州'

API_BASE_V3 = "https://tdx.transportdata.tw/api/basic/v3/Rail/TRA"
API_BASE_V2 = "https://tdx.transportdata.tw/api/basic/v2/Rail/TRA"

_DELAY_CACHE = { "data": {}, "timestamp": 0 }
_ROUTE_CACHE = {} 

class handler(BaseHTTPRequestHandler):

    def get_token(self, cid, csecret):
        auth_url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
        try:
            res = requests.post(auth_url, data={'grant_type': 'client_credentials','client_id': cid,'client_secret': csecret})
            if res.status_code == 200: return res.json().get('access_token')
            return None
        except: return None

    def get_cached_delays(self, headers):
        global _DELAY_CACHE
        now_ts = time.time()
        if _DELAY_CACHE["data"] and (now_ts - _DELAY_CACHE["timestamp"] < 50): return _DELAY_CACHE["data"]
        delay_url = f"{API_BASE_V2}/LiveTrainDelay"
        res = requests.get(delay_url, headers=headers)
        if res.status_code == 200:
            d_data = res.json()
            d_list = d_data.get('LiveTrainDelay', []) if isinstance(d_data, dict) else d_data
            new_delays = {t.get('TrainNo'): t.get('DelayTime', 0) for t in d_list}
            _DELAY_CACHE["data"] = new_delays
            _DELAY_CACHE["timestamp"] = now_ts
            return new_delays
        else: raise Exception(f"Delay API Error: {res.status_code}")

    def get_route_timetable(self, start_id, end_id, date_str, headers):
        global _ROUTE_CACHE
        cache_key = f"{start_id}_{end_id}"
        if cache_key in _ROUTE_CACHE and _ROUTE_CACHE[cache_key]["date"] == date_str: return _ROUTE_CACHE[cache_key]["trains"]
        timetable_url = f"{API_BASE_V3}/DailyTrainTimetable/OD/{start_id}/to/{end_id}/{date_str}"
        res = requests.get(timetable_url, headers=headers)
        if res.status_code == 200:
            raw_list = res.json().get('TrainTimetables', [])
            _ROUTE_CACHE[cache_key] = {"date": date_str, "trains": raw_list}
            return raw_list
        else: raise Exception(f"TDX Timetable Error: {res.status_code}")

    def do_GET(self):
        parsed_path = urlparse(self.path)
        params = parse_qs(parsed_path.query)
        start_station = params.get('start', [DEFAULT_START])[0]
        end_station = params.get('end', [DEFAULT_END])[0]

        if not CLIENT_ID or not CLIENT_SECRET: return self.send_error_response("Missing Environment Variables")
        start_id = STATION_MAP.get(start_station)
        end_id = STATION_MAP.get(end_station)
        if not start_id or not end_id: return self.send_error_response(f"找不到車站 ID")

        token = self.get_token(CLIENT_ID, CLIENT_SECRET)
        if not token: return self.send_error_response("Auth Failed")

        now = datetime.now() + timedelta(hours=8)
        today_str = now.strftime('%Y-%m-%d')
        headers = {'authorization': f'Bearer {token}'}

        try:
            raw_list = self.get_route_timetable(start_id, end_id, today_str, headers)
            delays = {}
            delay_failed = False
            try: delays = self.get_cached_delays(headers)
            except: 
                if _DELAY_CACHE["data"]: delays = _DELAY_CACHE["data"]; delay_failed = True
                else: delay_failed = True

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

                display_type = raw_type
                type_color = "#ffffff"
                if "區間快" in raw_type: display_type, type_color = "區間快", "#0076B2"
                elif "區間" in raw_type: display_type, type_color = "區間車", "#0076B2"
                elif "普悠瑪" in raw_type: display_type, type_color = "普悠瑪", "#9C1637"
                elif "3000" in raw_type: display_type, type_color = "自強3000", "#85a38f"
                elif "自強" in raw_type: display_type, type_color = "自強號", "#DF3F1F"
                elif "太魯閣" in raw_type: display_type, type_color = "太魯閣", "#9C1637"
                elif "莒光" in raw_type: display_type, type_color = "莒光號", "#FF8C00"

                delay = int(delays.get(no, 0))
                dep_dt = datetime.strptime(f"{today_str} {dep_time}", "%Y-%m-%d %H:%M")
                arr_dt = datetime.strptime(f"{today_str} {arr_time}", "%Y-%m-%d %H:%M")
                if arr_dt < dep_dt: arr_dt += timedelta(days=1)

                real_dep = dep_dt + timedelta(minutes=delay)
                real_arr = arr_dt + timedelta(minutes=delay)
                
                # 關鍵修改：不再過濾，而是加上 is_past 標記
                is_past = real_dep < (now - timedelta(minutes=10))

                processed.append({
                    "no": no, "type": display_type, "delay": delay, "color": type_color,
                    "act_dep": real_dep.strftime("%H:%M"), "act_arr": real_arr.strftime("%H:%M"),
                    "sch_dep": dep_time, "sch_arr": arr_time,
                    "sort_key": real_dep.timestamp(),
                    "is_past": is_past # 傳給前端
                })

            result = sorted(processed, key=lambda x: x['sort_key'])
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'public, max-age=60, s-maxage=60')
            self.end_headers()
            self.wfile.write(json.dumps({
                "update_time": now.strftime("%H:%M:%S"),
                "start": start_station,
                "end": end_station,
                "delay_failed": delay_failed,
                "trains": result
            }).encode())
        except Exception as e: self.send_error_response(str(e))

    def send_error_response(self, msg):
        self.send_response(500)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps({"error": msg}).encode())
