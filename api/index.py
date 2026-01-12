from http.server import BaseHTTPRequestHandler
import json
import requests
import os
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse
import redis

try:
    from .stations import STATION_MAP
except ImportError:
    from stations import STATION_MAP

# ================= 設定區 =================
CLIENT_ID = os.environ.get('TDX_ID')
CLIENT_SECRET = os.environ.get('TDX_SECRET')

KV_URL = os.environ.get('UPSTASH_REDIS_KV_URL') or os.environ.get('UPSTASH_REDIS_URL') or os.environ.get('KV_URL')

DEFAULT_START = '屏東'
DEFAULT_END = '潮州'

API_BASE_V3 = "https://tdx.transportdata.tw/api/basic/v3/Rail/TRA"
API_BASE_V2 = "https://tdx.transportdata.tw/api/basic/v2/Rail/TRA"

# 強制設定台灣時區 UTC+8
TW_TZ = timezone(timedelta(hours=8))

# 初始化 Redis 連線
redis_client = None
if KV_URL:
    try:
        redis_client = redis.from_url(KV_URL)
        redis_client.ping()
        print("Redis Connected Successfully")
    except Exception as e:
        print(f"Redis Connection Error: {e}")
        redis_client = None
else:
    print("Warning: No Redis URL found.")

# [修改] Log 寫入函式 (開發階段保留 100 筆)
def log_to_redis(msg):
    if redis_client:
        try:
            timestamp = datetime.now(timezone(timedelta(hours=8))).strftime("%H:%M:%S")
            entry = f"[{timestamp}] {msg}"
            redis_client.lpush("sys_logs", entry)
            # 測試階段保留多一點，100筆
            redis_client.ltrim("sys_logs", 0, 99)
        except Exception as e:
            print(f"Log Error: {e}")

class handler(BaseHTTPRequestHandler):

    def get_token(self, cid, csecret):
        if redis_client:
            try:
                cached_token = redis_client.get("tdx_token")
                if cached_token:
                    # [Log] 使用快取 Token (太頻繁可註解掉)
                    # log_to_redis("Token: Cache Hit") 
                    return cached_token.decode('utf-8')
            except: pass

        auth_url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
        try:
            res = requests.post(auth_url, data={'grant_type': 'client_credentials','client_id': cid,'client_secret': csecret})
            if res.status_code == 200: 
                data = res.json()
                token = data.get('access_token')
                expires = data.get('expires_in', 86400)

                if redis_client and token:
                    try:
                        redis_client.set("tdx_token", token, ex=expires - 600)
                    except: pass
                
                # [Log] 申請新 Token
                log_to_redis("Token: Refreshed (New)")
                return token
            log_to_redis(f"Auth Failed: {res.status_code}")
            return None
        except Exception as e:
            log_to_redis(f"Auth Exception: {str(e)}")
            return None

    def get_header_info(self, res):
        val = None
        for k, v in res.headers.items():
            if 'remaining' in k.lower():
                val = v
                break
        if val: return f"API {res.status_code} (剩: {val})"
        return f"API {res.status_code}"

    # === 使用 Redis 存取誤點資訊 (V3 Key) ===
    def get_cached_delays(self, headers):
        cache_key = "v3_tra_delay_data"

        if redis_client:
            try:
                cached_data = redis_client.get(cache_key)
                if cached_data:
                    # [Log] 誤點命中快取
                    log_to_redis("Delay V2: Redis Hit")
                    return (json.loads(cached_data), "Redis Hit")
            except Exception as e:
                print(f"Redis Read Error: {e}")

        delay_url = f"{API_BASE_V2}/LiveTrainDelay"
        res = requests.get(delay_url, headers=headers)

        if res.status_code == 200:
            status_str = self.get_header_info(res)
            d_data = res.json()
            d_list = d_data.get('LiveTrainDelay', []) if isinstance(d_data, dict) else d_data
            new_delays = {t.get('TrainNo'): t.get('DelayTime', 0) for t in d_list}

            if redis_client:
                try:
                    redis_client.set(cache_key, json.dumps(new_delays), ex=60)
                except Exception as e:
                    print(f"Redis Write Error: {e}")
            
            # [Log] 誤點 API 呼叫成功
            log_to_redis(f"Delay V2: API OK ({len(new_delays)} trains)")
            return (new_delays, status_str)
        else: 
            log_to_redis(f"Delay API Error: {res.status_code}")
            raise Exception(f"Delay API Error: {res.status_code}")

    # === 使用 Redis 存取時刻表 (V3 Key) ===
    def get_route_timetable(self, start_id, end_id, date_str, headers):
        cache_key = f"v3_route_{start_id}_{end_id}_{date_str}"

        if redis_client:
            try:
                cached_route = redis_client.get(cache_key)
                if cached_route:
                    # [Log] 時刻表命中快取
                    log_to_redis(f"Route V3 [{date_str}]: Redis Hit")
                    return (json.loads(cached_route), "Redis Hit")
            except: pass

        timetable_url = f"{API_BASE_V3}/DailyTrainTimetable/OD/{start_id}/to/{end_id}/{date_str}"
        res = requests.get(timetable_url, headers=headers)

        if res.status_code == 200:
            status_str = self.get_header_info(res)
            raw_list = res.json().get('TrainTimetables', [])

            if redis_client:
                try:
                    redis_client.set(cache_key, json.dumps(raw_list), ex=43200)
                except: pass
            
            # [Log] 時刻表 API 呼叫成功
            log_to_redis(f"Route V3 [{date_str}]: API OK")
            return (raw_list, status_str)
        else: 
            log_to_redis(f"Timetable API Error: {res.status_code}")
            raise Exception(f"TDX Timetable Error: {res.status_code}")

    # === 核心處理邏輯 ===
    def process_daily_list(self, raw_list, date_str, start_id, end_id, delays, now_aware, fix_crossing_night=False):
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

            raw_delay = int(delays.get(no, 0))

            dep_dt = datetime.strptime(f"{date_str} {dep_time}", "%Y-%m-%d %H:%M").replace(tzinfo=TW_TZ)
            arr_dt = datetime.strptime(f"{date_str} {arr_time}", "%Y-%m-%d %H:%M").replace(tzinfo=TW_TZ)

            if fix_crossing_night:
                if dep_time < "12:00": dep_dt += timedelta(days=1)
                if arr_time < "12:00": arr_dt += timedelta(days=1)

            if arr_dt < dep_dt: arr_dt += timedelta(days=1)

            time_diff_seconds = (dep_dt - now_aware).total_seconds()

            if time_diff_seconds > 21600: 
                delay = 0
            else:
                delay = raw_delay

            real_dep = dep_dt + timedelta(minutes=delay)
            real_arr = arr_dt + timedelta(minutes=delay)

            is_past = real_dep < (now_aware - timedelta(minutes=10))

            processed.append({
                "no": no, "type": display_type, "delay": delay, "color": type_color,
                "act_dep": real_dep.strftime("%H:%M"), "act_arr": real_arr.strftime("%H:%M"),
                "dep_date": real_dep.strftime("%Y-%m-%d"),
                "arr_date": real_arr.strftime("%Y-%m-%d"),
                "sch_dep": dep_time, "sch_arr": arr_time,
                "sort_key": real_dep.timestamp(),
                "is_past": is_past
            })
        return processed

    def do_GET(self):
        parsed_path = urlparse(self.path)
        params = parse_qs(parsed_path.query)

        # God Mode: 讀取 Logs
        if params.get('debug') == ['godmode']:
            logs = []
            if redis_client:
                try:
                    logs_bytes = redis_client.lrange("sys_logs", 0, -1)
                    logs = [l.decode('utf-8') for l in logs_bytes]
                except Exception as e:
                    logs = [f"Redis Read Error: {str(e)}"]
            else:
                logs = ["No Redis Connection"]
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({"logs": logs}).encode())
            return

        start_station = params.get('start', [DEFAULT_START])[0]
        end_station = params.get('end', [DEFAULT_END])[0]
        want_next_day = params.get('next_day', ['0'])[0] == '1'

        # [Log] 收到查詢請求
        log_to_redis(f"REQ: {start_station}->{end_station} (Next:{want_next_day})")

        if not CLIENT_ID or not CLIENT_SECRET: return self.send_error_response("Missing Environment Variables")
        start_id = STATION_MAP.get(start_station)
        end_id = STATION_MAP.get(end_station)
        if not start_id or not end_id: return self.send_error_response(f"找不到車站 ID")

        token = self.get_token(CLIENT_ID, CLIENT_SECRET)
        if not token: return self.send_error_response("Auth Failed")

        now_aware = datetime.now(timezone.utc).astimezone(TW_TZ)
        today_str = now_aware.strftime('%Y-%m-%d')
        tomorrow_str = (now_aware + timedelta(days=1)).strftime('%Y-%m-%d')

        headers = {'authorization': f'Bearer {token}'}

        try:
            raw_today, status_today = self.get_route_timetable(start_id, end_id, today_str, headers)
            
            raw_tmrw = []
            status_tmrw = "Skipped" 
            if want_next_day:
                raw_tmrw, status_tmrw = self.get_route_timetable(start_id, end_id, tomorrow_str, headers)

            raw_yest = []
            status_yest = "Skipped"
            if now_aware.hour < 4:
                yesterday_str = (now_aware - timedelta(days=1)).strftime('%Y-%m-%d')
                raw_yest, status_yest = self.get_route_timetable(start_id, end_id, yesterday_str, headers)

            delays = {}
            delay_failed = False
            delay_status = "Unknown"

            try: 
                delays, delay_status = self.get_cached_delays(headers)
            except Exception as e: 
                log_to_redis(f"Delay Fetch Fail: {str(e)}")
                delay_failed = True
                delay_status = "Failed"

            processed = []

            if raw_yest:
                yesterday_str = (now_aware - timedelta(days=1)).strftime('%Y-%m-%d')
                processed.extend(self.process_daily_list(raw_yest, yesterday_str, start_id, end_id, delays, now_aware, fix_crossing_night=True))

            processed.extend(self.process_daily_list(raw_today, today_str, start_id, end_id, delays, now_aware))
            
            if raw_tmrw:
                processed.extend(self.process_daily_list(raw_tmrw, tomorrow_str, start_id, end_id, delays, now_aware))

            unique_dict = {f"{p['sort_key']}_{p['no']}": p for p in processed}

            final_result = []
            now_ts = now_aware.timestamp()
            today_start = now_aware.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            future_hours = 48 if want_next_day else 24
            future_limit = now_ts + (future_hours * 3600) 
            past_limit = today_start 

            for p in unique_dict.values():
                ts = p['sort_key']
                if ts >= past_limit and ts <= future_limit:
                    final_result.append(p)

            result = sorted(final_result, key=lambda x: x['sort_key'])

            # [Log] 處理完成，記錄結果
            log_to_redis(f"RES: {len(result)} trains sent.")

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'public, max-age=60, s-maxage=60')
            self.end_headers()

            diag_route_status = f"{status_today} / {status_tmrw}"
            if now_aware.hour < 4:
                diag_route_status = f"Y:{status_yest} / T:{status_today} / N:{status_tmrw}"
            elif want_next_day:
                diag_route_status = f"T:{status_today} / N:{status_tmrw} (Loaded)"
            else:
                diag_route_status = f"T:{status_today} / N:Skipped"

            self.wfile.write(json.dumps({
                "update_time": now_aware.strftime("%H:%M:%S"),
                "start": start_station,
                "end": end_station,
                "delay_failed": delay_failed,
                "trains": result,
                "stats": {
                    "original_count": len(final_result)
                },
                "diagnostics": {
                    "route_status": diag_route_status,
                    "delay_status": delay_status
                }
            }).encode())
        except Exception as e:
            log_to_redis(f"CRITICAL: {str(e)}")
            self.send_error_response(str(e))

    def send_error_response(self, msg):
        self.send_response(500)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps({"error": msg}).encode())