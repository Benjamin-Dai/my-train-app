from http.server import BaseHTTPRequestHandler
import requests
import os
import json
from datetime import datetime, timedelta, timezone

# ================= 設定區 =================
CLIENT_ID = os.environ.get('TDX_ID')
CLIENT_SECRET = os.environ.get('TDX_SECRET')
START_STATION_NAME = '屏東'
START_STATION_ID = '5000'  # 屏東站
END_STATION_NAME = '潮州'
# =========================================

# --- 全域變數：用來快取 Token，避免一直重新申請導致被鎖 ---
CACHED_TOKEN = None
TOKEN_EXPIRY = datetime.min.replace(tzinfo=timezone.utc)

class handler(BaseHTTPRequestHandler):
    def get_token(self):
        global CACHED_TOKEN, TOKEN_EXPIRY
        now = datetime.now(timezone.utc)
        
        # 如果 Token 還活著 (還有 10 分鐘以上壽命)，直接沿用
        if CACHED_TOKEN and now < TOKEN_EXPIRY - timedelta(seconds=600):
            return CACHED_TOKEN, None
        
        # 否則重新申請
        try:
            res = requests.post("https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token", data={
                'grant_type': 'client_credentials',
                'client_id': CLIENT_ID,
                'client_secret': CLIENT_SECRET
            })
            if res.status_code != 200:
                return None, f"Token Error: {res.text}"
            
            data = res.json()
            CACHED_TOKEN = data.get('access_token')
            expires_in = data.get('expires_in', 3600)
            TOKEN_EXPIRY = now + timedelta(seconds=expires_in)
            return CACHED_TOKEN, None
        except Exception as e:
            return None, str(e)

    def do_GET(self):
        token, error_msg = self.get_token()
        if not token:
            self.send_response(500)
            self.wfile.write(f"Token Error: {error_msg}".encode('utf-8'))
            return

        headers = {'authorization': f'Bearer {token}'}
        # 強制設定為台灣時區 UTC+8
        tz_taiwan = timezone(timedelta(hours=8))
        now = datetime.now(tz_taiwan)
        today = now.strftime('%Y-%m-%d')
        
        # 收集診斷訊息 (Debug Logs)
        debug_logs = []
        debug_logs.append(f"Server 時間: {now.strftime('%H:%M:%S')}")
        debug_logs.append(f"查詢日期: {today}")

        url = f"https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/DailyTimetable/Station/{START_STATION_ID}/{today}"
        delay_url = "https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/LiveTrainDelay"

        try:
            # 抓取資料
            res = requests.get(url, headers=headers).json()
            delay_res = requests.get(delay_url, headers=headers).json()
            
            # 檢查 TDX 是否回傳錯誤訊息
            if isinstance(res, dict) and 'Message' in res:
                raise Exception(f"API Error: {res['Message']}")

            debug_logs.append(f"API 抓到總筆數: {len(res)} 筆")
            
            # 建立誤點字典
            if isinstance(delay_res, list):
                delays = {t.get('TrainNo'): t.get('DelayTime', 0) for t in delay_res}
            else:
                delays = {}

            processed = []
            sample_logs = 0 # 紀錄前幾筆被過濾的原因

            for t in res:
                if 'StopTimes' not in t: continue
                stop_times = t['StopTimes']
                stations = [s['StationName']['Zh_tw'].strip() for s in stop_times]
                
                # --- 診斷邏輯 ---
                reason = "通過"
                valid = False

                if END_STATION_NAME not in stations:
                    reason = "不經過目的地"
                else:
                    idx_start = stations.index(START_STATION_NAME)
                    idx_end = stations.index(END_STATION_NAME)
                    if idx_start >= idx_end:
                        reason = "方向相反"
                    else:
                        no = t['DailyTrainInfo']['TrainNo']
                        dep_s = stop_times[idx_start]['DepartureTime']
                        delay = delays.get(no, 0)
                        
                        # 計算發車時間
                        dep_dt = datetime.strptime(f"{today} {dep_s}", "%Y-%m-%d %H:%M").replace(tzinfo=tz_taiwan)
                        real_dep = dep_dt + timedelta(minutes=delay)

                        # 時間過濾：顯示 10 分鐘前 ~ 未來 3 小時
                        if not (now - timedelta(minutes=10) <= real_dep <= now + timedelta(hours=3)):
                            reason = f"時間不符 ({real_dep.strftime('%H:%M')})"
                        else:
                            valid = True
                            # 符合所有條件，加入清單
                            raw_type = t['DailyTrainInfo']['TrainTypeName']['Zh_tw']
                            arr_s = stop_times[idx_end]['ArrivalTime']
                            
                            color = "#ffffff"
                            if "區間" in raw_type: color = "#0076B2"
                            elif "自強" in raw_type: color = "#DF3F1F"
                            elif "3000" in raw_type: color = "#85a38f"
                            elif "普悠瑪" in raw_type: color = "#9C1637"
                            
                            act_arr = (datetime.strptime(f"{today} {arr_s}", "%Y-%m-%d %H:%M").replace(tzinfo=tz_taiwan) + timedelta(minutes=delay)).strftime("%H:%M")
                            
                            processed.append({
                                "no": no, 
                                "type": raw_type.replace("自強(3000)", "自強3000"), 
                                "delay": delay, 
                                "color": color,
                                "act_dep": real_dep.strftime("%H:%M"), 
                                "act_arr": act_arr,
                                "sch_dep": dep_s, 
                                "sch_arr": arr_s, 
                                "sort_key": real_dep
                            })

                # 紀錄前 3 筆無效的車次原因，方便除錯
                if not valid and sample_logs < 3:
                    train_no = t['DailyTrainInfo'].get('TrainNo', 'Unknown')
                    debug_logs.append(f"過濾車次 {train_no}: {reason}")
                    sample_logs += 1

            debug_logs.append(f"最終顯示: {len(processed)} 筆")
            data = sorted(processed, key=lambda x: x['sort_key'])
            
            # --- 生成 HTML ---
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
                cards_html = f'<div style="text-align:center; padding:50px; color:#444;">目前無符合班次</div>'

            # 將診斷訊息顯示在網頁最下方
            debug_html = "<br><hr><div style='color:#666; font-size:0.75rem; padding:15px; background:#111; border-radius:8px; line-height:1.5;'>" 
            debug_html += "<strong>🛠️ 診斷資訊 (Debug Info):</strong><br>"
            debug_html += "<br>".join(debug_logs) + "</div>"

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
                    <div class="update-time">Vercel 診斷版：{now.strftime("%H:%M:%S")}</div>
                    <div class="header">
                        <h1 style="margin:0; font-size:1.3rem;">{START_STATION_NAME} ➔ {END_STATION_NAME}</h1>
                    </div>
                    {cards_html}
                    {debug_html}
                </div>
            </body>
            </html>
            """
            
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))

        except Exception as e:
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(f"<h1 style='color:red'>系統錯誤</h1><p>{str(e)}</p>".encode('utf-8'))
