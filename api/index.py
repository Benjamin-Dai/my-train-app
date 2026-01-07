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

# Token 快取
CACHED_TOKEN = None
TOKEN_EXPIRY = datetime.min.replace(tzinfo=timezone.utc)

class handler(BaseHTTPRequestHandler):
    def get_token(self):
        global CACHED_TOKEN, TOKEN_EXPIRY
        now = datetime.now(timezone.utc)
        if CACHED_TOKEN and now < TOKEN_EXPIRY - timedelta(seconds=600):
            return CACHED_TOKEN, None
        
        try:
            res = requests.post("https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token", data={
                'grant_type': 'client_credentials', 'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET
            })
            if res.status_code != 200: return None, f"Token Error: {res.text}"
            data = res.json()
            CACHED_TOKEN = data.get('access_token')
            TOKEN_EXPIRY = now + timedelta(seconds=data.get('expires_in', 3600))
            return CACHED_TOKEN, None
        except Exception as e: return None, str(e)

    def do_GET(self):
        token, error_msg = self.get_token()
        if not token:
            self.send_response(500)
            self.wfile.write(f"Token Error: {error_msg}".encode('utf-8'))
            return

        headers = {'authorization': f'Bearer {token}'}
        tz_taiwan = timezone(timedelta(hours=8))
        now = datetime.now(tz_taiwan)
        today = now.strftime('%Y-%m-%d')
        
        # 診斷訊息收集
        debug_logs = []
        debug_logs.append(f"系統時間 (台灣): {now.strftime('%Y-%m-%d %H:%M:%S')}")
        debug_logs.append(f"查詢日期: {today}")
        debug_logs.append(f"查詢站點 ID: {START_STATION_ID} ({START_STATION_NAME})")

        url = f"https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/DailyTimetable/Station/{START_STATION_ID}/{today}"
        delay_url = "https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/LiveTrainDelay"

        try:
            res = requests.get(url, headers=headers).json()
            delay_res = requests.get(delay_url, headers=headers).json()
            
            # 檢查是否為錯誤訊息
            if isinstance(res, dict) and 'Message' in res:
                raise Exception(f"API 回傳錯誤: {res['Message']}")

            debug_logs.append(f"API 回傳總筆數: {len(res)} 筆")
            
            delays = {t.get('TrainNo'): t.get('DelayTime', 0) for t in delay_res}
            processed = []
            
            # 取前 3 筆做樣本分析
            sample_count = 0

            for t in res:
                if 'StopTimes' not in t: continue
                stop_times = t['StopTimes']
                stations = [s['StationName']['Zh_tw'].strip() for s in stop_times]
                
                # 診斷：為什麼這班車被過濾？
                reason = "通過"
                if END_STATION_NAME not in stations:
                    reason = f"不經過{END_STATION_NAME}"
                else:
                    idx_start = stations.index(START_STATION_NAME)
                    idx_end = stations.index(END_STATION_NAME)
                    if idx_start >= idx_end:
                        reason = "方向錯誤 (往北)"
                    else:
                        no = t['DailyTrainInfo']['TrainNo']
                        dep_s = stop_times[idx_start]['DepartureTime']
                        delay = delays.get(no, 0)
                        dep_dt = datetime.strptime(f"{today} {dep_s}", "%Y-%m-%d %H:%M").replace(tzinfo=tz_taiwan)
                        real_dep = dep_dt + timedelta(minutes=delay)
                        
                        # 診斷時間
                        if not (now - timedelta(minutes=10) <= real_dep <= now + timedelta(hours=3)):
                            reason = f"時間不符 ({real_dep.strftime('%H:%M')})"
                        else:
                            # 通過所有檢查
                            raw_type = t['DailyTrainInfo']['TrainTypeName']['Zh_tw']
                            arr_s = stop_times[idx_end]['ArrivalTime']
                            color = "#ffffff"
                            if "區間" in raw_type: color = "#0076B2"
                            elif "自強" in raw_type: color = "#DF3F1F"
                            elif "3000" in raw_type: color = "#85a38f"
                            elif "普悠瑪" in raw_type: color = "#9C1637"
                            
                            act_arr = (datetime.strptime(f"{today} {arr_s}", "%Y-%m-%d %H:%M").replace(tzinfo=tz_taiwan) + timedelta(minutes=delay)).strftime("%H:%M")
                            
                            processed.append({
                                "no": no, "type": raw_type.replace("自強(3000)", "自強3000"), 
                                "delay": delay, "color": color,
                                "act_dep": real_dep.strftime("%H:%M"), "act_arr": act_arr,
                                "sch_dep": dep_s, "sch_arr": arr_s, "sort_key": real_dep
                            })

                if sample_count < 3:
                    debug_logs.append(f"樣本車次 {t['DailyTrainInfo']['TrainNo']}: {reason}")
                    sample_count += 1

            debug_logs.append(f"最終顯示筆數: {len(processed)}")
            data = sorted(processed, key=lambda x: x['sort_key'])
            
            # HTML 生成
            cards_html = ""
            for t in data:
                delay_tag = f'<div class="delay-badge">誤點 {t["delay"]} 分</div>' if t['delay'] > 0 else ""
                cards_html += f"""
                <a href="https://railway.chienwen.net/taiwan/train/TRA-{t['no']}/live" target="_blank">
                    <div class="card" style="border-left-color: {t['color']};">
                        {delay_tag}
                        <div class="train-info" style="color: {t['color']};">{t['type']} {t['no']} 次</div>
                        <div class="main-time"><span>{t['act_dep']}</span><span class="arrow">➔</span><span>{t['act_arr']}</span></div>
                        <div class="sub-time">原定 {t['sch_dep']} ➔ {t['sch_arr']}</div>
                    </div>
                </a>"""

            if not data:
                cards_html = f'<div style="text-align:center; padding:50px; color:#444;">目前無符合班次</div>'

            # 將診斷訊息印在網頁最下方
            debug_html = "<br><hr><div style='color:#666; font-size:0.7rem; padding:10px; background:#111;'>" + "<br>".join(debug_logs) + "</div>"

            html = f"""
            <!DOCTYPE html>
            <html lang="zh-TW">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
                <title>列車時刻 (診斷版)</title>
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
                    <div class="update-time">Vercel 診斷模式：{now.strftime("%H:%M:%S")}</div>
                    <div class="header">
                        <h1 style="margin:0; font-size:1.3rem;">{START_STATION_NAME} ➔ {END_STATION_NAME}</h1>
                    </div>
                    {cards_html}
                    {debug_html}
