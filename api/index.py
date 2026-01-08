from http.server import BaseHTTPRequestHandler
import json
import requests
import os
import time  # 新增 time 模組
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

# 導入車站資料
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

# === 全域快取 (In-Memory Cache) ===
# 這裡的資料在 Vercel 實體存活期間會被保留
_DELAY_CACHE = {
    "data": {},
    "timestamp": 0
}
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

    # === 新增：取得誤點資料 (含快取邏輯) ===
    def get_cached_delays(self, headers):
        global _DELAY_CACHE
        now_ts = time.time()
        
        # 如果快取資料存在，且距離上次更新不到 50 秒，直接回傳快取
        if _DELAY_CACHE["data"] and (now_ts - _DELAY_CACHE["timestamp"] < 50):
            # print("Using Cached Delays") # Debug用
            return _DELAY_CACHE["data"]

        # 否則，向 TDX 請求最新資料
        delay_url = f"{API_BASE_V2}/LiveTrainDelay"
        res = requests.get(delay_url, headers=headers)
        
        if res.status_code == 200:
            d_data = res.json()
            d_list = d_data.get('LiveTrainDelay', []) if isinstance(d_data, dict) else d_data
            
            # 轉換成 {車次: 誤點分} 的格式
            new_delays = {}
            for t in d_list:
                new_delays[t.get('TrainNo')] = t.get('DelayTime', 0)
            
            # 更新快取
            _DELAY_CACHE["data"] = new_delays
            _DELAY_CACHE["timestamp"] = now_ts
            return new_delays
        else:
            # 如果 API 失敗，拋出錯誤，讓主程式決定是否使用舊快取或報錯
            raise Exception(f"Delay API Error: {res.status_code}")

    def do_GET(self):
        parsed_path = urlparse(self.path)
        params = parse_qs(parsed_path.query)

        start_station = params.get('start', [DEFAULT_START])[0]
        end_station = params.get('end', [DEFAULT_END])[0]

        if not CLIENT_ID or not CLIENT_SECRET:
            self.send_error_response("Missing Environment Variables")
            return

        start_id = STATION_MAP.get(start_station)
        end_id = STATION_MAP.get(end_station)

        if not start_id or not end_id:
            self.send_error_response(f"找不到車站 ID: {start_station} 或 {end_station}")
            return

        token = self.get_token(CLIENT_ID, CLIENT_SECRET)
        if not token:
            self.send_error_response("Auth Failed")
            return

        now = datetime.now() + timedelta(hours=8)
        today_str = now.strftime('%Y-%m-%d')
        headers = {'authorization': f'Bearer {token}'}

        try:
            # 1. V3 時刻表 (OD) - 這是必須針對每個使用者查的，無法全域共用
            timetable_url = f"{API_BASE_V3}/DailyTrainTimetable/OD/{start_id}/to/{end_id}/{today_str}"
            res = requests.get(timetable_url, headers=headers)
            
            if res.status_code != 200:
                raise Exception(f"TDX Timetable Error: {res.status_code}")

            timetable_data = res.json()
            raw_list = timetable_data.get('TrainTimetables', []) if isinstance(timetable_data, dict) else []
            original_count = len(raw_list)

            # 2. V2 誤點資訊 (使用快取優化)
            delays = {}
            delay_failed = False
            
            try:
                # 呼叫我們寫好的快取函式
                delays = self.get_cached_delays(headers)
            except Exception as e:
                # 如果連線失敗，但我們手上有舊快取(即使過期)，為了使用者體驗，還是先用舊的
                if _DELAY_CACHE["data"]:
                    delays = _DELAY_CACHE["data"]
                    # 這裡可以決定要不要標記 failed，如果用舊資料算不算 failed? 
                    # 為了嚴謹，我們先標記 true，讓前端顯示黃字提示
                    delay_failed = True 
                else:
                    delay_failed = True # 真的沒資料

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
                
                if arr_dt < dep_dt:
                    arr_dt += timedelta(days=1)

                real_dep = dep_dt + timedelta(minutes=delay)
                real_arr = arr_dt + timedelta(minutes=delay)

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

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'public, max-age=60, s-maxage=60')
            self.end_headers()
            self.wfile.write(json.dumps({
                "update_time": now.strftime("%H:%M:%S"),
                "start": start_station,
                "end": end_station,
                "stats": {
                    "original_count": original_count,
                    "filtered_count": len(result)
                },
                "delay_failed": delay_failed,
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
