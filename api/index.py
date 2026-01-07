from http.server import BaseHTTPRequestHandler
import requests
import os
import json
from datetime import datetime, timedelta, timezone

CLIENT_ID = os.environ.get('TDX_ID')
CLIENT_SECRET = os.environ.get('TDX_SECRET')
START_STATION_ID = '5000' # 屏東

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
            if res.status_code != 200: return None, f"Token Error"
            data = res.json()
            CACHED_TOKEN = data.get('access_token')
            TOKEN_EXPIRY = now + timedelta(seconds=data.get('expires_in', 3600))
            return CACHED_TOKEN, None
        except Exception as e: return None, str(e)

    def do_GET(self):
        logs = []
        logs.append(f"時間: {datetime.now().strftime('%H:%M:%S')}")
        
        token, error_msg = self.get_token()
        if not token:
            self.send_response(500)
            self.wfile.write(f"Auth Fail".encode('utf-8'))
            return

        headers = {'authorization': f'Bearer {token}'}
        
        tz_taiwan = timezone(timedelta(hours=8))
        now_dt = datetime.now(tz_taiwan)
        today_str = now_dt.strftime('%Y-%m-%d')
        
        # 使用全日時刻表
        url = f"https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/DailyTimetable/Station/{START_STATION_ID}/{today_str}"
        delay_url = "https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/LiveTrainDelay"

        try:
            logs.append(f"正在查詢時刻表: {url}")
            res = requests.get(url, headers=headers).json()
            delay_res = requests.get(delay_url, headers=headers).json()
            
            logs.append(f"API 回傳原始筆數: {len(res) if isinstance(res, list) else '錯誤'}")

            delays = {}
            if isinstance(delay_res, list):
                for t in delay_res:
                    delays[t.get('TrainNo')] = t.get('DelayTime', 0)

            processed = []
            
            # ★★★ 南下終點站白名單 (包含所有可能的寫法) ★★★
            SOUTH_DESTS = ['潮州', '枋寮', '臺東', '台東', '花蓮', '知本', '玉里', '南州', '林邊', '大武', '枋野', '太麻里']
            
            # 統計用
            stats = {"total": 0, "pass_dest": 0, "pass_time": 0, "skipped_samples": []}

            if isinstance(res, list):
                stats["total"] = len(res)
                
                for t in res:
                    info = t.get('DailyTrainInfo', {})
                    train_no = info.get('TrainNo')
                    dest = info.get('EndingStationName', {}).get('Zh_tw', '未知')
                    
                    # 1. 終點站過濾 (Destination Filter)
                    # 只要終點站不在白名單裡，就當作是北上車 (往高雄/新左營/台北...)
                    if dest not in SOUTH_DESTS:
                        if len(stats["skipped_samples"]) < 3: # 記錄前3個被踢掉的，方便除錯
                            stats["skipped_samples"].append(f"{train_no}往{dest}")
                        continue
                    
                    stats["pass_dest"] += 1

                    # 2. 找出屏東發車時間
                    stop_times = t.get('StopTimes', [])
                    dep_time = ""
                    for s in stop_times:
                        if s['StationID'] == START_STATION_ID:
                            dep_time = s['DepartureTime']
                            break
                    
                    if not dep_time: continue

                    # 3. 時間過濾
                    sch_dep = dep_time[:5]
                    delay = delays.get(train_no, 0)
                    
                    try:
                        dep_dt = datetime.strptime(f"{today_str} {sch_dep}", "%Y-%m-%d %H:%M").replace(tzinfo=tz_taiwan)
                        real_dep = dep_dt + timedelta(minutes=delay)
                        
                        # 只顯示「現在 - 10分鐘」以後的車
                        if real_dep < now_dt - timedelta(minutes=10):
                            continue
                            
                        stats["pass_time"] += 1
                        
                    except: continue

                    t_type = info.get('TrainTypeName', {}).get('Zh_tw', '').replace("自強(3000)", "自強3000")
                    
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
            logs.append(f"過濾統計: Total={stats['total']}, 終點站符合={stats['pass_dest']}, 時間符合={stats['pass_time']}")
            logs.append(f"被過濾的範例(北上): {', '.join(stats['skipped_samples'])}")
            logs.append(f"最終顯示: {len(data)} 筆")

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
                cards_html = f'<div style="text-align:center; padding:50px; color:#444;">無符合班次</div>'
            
            debug_html = "<br>".join(logs)

            html = f"""
            <!DOCTYPE html>
            <html lang="zh-TW">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
                <meta http-equiv="refresh" content="60">
                <title>屏東南下時刻</title>
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
                    details {{ margin-top: 30px; border: 1px solid #333; border-radius: 8px; padding: 10px; background: #111; }}
                    summary {{ color: #888; cursor: pointer; font-size: 0.8rem; }}
                    pre {{ color: #0f0; font-size: 0.7rem; white-space: pre-wrap; margin: 10px 0 0 0; }}
                    a {{ text-decoration: none; color: inherit; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="update-time">全日時刻+終點過濾版</div>
                    <div class="header">
                        <h1 style="margin:0; font-size:1.3rem;">屏東 ➔ 往南 (潮州/台東)</h1>
                    </div>
                    {cards_html}
                    
                    <details>
                        <summary>🛠️ 開發者診斷資訊</summary>
                        <pre>{debug_html}</pre>
                    </details>
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
