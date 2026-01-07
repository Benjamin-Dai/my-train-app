import requests
import json
import os
from datetime import datetime, timedelta, timezone

# ================= 設定區 =================
CLIENT_ID = os.environ.get('TDX_ID')
CLIENT_SECRET = os.environ.get('TDX_SECRET')
START_STATION_ID = '5000'
# =========================================

class TrainApp:
    def __init__(self, cid, csecret):
        self.cid = cid
        self.csecret = csecret
        self.token = self.get_token()

    def get_token(self):
        auth_url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
        try:
            res = requests.post(auth_url, data={
                'grant_type': 'client_credentials', 'client_id': self.cid, 'client_secret': self.csecret
            })
            if res.status_code != 200: return None
            return res.json().get('access_token')
        except: return None

    def fetch_data(self):
        if not self.token: return []
        headers = {'authorization': f'Bearer {self.token}'}
        url = f"https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/LiveBoard/Station/{START_STATION_ID}"

        try:
            res = requests.get(url, headers=headers).json()
            processed = []
            
            # 手動設定台灣時區
            tz_taiwan = timezone(timedelta(hours=8))
            now_dt = datetime.now(tz_taiwan)

            if isinstance(res, list):
                for t in res:
                    # Direction: 0 = 順行 (往南)
                    if t.get('Direction') == 0: 
                        train_no = t['TrainNo']
                        t_type = t['TrainTypeName']['Zh_tw'].replace("自強(3000)", "自強3000")
                        sch_dep = t['ScheduledDepartureTime']
                        delay = t.get('DelayTime', 0)
                        dest = t.get('EndingStationName', {}).get('Zh_tw', '未知')
                        
                        dep_dt = datetime.strptime(f"{now_dt.strftime('%Y-%m-%d')} {sch_dep}", "%Y-%m-%d %H:%M").replace(tzinfo=tz_taiwan)
                        if dep_dt < now_dt - timedelta(hours=12): dep_dt += timedelta(days=1)
                        real_dep = dep_dt + timedelta(minutes=delay)
                        
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
            
            return sorted(processed, key=lambda x: x['sort_key'])
        except: return []

    def generate_html(self, data):
        tz_taiwan = timezone(timedelta(hours=8))
        update_time = datetime.now(tz_taiwan).strftime("%H:%M:%S")

        html_template = """
        <!DOCTYPE html>
        <html lang="zh-TW">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
            <meta http-equiv="refresh" content="60">
            <title>屏東車站看板</title>
            <style>
                body { background: #000; color: #fff; font-family: -apple-system, sans-serif; padding: 10px; margin: 0; }
                .container { max-width: 500px; margin: 0 auto; }
                .update-time { color: #999; font-size: 0.65rem; text-align: right; margin-bottom: 8px; }
                .header { padding: 0 5px; display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
                .card { background: #151517; border-radius: 12px; padding: 10px 16px; margin-bottom: 8px; border-left: 5px solid #333; position: relative; }
                .delay-badge { position: absolute; top: 12px; right: 16px; border: 1px solid #f2a900; color: #f2a900; padding: 1px 5px; border-radius: 4px; font-size: 0.65rem; font-weight: 600; }
                .train-info { font-size: 0.82rem; font-weight: 700; margin-bottom: 2px; }
                .main-time { display: flex; align-items: center; justify-content: center; font-size: 1.8rem; font-weight: 700; padding: 4px 0; }
                .sub-time { text-align: center; color: #999; font-size: 0.7rem; }
                a { text-decoration: none; color: inherit; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="update-time">Github 快照時間：""" + update_time + """</div>
                <div class="header">
                    <h1 style="margin:0; font-size:1.3rem;">屏東 ➔ 往南 (潮州/台東)</h1>
                </div>
                {% CARDS %}
            </div>
        </body>
        </html>
        """
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
            cards_html = '<div style="text-align:center; padding:50px; color:#444;">看板目前無資料</div>'
        
        with open("index.html", "w", encoding="utf-8") as f:
            f.write(html_template.replace("{% CARDS %}", cards_html))

if __name__ == "__main__":
    app = TrainApp(CLIENT_ID, CLIENT_SECRET)
    data = app.fetch_data()
    app.generate_html(data)
