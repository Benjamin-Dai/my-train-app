from http.server import BaseHTTPRequestHandler
import requests
import os
import json
from datetime import datetime, timedelta, timezone

# ================= 設定區 =================
CLIENT_ID = os.environ.get('TDX_ID')
CLIENT_SECRET = os.environ.get('TDX_SECRET')
START_STATION_ID = '5000'  # 屏東站
# =========================================

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
            if res.status_code != 200: return None, f"Token Error"
            data = res.json()
            CACHED_TOKEN = data.get('access_token')
            TOKEN_EXPIRY = now + timedelta(seconds=data.get('expires_in', 3600))
            return CACHED_TOKEN, None
        except: return None, "Auth Exception"

    def do_GET(self):
        token, error_msg = self.get_token()
        if not token:
            self.send_response(500)
            self.wfile.write(f"Auth Fail".encode('utf-8'))
            return

        headers = {'authorization': f'Bearer {token}'}
        url = f"https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/LiveBoard/Station/{START_STATION_ID}"

        try:
            res = requests.get(url, headers=headers).json()
            processed = []
            
            tz_taiwan = timezone(timedelta(hours=8))
            now_dt = datetime.now(tz_taiwan)

            if isinstance(res, list):
                for t in res:
                    if t.get('Direction') == 0: 
                        train_no = t['TrainNo']
                        t_type = t['TrainTypeName']['Zh_tw'].replace("自強(3000)", "自強3000")
                        
                        # --- 修正時間解析邏輯 ---
                        raw_time = t['ScheduledDepartureTime']
                        # 如果時間字串長度 > 5 (代表有秒數，如 13:00:00)，只取前 5 碼
                        sch_dep = raw_time[:5] 
                        
                        delay = t.get('DelayTime', 0)
                        dest = t.get('EndingStationName', {}).get('Zh_tw', '未知')
                        
                        try:
                            dep_dt = datetime.strptime(f"{now_dt.strftime('%Y-%m-%d')} {sch_dep}", "%Y-%m-%d %H:%M").replace(tzinfo=tz_taiwan)
                            if dep_dt < now_dt - timedelta(hours=12): dep_dt += timedelta(days=1)
                            real_dep = dep_dt + timedelta(minutes=delay)
                        except:
                            continue # 如果時間格式真的太奇怪就跳過這班

                        color = "#ffffff"
                        if "區間" in t_type: color = "#0076B2"
                        elif "3000" in t_type: color = "#85a38f"
                        elif "自強" in t_type: color = "#DF3F1F"
                        elif "普悠瑪" in t_type: color = "#9C1637"

                        processed.append({
                            "no": train_no, "type": t_type, "delay": delay, "color": color,
                            "act_dep": real_dep.strftime("%H:%M"), "sch_dep": sch_dep, "dest": dest,
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
                        <div class="train-info" style="color: {t['color']};">{t['type']} {t['no']} 次 (往{t['dest']})</div>
                        <div class="main-time"><span>{t['act_dep']}</span></div>
                        <div class="sub-time">原定 {t['sch_dep']} 開</div>
                    </div>
                </a>"""

            if not data:
                cards_html = f'<div style="text-align:center; padding:50px; color:#444;">目前無南下班次</div>'

            html = f"""
            <!DOCTYPE html>
            <html lang="zh-TW">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
                <meta http-equiv="refresh" content="60">
                <title>屏東車站看板</title>
                <style>
                    body {{ background: #000; color: #fff; font-family: -apple-system, sans-serif; padding: 10px; margin: 0; }}
                    .container {{ max-width: 500px; margin: 0 auto; }}
                    .update-time {{ color: #999; font-size: 0.65rem; text-align: right; margin-bottom: 8px; }}
                    .header {{ padding: 0 5px; display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }}
                    .card {{ background: #151517; border-radius: 12px; padding: 10px 16px; margin-bottom: 8px; border-left: 5px solid #333; position: relative; }}
                    .delay-badge {{ position: absolute; top: 12px; right: 16px; border: 1px solid #f2a900; color: #f2a900; padding: 1px 5px; border-radius: 4px; font-size: 0.65rem; font-weight: 600; }}
                    .train-info {{ font-size: 0.82rem; font-weight: 700; margin-bottom: 2px; }}
                    .main-time {{ display: flex; align-items: center; justify-content: center; font-size: 1.8rem; font-weight: 700; padding: 4px 0; }}
                    .sub-time {{ text-align: center; color: #999; font-size: 0.7rem; }}
                    a {{ text-decoration: none; color: inherit; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="update-time">最後更新：{now_dt.strftime("%H:%M:%S")}</div>
                    <div class="header">
                        <h1 style="margin:0; font-size:1.3rem;">屏東 ➔ 往南 (潮州/台東)</h1>
                    </div>
                    {cards_html}
                </div>
            </body>
            </html>
            """
            
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 's-maxage=60, stale-while-revalidate')
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))

        except Exception as e:
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(f"系統錯誤: {str(e)}".encode('utf-8'))
