from http.server import BaseHTTPRequestHandler
import requests
import os
import json
from datetime import datetime, timedelta, timezone

# ================= 設定區 =================
CLIENT_ID = os.environ.get('TDX_ID')
CLIENT_SECRET = os.environ.get('TDX_SECRET')
START_STATION_NAME = '屏東'
START_STATION_ID = '5000'
END_STATION_NAME = '潮州'
# =========================================

# --- 關鍵修改 1：全域變數快取 Token ---
# 這樣在 Vercel 實例存活期間，我們可以重複使用 Token，不用每次都去申請
CACHED_TOKEN = None
TOKEN_EXPIRY = datetime.min.replace(tzinfo=timezone.utc)

class handler(BaseHTTPRequestHandler):
    def get_token(self):
        global CACHED_TOKEN, TOKEN_EXPIRY
        now = datetime.now(timezone.utc)
        
        # 如果現有 Token 還沒過期 (預留 600秒緩衝)，直接回傳，省一次 API！
        if CACHED_TOKEN and now < TOKEN_EXPIRY - timedelta(seconds=600):
            return CACHED_TOKEN, None

        auth_url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
        try:
            res = requests.post(auth_url, data={
                'grant_type': 'client_credentials',
                'client_id': CLIENT_ID,
                'client_secret': CLIENT_SECRET
            })
            if res.status_code != 200:
                return None, f"Token Error: {res.text}"
            
            data = res.json()
            CACHED_TOKEN = data.get('access_token')
            # 設定過期時間 (expires_in 通常是 86400 秒)
            expires_in = data.get('expires_in', 3600)
            TOKEN_EXPIRY = now + timedelta(seconds=expires_in)
            
            return CACHED_TOKEN, None
        except Exception as e:
            return None, str(e)

    def do_GET(self):
        token, error_msg = self.get_token()
        if not token:
            self.send_response(500)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(f"<h1>Token 取得失敗</h1><p>{error_msg}</p>".encode('utf-8'))
            return

        headers = {'authorization': f'Bearer {token}'}
        tz_taiwan = timezone(timedelta(hours=8))
        now = datetime.now(tz_taiwan)
        today = now.strftime('%Y-%m-%d')
        
        url = f"https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/DailyTimetable/Station/{START_STATION_ID}/{today}"
        delay_url = "https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/LiveTrainDelay"

        try:
            raw_res = requests.get(url, headers=headers)
            raw_delay = requests.get(delay_url, headers=headers)

            try:
                res = raw_res.json()
                delay_res = raw_delay.json()
            except:
                raise Exception("TDX 回傳了非 JSON 格式的資料")

            if not isinstance(res, list):
                error_content = str(res)
                # 如果遇到 Rate Limit，顯示友善訊息
                if "rate limit" in error_content.lower():
                    raise Exception("系統忙碌中 (流量管制)，請稍候再試。")
                raise Exception(f"時刻表 API 回傳錯誤: {error_content}")
            
            if not isinstance(delay_res, list):
                delay_res = [] 

            delays = {t.get('TrainNo'): t.get('DelayTime', 0) for t in delay_res}

            processed = []
            for t in res:
                if not isinstance(t, dict): continue
                if 'StopTimes' not in t or not t['StopTimes']: continue
                
                stop_times = t['StopTimes']
                stations = [s['StationName']['Zh_tw'].strip() for s in stop_times]

                if END_STATION_NAME in stations:
                    idx_start = stations.index(START_STATION_NAME)
                    idx_end = stations.index(END_STATION_NAME)

                    if idx_start < idx_end:
                        no = t['DailyTrainInfo']['TrainNo']
                        dep_s = stop_times[idx_start]['DepartureTime']
                        delay = delays.get(no, 0)
                        
                        dep_dt = datetime.strptime(f"{today} {dep_s}", "%Y-%m-%d %H:%M").replace(tzinfo=tz_taiwan)
                        real_dep = dep_dt + timedelta(minutes=delay)

                        if now - timedelta(minutes=10) <= real_dep <= now + timedelta(hours=3):
                            raw_type = t['DailyTrainInfo']['TrainTypeName']['Zh_tw']
                            arr_s = stop_times[idx_end]['ArrivalTime']
                            
                            color = "#ffffff"
                            if "區間" in raw_type: color = "#0076B2"
                            elif "3000" in raw_type: color = "#85a38f"
                            elif "自強" in raw_type: color = "#DF3F1F"
                            elif "普悠瑪" in raw_type or "太魯閣" in raw_type: color = "#9C1637"

                            d_type = raw_type.replace("自強(3000)", "自強3000")
                            act_arr = (datetime.strptime(f"{today} {arr_s}", "%Y-%m-%d %H:%M").replace(tzinfo=tz_taiwan) + timedelta(minutes=delay)).strftime("%H:%M")

                            processed.append({
                                "no": no, "type": d_type, "delay": delay, "color": color,
                                "act_dep": real_dep.strftime("%H:%M"),
                                "act_arr": act_arr,
                                "sch_dep": dep_s, "sch_arr": arr_s,
                                "sort_key": real_dep
                            })
            
            data = sorted(processed, key=lambda x: x['sort_key'])
            
            cards_html = ""
            for t in data:
                delay_tag = f'<div class="delay-badge">誤點 {t["delay"]} 分</div>' if t['delay'] > 0 else ""
                train_url = f"https://railway.chienwen.net/taiwan/train/TRA-{t['no']}/live"
                cards_html += f"""
                <a href="{train_url}" target="_blank">
                    <div class="card" style="border-left-color: {t['color']};">
                        {delay_tag}
                        <div class="train-info" style="color: {t['color']};">{t['type']} {t['no']} 次</div>
                        <div class="main-time"><span>{t['act_dep']}</span><span class="arrow">➔</span><span>{t['act_arr']}</span></div>
                        <div class="sub-time">原定 {t['sch_dep']} ➔ {t['sch_arr']}</div>
                    </div>
                </a>"""

            if not data:
                cards_html = f'<div style="text-align:center; padding:50px; color:#444;">目前無符合班次<br><small>{now.strftime("%H:%M:%S")} 更新</small></div>'

            # --- 關鍵修改 3：前端自動刷新改為 60 秒 ---
            html = f"""
            <!DOCTYPE html>
            <html lang="zh-TW">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
                <meta http-equiv="refresh" content="60"> 
                <title>列車時刻</title>
                <style>
                    body {{ background: #000; color: #fff; font-family: -apple-system, sans-serif; padding: 10px; margin: 0; }}
                    .container {{ max-width: 500px; margin: 0 auto; }}
                    .update-time {{ color: #999; font-size: 0.65rem; text-align: right; margin-bottom: 8px; }}
                    .header {{ padding: 0 5px; display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }}
                    .card {{ background: #151517; border-radius: 12px; padding: 10px 16px; margin-bottom: 8px; border-left: 5px solid #333; position: relative; }}
                    .delay-badge {{ position: absolute; top: 12px; right: 16px; border: 1px solid #f2a900; color: #f2a900; padding: 1px 5px; border-radius: 4px; font-size: 0.65rem; font-weight: 600; }}
                    .train-info {{ font-size: 0.82rem; font-weight: 700; margin-bottom: 2px; }}
                    .main-time {{ display: flex; align-items: center; justify-content: center; font-size: 1.8rem; font-weight: 700; padding: 4px 0; }}
                    .arrow {{ margin: 0 12px; color: #999; font-size: 0.8rem; }}
                    .sub-time {{ text-align: center; color: #999; font-size: 0.7rem; }}
                    a {{ text-decoration: none; color: inherit; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="update-time">Vercel 即時運算：{now.strftime("%H:%M:%S")}</div>
                    <div class="header">
                        <h1 style="margin:0; font-size:1.3rem;">{START_STATION_NAME} ➔ {END_STATION_NAME}</h1>
                    </div>
                    {cards_html}
                </div>
            </body>
            </html>
            """
            
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            # --- 關鍵修改 2：快取時間改為 60 秒 ---
            # s-maxage=60 代表 Vercel 伺服器會在 60 秒內直接給你看舊資料，不會真的跑去執行程式
            self.send_header('Cache-Control', 's-maxage=60, stale-while-revalidate')
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))

        except Exception as e:
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            error_html = f"""
            <div style="background:#330000; color:#ffcccc; padding:20px; font-family:monospace;">
                <h2>系統訊息</h2>
                <p>{str(e)}</p>
            </div>
            """
            self.wfile.write(error_html.encode('utf-8'))
