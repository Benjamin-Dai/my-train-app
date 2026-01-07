from http.server import BaseHTTPRequestHandler
import requests
import os
from datetime import datetime, timedelta, timezone

# ================= 設定區 =================
# Vercel 會自動從環境變數讀取這些值
CLIENT_ID = os.environ.get('TDX_ID')
CLIENT_SECRET = os.environ.get('TDX_SECRET')
START_STATION_NAME = '屏東'
START_STATION_ID = '5000'  # 屏東站代碼
END_STATION_NAME = '潮州'
# =========================================

class handler(BaseHTTPRequestHandler):
    def get_token(self):
        auth_url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
        try:
            res = requests.post(auth_url, data={
                'grant_type': 'client_credentials',
                'client_id': CLIENT_ID,
                'client_secret': CLIENT_SECRET
            })
            return res.json().get('access_token')
        except:
            return None

    def do_GET(self):
        token = self.get_token()
        if not token:
            self.send_error(500, "TDX Token Error")
            return

        headers = {'authorization': f'Bearer {token}'}
        # 強制設定台灣時區 UTC+8
        tz_taiwan = timezone(timedelta(hours=8))
        now = datetime.now(tz_taiwan)
        today = now.strftime('%Y-%m-%d')
        
        # 使用屏東站專屬 API
        url = f"https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/DailyTimetable/Station/{START_STATION_ID}/{today}"
        delay_url = "https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/LiveTrainDelay"

        try:
            res = requests.get(url, headers=headers).json()
            delay_res = requests.get(delay_url, headers=headers).json()
            delays = {t['TrainNo']: t.get('DelayTime', 0) for t in delay_res}

            processed = []
            for t in res:
                # 防呆：如果沒有停靠站資料就跳過
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
                        
                        # 加上時區資訊
                        dep_dt = datetime.strptime(f"{today} {dep_s}", "%Y-%m-%d %H:%M").replace(tzinfo=tz_taiwan)
                        real_dep = dep_dt + timedelta(minutes=delay)

                        # 顯示：10分鐘前 ~ 未來3小時
                        if now - timedelta(minutes=10) <= real_dep <= now + timedelta(hours=3):
                            raw_type = t['DailyTrainInfo']['TrainTypeName']['Zh_tw']
                            arr_s = stop_times[idx_end]['ArrivalTime']
                            
                            # 顏色邏輯
                            color = "#ffffff"
                            if "區間" in raw_type: color = "#0076B2"
                            elif "3000" in raw_type: color = "#85a38f"
                            elif "自強" in raw_type: color = "#DF3F1F"
                            elif "普悠瑪" in raw_type or "太魯閣" in raw_type: color = "#9C1637"

                            # 名稱簡化
                            d_type = raw_type
                            if "區間快" in raw_type: d_type = "區間快"
                            elif "區間" in raw_type: d_type = "區間車"
                            elif "3000" in raw_type: d_type = "自強3000"
                            elif "自強" in raw_type: d_type = "自強號"

                            act_arr = (datetime.strptime(f"{today} {arr_s}", "%Y-%m-%d %H:%M").replace(tzinfo=tz_taiwan) + timedelta(minutes=delay)).strftime("%H:%M")

                            processed.append({
                                "no": no, "type": d_type, "delay": delay, "color": color,
                                "act_dep": real_dep.strftime("%H:%M"),
                                "act_arr": act_arr,
                                "sch_dep": dep_s, "sch_arr": arr_s,
                                "sort_key": real_dep
                            })
            
            data = sorted(processed, key=lambda x: x['sort_key'])
            
            # 生成 HTML (Vercel 直接輸出字串)
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

            html = f"""
            <!DOCTYPE html>
            <html lang="zh-TW">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
                <title>列車時刻 (Vercel)</title>
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
            # 設定 10 秒快取，避免瘋狂按 F5 導致 TDX 鎖 IP
            self.send_header('Cache-Control', 's-maxage=10, stale-while-revalidate')
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))

        except Exception as e:
            self.send_response(500)
            self.send_header('Content-type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(f"系統錯誤: {str(e)}".encode('utf-8'))
