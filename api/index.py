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

# 確保環境變數抓取正確
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
            res = requests.post(auth_url, data={'grant_type': 'client_credentials','client_id': cid,'client_secret': csecret}, timeout=10)
            if res.status_code == 200: return res.json().get('access_token')
            return None
        except: return None

    def get_header_info(self, res):
        limit = res.headers.get('RateLimit-Remaining')
        if not limit: limit = res.headers.get('x-ratelimit-remaining-minute')
        if not limit: limit = res.headers.get('X-RateLimit-Remaining')
        if not limit: limit = res.headers.get('x-ratelimit-remaining')
        if limit: return f"API {res.status_code} (剩餘: {limit})"
        found = [v for k, v in res.headers.items() if 'remaining' in k.lower()]
        return f"API {res.status_code} (剩餘: {found[0] if found else '未知'})"

    def get_cached_delays(self, headers):
        global _DELAY_CACHE
        now_ts = time.time()
        if _DELAY_CACHE["data"] and (now_ts - _DELAY_CACHE["timestamp"] < 50): 
            return (_DELAY_CACHE["data"], "Cache Hit (0點)")
        delay_url = f"{API_BASE_V2}/LiveTrainDelay"
        try:
            res = requests.get(delay_url, headers=headers, timeout=10)
            if res.status_code == 200:
                status_str = self.get_header_info(res)
                d_data = res.json()
                d_list = d_data.get('LiveTrainDelay', []) if isinstance(d_data, dict) else d_data
                new_delays = {t.get('TrainNo'): t.get('DelayTime', 0) for t in d_list}
                _DELAY_CACHE["data"] = new_delays
                _DELAY_CACHE["timestamp"] = now_ts
                return (new_delays, status_str)
            elif res.status_code == 429: raise Exception("429")
            else: raise Exception(f"Error {res.status_code}")
        except Exception as e: raise e

    def get_route_timetable(self, start_id, end_id, date_str, headers):
        global _ROUTE_CACHE
        cache_key = f"{start_id}_{end_id}"
        if cache_key in _ROUTE_CACHE and _ROUTE_CACHE[cache_key]["date"] == date_str: 
            return (_ROUTE_CACHE[cache_key]["trains"], "Cache Hit (0點)")
        timetable_url = f"{API_BASE_V3}/DailyTrainTimetable/OD/{start_id}/to/{end_id}/{date_str}"
        try:
            res = requests.get(timetable_url, headers=headers, timeout=10)
            if res.status_code == 200:
                status_str = self.get_header_info(res)
                raw_list = res.json().get('TrainTimetables', [])
                _ROUTE_CACHE[cache_key] = {"date": date_str, "trains": raw_list}
                return (raw_list, status_str)
            elif res.status_code == 429: raise Exception("429")
            else: raise Exception(f"Error {res.status_code}")
        except Exception as e: raise e

    def do_GET(self):
        parsed_path = urlparse(self.path)
        params = parse_qs(parsed_path.query)
        start_station = params.get('start', [DEFAULT_START])[0]
        end_station = params.get('end', [DEFAULT_END])[0]
        if not CLIENT_ID or not CLIENT_SECRET: return self.send_error_response("後端配置錯誤", 500)
        start_id = STATION_MAP.get(start_station)
        end_id = STATION_MAP.get(end_station)
        if not start_id or not end_id: return self.send_error_response("車站 ID 錯誤", 400)
        token = self.get_token(CLIENT_ID, CLIENT_SECRET)
        if not token: return self.send_error_response("TDX 認證失敗", 500)
        now = datetime.now() + timedelta(hours=8)
        headers = {'authorization': f'Bearer {token}'}
        try:
            raw_list, route_status = self.get_route_timetable(start_id, end_id, now.strftime('%Y-%m-%d'), headers)
            delays, delay_status = {}, "Unknown"
            delay_failed = False
            try: delays, delay_status = self.get_cached_delays(headers)
            except Exception as e:
                delay_failed = True
                delay_status = "系統忙碌" if "429" in str(e) else "讀取失敗"
                if _DELAY_CACHE["data"]: delays = _DELAY_CACHE["data"]
            processed = []
            for item in raw_list:
                info = item.get('TrainInfo', {})
                no = info.get('TrainNo')
                raw_type = info.get('TrainTypeName', {}).get('Zh_tw', '')
                stop_times = item.get('StopTimes', [])
                dep_time, arr_time = None, None
                for stop in stop_times:
                    if stop.get('StationID') == start_id: dep_time = stop.get('DepartureTime')
                    elif stop.get('StationID') == end_id: arr_time = stop.get('ArrivalTime')
                if not dep_time or not arr_time: continue 
                type_color = "#ffffff"
                if "區間快" in raw_type: type_color = "#0076B2"
                elif "區間" in raw_type: type_color = "#0076B2"
                elif "自強3000" in raw_type or "EMU3000" in raw_type: type_color = "#85a38f"
                elif "自強" in raw_type: type_color = "#DF3F1F"
                elif "莒光" in raw_type: type_color = "#FF8C00"
                elif "普悠瑪" in raw_type or "太魯閣" in raw_type: type_color = "#9C1637"
                delay = int(delays.get(no, 0))
                dep_dt = datetime.strptime(f"{now.strftime('%Y-%m-%d')} {dep_time}", "%Y-%m-%d %H:%M")
                arr_dt = datetime.strptime(f"{now.strftime('%Y-%m-%d')} {arr_time}", "%Y-%m-%d %H:%M")
                if arr_dt < dep_dt: arr_dt += timedelta(days=1)
                real_dep = dep_dt + timedelta(minutes=delay)
                real_arr = arr_dt + timedelta(minutes=delay)
                processed.append({
                    "no": no, "type": raw_type, "delay": delay, "color": type_color,
                    "act_dep": real_dep.strftime("%H:%M"), "act_arr": real_arr.strftime("%H:%M"),
                    "sch_dep": dep_time, "sch_arr": arr_time,
                    "sort_key": real_dep.timestamp(), "is_past": real_dep < (now - timedelta(minutes=10))
                })
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({
                "update_time": now.strftime("%H:%M:%S"), "start": start_station, "end": end_station,
                "delay_failed": delay_failed, "trains": sorted(processed, key=lambda x: x['sort_key']),
                "diagnostics": { "route_status": route_status, "delay_status": delay_status }
            }).encode())
        except Exception as e:
            code = 429 if "429" in str(e) else 500
            self.send_error_response("Rate Limit" if code==429 else str(e), code)

    def send_error_response(self, msg, code):
        self.send_response(code)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps({"error": msg}).encode())
