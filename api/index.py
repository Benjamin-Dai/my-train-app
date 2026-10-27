from http.server import BaseHTTPRequestHandler
import json
import requests
import os
import random
import re
import hmac
import hashlib
import secrets
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

# 開發者後台（只用來看使用者回報）
ADMIN_USER = os.environ.get('ADMIN_USER')
ADMIN_PASS = os.environ.get('ADMIN_PASS')
ADMIN_TOKEN_TTL = 1800          # 登入後 30 分鐘內有效（每次使用會延長）
LOGIN_MAX_FAILS = 5             # 同一個 IP 最多錯 5 次
LOGIN_LOCK_SECONDS = 900        # 錯太多次鎖 15 分鐘
LOGIN_GLOBAL_MAX_FAILS = 30     # 所有 IP 合計，防止換 IP 硬猜
MAX_BODY_BYTES = 32 * 1024      # 回報內容上限 32KB
REPORT_RATE_MAX = 20            # 同一個 IP 10 分鐘內最多 20 筆回報
REPORT_RATE_WINDOW = 600
REPORT_TTL = 604800             # 回報保留 7 天
REPORT_ID_RE = re.compile(r"^report:\d{8}_\d{6}_\d{4}$")

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

    # ================= POST：使用者回報 / 開發者後台 =================

    def send_json(self, code, obj, admin=False):
        self.send_response(code)
        self.send_header('Content-type', 'application/json')
        if admin:
            # 後台 API：不允許跨網域、不快取
            self.send_header('Cache-Control', 'no-store')
        else:
            self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(obj, ensure_ascii=False).encode())

    def client_ip(self):
        xff = self.headers.get('x-forwarded-for', '')
        ip = xff.split(',')[0].strip() if xff else ''
        return ip or self.headers.get('x-real-ip') or self.client_address[0]

    def read_body(self):
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY_BYTES:
            return None
        return self.rfile.read(length) if length > 0 else b''

    def do_POST(self):
        params = parse_qs(urlparse(self.path).query)
        admin_action = params.get('admin', [None])[0]

        body = self.read_body()
        if body is None:
            return self.send_json(413, {"error": "Payload Too Large"}, admin=bool(admin_action))

        if admin_action:
            try:
                return self.handle_admin(admin_action, body)
            except Exception as e:
                print(f"Admin Error: {e}")
                return self.send_json(500, {"error": "Server Error"}, admin=True)

        # ---- 使用者回報 ----
        if not redis_client:
            return self.send_json(500, {"error": "No Redis"})
        try:
            data = json.loads(body.decode('utf-8') or '{}')
            if not isinstance(data, dict):
                return self.send_json(400, {"error": "Bad Request"})

            rl_key = f"rl:report:{self.client_ip()}"
            count = redis_client.incr(rl_key)
            if count == 1:
                redis_client.expire(rl_key, REPORT_RATE_WINDOW)
            if count > REPORT_RATE_MAX:
                return self.send_json(429, {"error": "Too Many Reports"})

            now_str = datetime.now(TW_TZ).strftime("%Y%m%d_%H%M%S")
            report_id = f"report:{now_str}_{random.randint(1000, 9999)}"
            redis_client.set(report_id, json.dumps(data, ensure_ascii=False), ex=REPORT_TTL)
            return self.send_json(200, {"status": "ok", "id": report_id})
        except Exception as e:
            print(f"Report Error: {e}")
            return self.send_json(500, {"error": "Upload Failed"})

    def handle_admin(self, action, body):
        if not redis_client:
            return self.send_json(503, {"error": "No Redis"}, admin=True)
        if not ADMIN_USER or not ADMIN_PASS:
            # 沒設定帳密就整個關閉，避免空帳密被當成正確
            return self.send_json(503, {"error": "Admin Disabled"}, admin=True)

        try:
            data = json.loads(body.decode('utf-8') or '{}')
            if not isinstance(data, dict): data = {}
        except Exception:
            data = {}

        if action == 'login':
            ip = self.client_ip()
            fail_key = f"admin:fail:{ip}"
            global_key = "admin:fail:_all"
            fails, global_fails = redis_client.mget([fail_key, global_key])
            if int(fails or 0) >= LOGIN_MAX_FAILS or int(global_fails or 0) >= LOGIN_GLOBAL_MAX_FAILS:
                return self.send_json(429, {"error": "Too Many Attempts"}, admin=True)

            u = str(data.get('u', '')).encode('utf-8')
            p = str(data.get('p', '')).encode('utf-8')
            # compare_digest：比對時間固定，不會因為「前幾個字對了」而比較慢
            ok_u = hmac.compare_digest(u, ADMIN_USER.encode('utf-8'))
            ok_p = hmac.compare_digest(p, ADMIN_PASS.encode('utf-8'))
            if not (ok_u and ok_p):
                pipe = redis_client.pipeline()
                pipe.incr(fail_key); pipe.expire(fail_key, LOGIN_LOCK_SECONDS)
                pipe.incr(global_key)
                if pipe.execute()[2] == 1:
                    redis_client.expire(global_key, LOGIN_LOCK_SECONDS)
                return self.send_json(401, {"error": "Auth Failed"}, admin=True)

            redis_client.delete(fail_key)
            token = secrets.token_urlsafe(32)
            redis_client.set(self.token_key(token), "1", ex=ADMIN_TOKEN_TTL)
            return self.send_json(200, {"token": token, "expires_in": ADMIN_TOKEN_TTL}, admin=True)

        # ---- 以下都需要有效 token ----
        auth = self.headers.get('Authorization', '')
        token = auth[7:].strip() if auth.startswith('Bearer ') else ''
        tkey = self.token_key(token) if token else None
        if not tkey or not redis_client.exists(tkey):
            return self.send_json(401, {"error": "Unauthorized"}, admin=True)

        if action == 'logout':
            redis_client.delete(tkey)
            return self.send_json(200, {"status": "ok"}, admin=True)

        redis_client.expire(tkey, ADMIN_TOKEN_TTL)

        if action == 'list_reports':
            keys = [k.decode('utf-8') for k in redis_client.scan_iter(match="report:*", count=200)]
            keys = sorted([k for k in keys if REPORT_ID_RE.match(k)], reverse=True)
            return self.send_json(200, {"reports": keys}, admin=True)

        if action == 'get_report':
            report_id = str(data.get('id', ''))
            if not REPORT_ID_RE.match(report_id):
                return self.send_json(400, {"error": "Bad Report ID"}, admin=True)
            content = redis_client.get(report_id)
            if not content:
                return self.send_json(404, {"error": "Not Found"}, admin=True)
            return self.send_json(200, {"report_content": json.loads(content)}, admin=True)

        if action == 'clear_reports':
            keys = list(redis_client.scan_iter(match="report:*", count=200))
            if keys: redis_client.delete(*keys)
            return self.send_json(200, {"status": "ok", "deleted": len(keys)}, admin=True)

        return self.send_json(400, {"error": "Unknown Action"}, admin=True)

    @staticmethod
    def token_key(token):
        # Redis 只存 token 的雜湊值，就算資料庫內容外洩也拿不到可用的 token
        return "admin:token:" + hashlib.sha256(token.encode('utf-8')).hexdigest()

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