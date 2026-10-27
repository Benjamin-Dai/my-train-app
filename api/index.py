from http.server import BaseHTTPRequestHandler
import json
import requests
import os
import random
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

API_BASE_V3 = "https://tdx.transportdata.tw/api/basic/v3/Rail/TRA"
API_BASE_V2 = "https://tdx.transportdata.tw/api/basic/v2/Rail/TRA"
AUTH_URL = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"

TW_TZ = timezone(timedelta(hours=8))

# 共用同一條 HTTP 連線：函式「醒著」時，之後呼叫 TDX 不必重新做 TLS 握手
HTTP = requests.Session()
# (連線逾時, 讀取逾時) 秒：TDX 卡住時不要一直等
TDX_TIMEOUT = (3.05, 8)

TOKEN_KEY = "tdx_token"
DELAY_KEY = "v3_tra_delay_data"

# 不在啟動時 ping：連線會在第一次下指令時才建立，省掉冷啟動多一趟來回
redis_client = None
if KV_URL:
    try:
        redis_client = redis.from_url(KV_URL)
    except Exception as e:
        print(f"Redis Init Error: {e}")
        redis_client = None
else:
    print("Warning: No Redis URL found.")


def route_key(start_id, end_id, date_str):
    return f"v3_route_{start_id}_{end_id}_{date_str}"


def redis_mget(keys):
    """一次來回讀回所有需要的快取，回傳 {key: bytes}；失敗就當作全部沒快取。"""
    if not redis_client or not keys:
        return {}
    try:
        values = redis_client.mget(keys)
        return {k: v for k, v in zip(keys, values) if v is not None}
    except Exception as e:
        print(f"Redis MGET Error: {e}")
        return {}


def redis_set(key, value, ex):
    if not redis_client:
        return
    try:
        redis_client.set(key, value, ex=ex)
    except Exception:
        pass


class handler(BaseHTTPRequestHandler):

    def fetch_token(self):
        try:
            res = HTTP.post(AUTH_URL, data={'grant_type': 'client_credentials', 'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET}, timeout=TDX_TIMEOUT)
            if res.status_code != 200:
                return None
            data = res.json()
            token = data.get('access_token')
            expires = data.get('expires_in', 86400)
            if token:
                redis_set(TOKEN_KEY, token, max(expires - 600, 60))
            return token
        except Exception:
            return None

    def get_header_info(self, res):
        val = None
        for k, v in res.headers.items():
            if 'remaining' in k.lower(): val = v; break
        if val: return f"API(剩:{val})"
        return "API"

    def get_delays(self, cached_raw, get_headers, allow_api=True):
        if cached_raw:
            try:
                return (json.loads(cached_raw), "Redis")
            except Exception:
                pass

        if not allow_api:
            return ({}, "Skipped")

        res = HTTP.get(f"{API_BASE_V2}/LiveTrainDelay", headers=get_headers(), timeout=TDX_TIMEOUT)
        if res.status_code == 200:
            status_str = self.get_header_info(res)
            d_data = res.json()
            d_list = d_data.get('LiveTrainDelay', []) if isinstance(d_data, dict) else d_data
            new_delays = {t.get('TrainNo'): t.get('DelayTime', 0) for t in d_list}
            redis_set(DELAY_KEY, json.dumps(new_delays), 75)
            return (new_delays, status_str)
        else:
            raise Exception(f"Delay Error: {res.status_code}")

    def get_route_timetable(self, start_id, end_id, date_str, cached_raw, get_headers):
        if cached_raw:
            try:
                return (json.loads(cached_raw), "Redis")
            except Exception:
                pass

        res = HTTP.get(f"{API_BASE_V3}/DailyTrainTimetable/OD/{start_id}/to/{end_id}/{date_str}", headers=get_headers(), timeout=TDX_TIMEOUT)
        if res.status_code == 200:
            status_str = self.get_header_info(res)
            raw_list = res.json().get('TrainTimetables', [])
            redis_set(route_key(start_id, end_id, date_str), json.dumps(raw_list), 43200)
            return (raw_list, status_str)
        else:
            raise Exception(f"Timetable Error: {res.status_code}")

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
            elif "3000" in raw_type: display_type, type_color = "自強3000", "#ffffff"
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
            
            if time_diff_seconds > 21600: delay = 0
            else: delay = raw_delay

            real_dep = dep_dt + timedelta(minutes=delay)
            real_arr = arr_dt + timedelta(minutes=delay)
            is_past = real_dep < (now_aware - timedelta(minutes=10))

            processed.append({
                "no": no, "type": display_type, "delay": delay, "color": type_color,
                "act_dep": real_dep.strftime("%H:%M"), "act_arr": real_arr.strftime("%H:%M"),
                "dep_date": real_dep.strftime("%Y-%m-%d"), "arr_date": real_arr.strftime("%Y-%m-%d"),
                "sch_dep": dep_time, "sch_arr": arr_time, "sort_key": real_dep.timestamp(), "is_past": is_past
            })
        return processed

    def do_POST(self):
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            
            now_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M%S")
            rand_id = random.randint(1000, 9999)
            report_id = f"report:{now_str}_{rand_id}"
            
            if redis_client:
                redis_client.set(report_id, json.dumps(data), ex=604800)
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "id": report_id}).encode())
            else:
                self.send_error_response("No Redis")
        except Exception as e:
            self.send_error_response(f"Upload Failed: {str(e)}")

    def do_GET(self):
        parsed_path = urlparse(self.path)
        params = parse_qs(parsed_path.query)

        start_station = params.get('start', [''])[0]
        end_station = params.get('end', [''])[0]
        want_next_day = params.get('next_day', ['0'])[0] == '1'
        raw_mode = params.get('mode', ['Query'])[0]

        if not CLIENT_ID or not CLIENT_SECRET: return self.send_error_response("Missing Env")
        start_id = STATION_MAP.get(start_station)
        end_id = STATION_MAP.get(end_station)
        if not start_id or not end_id:
            return self.send_error_response(f"Station Error")

        now_aware = datetime.now(timezone.utc).astimezone(TW_TZ)
        today_str = now_aware.strftime('%Y-%m-%d')
        tomorrow_str = (now_aware + timedelta(days=1)).strftime('%Y-%m-%d')
        yesterday_str = (now_aware - timedelta(days=1)).strftime('%Y-%m-%d')
        need_yesterday = now_aware.hour < 4

        # 一次 MGET 取回 token、時刻表、誤點的快取（原本是一個一個 GET）
        keys = [TOKEN_KEY, DELAY_KEY, route_key(start_id, end_id, today_str)]
        if want_next_day: keys.append(route_key(start_id, end_id, tomorrow_str))
        if need_yesterday: keys.append(route_key(start_id, end_id, yesterday_str))
        cached = redis_mget(keys)

        # token 只有在真的要打 TDX 時才拿；全部命中快取就完全不用
        token_box = {"token": cached[TOKEN_KEY].decode('utf-8') if TOKEN_KEY in cached else None}
        def get_headers():
            if not token_box["token"]:
                token_box["token"] = self.fetch_token()
                if not token_box["token"]:
                    raise Exception("Auth Failed")
            return {'authorization': f'Bearer {token_box["token"]}'}

        def route(date_str):
            return self.get_route_timetable(start_id, end_id, date_str, cached.get(route_key(start_id, end_id, date_str)), get_headers)

        try:
            raw_today, status_today = route(today_str)

            raw_tmrw, status_tmrw = [], "Skipped"
            if want_next_day:
                raw_tmrw, status_tmrw = route(tomorrow_str)

            raw_yest, status_yest = [], "Skipped"
            if need_yesterday:
                raw_yest, status_yest = route(yesterday_str)

            delays = {}
            delay_failed = False
            delay_status = "Unknown"
            try:
                allow_v2 = (raw_mode != "load_next_day")
                delays, delay_status = self.get_delays(cached.get(DELAY_KEY), get_headers, allow_api=allow_v2)
            except Exception as e:
                delay_failed, delay_status = True, "Failed"

            processed = []
            if raw_yest:
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

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            # 一般查詢保持 60 秒快取
            self.send_header('Cache-Control', 'public, max-age=60, s-maxage=60')
            self.end_headers()

            if need_yesterday: diag_route_status = f"Y:{status_yest} / T:{status_today} / N:{status_tmrw}"
            elif want_next_day: diag_route_status = f"T:{status_today} / N:{status_tmrw} (Loaded)"
            else: diag_route_status = f"T:{status_today} / N:Skipped"

            self.wfile.write(json.dumps({
                "update_time": now_aware.strftime("%H:%M:%S"),
                "start": start_station, "end": end_station, "delay_failed": delay_failed,
                "trains": result, "stats": { "original_count": len(final_result) },
                "diagnostics": { "route_status": diag_route_status, "delay_status": delay_status }
            }).encode())
        except Exception as e:
            self.send_error_response(str(e))

    def send_error_response(self, msg):
        self.send_response(500)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps({"error": msg}).encode())