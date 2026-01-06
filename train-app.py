import requests
import json
import os
from datetime import datetime, timedelta

# ================= 設定區 (從 GitHub Secrets 讀取) =================
CLIENT_ID = os.environ.get('TDX_ID')
CLIENT_SECRET = os.environ.get('TDX_SECRET')
START_STATION_ID = '5000' # 屏東
END_STATION_ID = '5030'   # 潮州
# =================================================================

class TrainApp:
    def __init__(self, cid, csecret):
        self.cid = cid
        self.csecret = csecret
        self.token = self.get_token()

    def get_token(self):
        auth_url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
        res = requests.post(auth_url, data={
            'grant_type': 'client_credentials',
            'client_id': self.cid,
            'client_secret': self.csecret
        })
        return res.json().get('access_token')

    def fetch_data(self):
        headers = {'authorization': f'Bearer {self.token}'}
        today = datetime.now().strftime('%Y-%m-%d')
        url = f"https://tdx.transportdata.tw/api/basic/v3/Rail/TRA/DailyTimetable/OD/{START_STATION_ID}/to/{END_STATION_ID}/{today}"
        delay_url = "https://tdx.transportdata.tw/api/basic/v3/Rail/TRA/LiveTrainDelay"
        
        try:
            trains = requests.get(url, headers=headers).json().get('TrainTimetables', [])
            delays = {t['TrainNo']: t.get('DelayTime', 0) for t in requests.get(delay_url, headers=headers).json().get('LiveTrainDelays', [])}
        except:
            return []
        
        processed = []
        now = datetime.now()
        
        for t in trains:
            no = t['TrainInfo']['TrainNo']
            type_name = t['TrainInfo']['TrainTypeName']['Zh_tw']
            dep_s = t['StopTimes'][0]['DepartureTime']
            arr_s = t['StopTimes'][1]['ArrivalTime']
            delay = delays.get(no, 0)
            
            dep_dt = datetime.strptime(f"{today} {dep_s}", "%Y-%m-%d %H:%M")
            arr_dt = datetime.strptime(f"{today} {arr_s}", "%Y-%m-%d %H:%M")
            real_dep = dep_dt + timedelta(minutes=delay)
            real_arr = arr_dt + timedelta(minutes=delay)
            
            # 顯示「現在時間前 15 分鐘」到「未來 120 分鐘」的車
            # 只要是「現在之後」發車的班次，全部都顯示出來
        if real_dep > now - timedelta(minutes=10):
                processed.append({
                    "no": no, "type": type_name, "delay": delay,
                    "act_dep": real_dep.strftime("%H:%M"),
                    "act_arr": real_arr.strftime("%H:%M"),
                    "sch_dep": dep_s, "sch_arr": arr_s,
                    "sort_key": real_dep
                })
        
        return sorted(processed, key=lambda x: x['sort_key'])

    def generate_html(self, data):
        html_template = """
        <!DOCTYPE html>
        <html lang="zh-TW">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <meta http-equiv="refresh" content="60">
            <title>智慧時刻表</title>
            <style>
                body { background: #000; color: #fff; font-family: sans-serif; padding: 15px; margin: 0; }
                .container { max-width: 500px; margin: 0 auto; }
                .header { padding: 20px 0; border-bottom: 1px solid #333; margin-bottom: 20px; }
                .card { background: #1c1c1e; border-radius: 16px; padding: 20px; margin-bottom: 15px; border-left: 6px solid #30d158; }
                .late-card { border-left-color: #ff453a; }
                .train-info { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
                .train-no { color: #8e8e93; font-size: 0.9rem; font-weight: bold; }
                .delay-badge { background: #ff453a; color: white; padding: 3px 10px; border-radius: 10px; font-size: 0.8rem; font-weight: bold; }
                .main-time { display: flex; align-items: center; justify-content: center; font-size: 2.6rem; font-weight: 900; }
                .arrow { margin: 0 15px; color: #444; font-size: 1.5rem; }
                .sub-time { text-align: center; color: #636366; font-size: 0.85rem; margin-top: 12px; padding-top: 10px; border-top: 1px solid #2c2c2e; }
                .update-time { text-align: center; color: #48484a; font-size: 0.75rem; margin-top: 20px; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1 style="margin:0; font-size:1.5rem;">屏東 ➔ 潮州</h1>
                    <div style="color:#8e8e93; font-size:0.9rem; margin-top:5px;">智慧即時排序看板</div>
                </div>
                {% CARDS %}
                <div class="update-time">最後更新時間：""" + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + """</div>
            </div>
        </body>
        </html>
        """
        cards_html = ""
        for t in data:
            delay_tag = f'<div class="delay-badge">晚 {t["delay"]} 分</div>' if t['delay'] > 0 else ""
            card_style = "late-card" if t['delay'] > 0 else ""
            cards_html += f"""
            <div class="card {card_style}">
                <div class="train-info"><span class="train-no">{t['type']} {t['no']} 次</span>{delay_tag}</div>
                <div class="main-time"><span>{t['act_dep']}</span><span class="arrow">➔</span><span>{t['act_arr']}</span></div>
                <div class="sub-time">原定：{t['sch_dep']} ➔ {t['sch_arr']}</div>
            </div>
            """
        if not data:
            cards_html = '<div style="text-align:center; padding:50px; color:#666;">目前時段暫無班次</div>'

        with open("index.html", "w", encoding="utf-8") as f:
            f.write(html_template.replace("{% CARDS %}", cards_html))

if __name__ == "__main__":
    if CLIENT_ID and CLIENT_SECRET:
        app = TrainApp(CLIENT_ID, CLIENT_SECRET)
        data = app.fetch_data()
        app.generate_html(data)
