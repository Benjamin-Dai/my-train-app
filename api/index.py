from http.server import BaseHTTPRequestHandler
import json
import requests
import os
import time
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

# 嘗試導入車站資料，兼容本地測試與 Vercel 環境
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

# === 1. 誤點資料快取 (全域共用，50秒更新一次) ===
# 這裡的資料在 Vercel 實體存活期間會被保留
_DELAY_CACHE = {
    "data": {},
    "timestamp": 0
}

# === 2. 路線時刻表快取 (Route Caching) ===
# 結構: { "startID_endID": { "date": "2024-01-01", "trains": [...] } }
# 只要有人查過這條路線，當天內就不會再消耗 V3 API 額度
_ROUTE_CACHE = {} 
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

    # === 核心功能 A：取得誤點資料 (含 50秒 快取邏輯) ===
    def get_cached_delays(self, headers):
        global _DELAY_CACHE
        now_ts = time.time()
        
        # 如果快取資料存在，且距離上次更新不到 50 秒，直接回傳快取
        if _DELAY_CACHE["data"] and (now_ts - _DELAY_CACHE["timestamp"] < 50):
            return _DELAY_CACHE["data"]

        # 否則，向 TDX 請求最新全台誤點資料
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
            raise Exception(f"Delay API Error: {res.status_code}")

    # === 核心功能 B：取得路線時刻表 (含路線快取邏輯) ===
    def get_route_timetable(self, start_id, end_id, date_str, headers):
        global _ROUTE_CACHE
        cache_key = f"{start_id}_{end_id}"
        
        # 1. 檢查記憶體中是否已有這條路線今天的時刻表
        if cache_key in _ROUTE_CACHE:
            cached_data = _ROUTE_CACHE[cache_key]
            # 必須確認快取的是「今天」的資料
            if cached_data["date"] == date_str:
                # print(f"Route Cache Hit: {cache_key}") # Debug用，確認沒扣額度
                return cached_data["trains"]
        
        # 2. 沒快取，去問 TDX V3 API (這會消耗搜尋額度)
        timetable_url = f"{API_BASE_V3}/DailyTrainTimetable/OD/{start_id}/to/{end_id}/{date_str}"
        res = requests.get(timetable_url, headers=headers)
        
        if res.status_code == 200:
            timetable_data = res.json()
            raw_list = timetable_data.get('TrainTimetables', []) if isinstance(timetable_data, dict) else []
            
            # 3. 寫入快取，供下一個人使用
            _ROUTE_CACHE[cache_key] = {
                "date": date_str,
                "trains": raw_list
            }
            return raw_list
        else:
            raise Exception(f"TDX Timetable Error: {res.status_code}")

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

        # 設定時區 (UTC+8)
        now = datetime.now() + timedelta(hours=8)
        today_str = now.strftime('%Y-%m-%d')
        headers = {'authorization': f'Bearer {token}'}

        try:
            # 步驟 1: 取得時刻表 (優先讀取快取)
            # 這能大幅節省 V3 API 額度
            raw_list = self.get_route_timetable(start_id, end_id, today_str, headers)
            original_count = len(raw_list)

            # 步驟 2: 取得誤點資訊 (優先讀取快取)
            # 這能大幅節省 V2 API 額度
            delays = {}
            delay_failed = False
            
            try:
                delays = self.get_cached_delays(headers)
            except Exception as e:
                # 容錯機制：如果 API 失敗，嘗試用舊快取
                if _DELAY_CACHE["data"]:
                    delays = _DELAY_CACHE["data"]
                    delay_failed = True # 標記為失敗(黃字)，但仍顯示資料
                else:
                    delay_failed = True # 真的沒資料

            # 步驟 3: 資料整合與過濾
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

                # 車種顏色處理
                display_type = raw_type
                type_color = "#ffffff" 
                if "區間快" in raw_type: display_type, type_color = "區間快", "#0076B2"
                elif "區間" in raw_type: display_type, type_color = "區間車", "#0076B2"
                elif "普悠瑪" in raw_type: display_type, type_color = "普悠瑪", "#9C1637"
                elif "3000" in raw_type: display_type, type_color = "自強3000", "#85a38f"
                elif "自強" in raw_type: display_type, type_color = "自強號", "#DF3F1F"
                elif "太魯閣" in raw_type: display_type, type_color = "太魯閣", "#9C1637"
                elif "莒光" in raw_type: display_type, type_color = "莒光號", "#FF8C00"

                # 計算誤點
                delay = int(delays.get(no, 0))

                dep_dt = datetime.strptime(f"{today_str} {dep_time}", "%Y-%m-%d %H:%M")
                arr_dt = datetime.strptime(f"{today_str} {arr_time}", "%Y-%m-%d %H:%M")
                
                # 處理跨日
                if arr_dt < dep_dt:
                    arr_dt += timedelta(days=1)

                real_dep = dep_dt + timedelta(minutes=delay)
                real_arr = arr_dt + timedelta(minutes=delay)

                # 只顯示還有救的班次 (發車時間 > 現在 - 10分鐘)
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

            # 依實際發車時間排序
            result = sorted(processed, key=lambda x: x['sort_key'])

            # 回傳 JSON
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            # Vercel CDN 快取 60 秒
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
