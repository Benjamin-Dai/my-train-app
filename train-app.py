import requests
import json
import os
from datetime import datetime, timedelta

# ================= 設定區 =================
CLIENT_ID = os.environ.get('TDX_ID')
CLIENT_SECRET = os.environ.get('TDX_SECRET')
# 如果要換地點，直接修改這裡
START_STATION_NAME = '屏東'
END_STATION_NAME = '潮州'
# =========================================

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
        now = datetime.now()
        today = now.strftime('%Y-%m-%d')
        
        url = "https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/DailyTimetable/Today"
        delay_url = "https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/LiveTrainDelay"
        
        try:
            res = requests.get(url, headers=headers)
            all_trains = res.json()
            delay_res = requests.get(delay_url, headers=headers).json()
            delays = {t['TrainNo']: t.get('DelayTime', 0) for t in delay_res}
            
            processed = []
            for t in all_trains:
                stop_times = t['StopTimes']
                stations = [s['StationName']['Zh_tw'] for s in stop_times]
                
                if START_STATION_NAME in stations and END_STATION_NAME in stations:
                    idx_start = stations.index(START_STATION_NAME)
                    idx_end = stations.index(END_STATION_NAME)
                    
                    if idx_start < idx_end:
                        no = t['DailyTrainInfo']['TrainNo']
                        type_name = t['DailyTrainInfo']['TrainTypeName']['Zh_tw']
                        dep_s = stop_times[idx_start]['DepartureTime']
                        arr_s = stop_times[idx_end]['ArrivalTime']
                        delay = delays.get(no, 0)
                        
                        dep_dt = datetime.strptime(f"{today} {dep_s}", "%Y-%m-%d %H:%M")
                        arr_dt = datetime.strptime(f"{today} {arr_s}", "%Y-%m-%d %H:%M")
                        real_dep = dep_dt + timedelta(minutes=delay)
                        real_arr = arr_dt + timedelta(minutes=delay)
                        
                        if real_dep > now - timedelta(minutes=10):
                            processed.append({
                                "no": no, "type": type_name, "delay": delay,
                                "act_dep": real_dep.strftime("%H:%M"),
                                "act_arr": real_arr.strftime("%H:%M"),
                                "sch_dep": dep_s, "sch_arr": arr_s,
                                "sort_key": real_dep
                            })
            
            return sorted(processed, key=lambda x: x['sort_key'])
        except Exception as e:
            print(f"發生異常: {e}")
            return []

    def generate_html(self, data):
        html_template = """
        <!DOCTYPE html>
        <html lang="zh-TW">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
            <meta http-equiv="refresh" content="60">
            <title>列車動態時刻表</title>
            <style>
                body { background: #000; color: #fff; font-family: -apple-system, sans-serif; padding: 12px; margin: 0; }
                .container { max-width: 500px; margin: 0 auto; }
                .header { padding: 10px 5px; border-bottom: 1px solid #1c1c1e; margin-bottom: 15px; }
                .card { background: #151517; border-radius: 14px; padding: 10px 16px; margin-bottom: 8px; border-left: 5px solid #334439; }
                .late-card { border-left-color: hsl(40, 100%, 50%); }
                .train-info { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
                .train-no { color: #8e8e93; font-size: 0.8rem; font-weight: 500; }
                .delay-badge { background: hsl(40, 100%, 50%); color: #000; padding: 2px 7px; border-radius: 5px; font-size: 0.7rem; font-weight: 900; }
                .main-time { display: flex; align-items: center; justify-content: center; font-size: 1.8rem; font-weight: 800; }
                .arrow { margin: 0 10px; color: #2c2c2e; font-size: 0.9rem; }
                .sub-time { text-align: center; color: #48484a; font-size: 0.7rem; margin-top: 8px; padding-top: 8px; border-top: 1px solid #1c1c1e; }
                .update-time { text-align: center; color: #2c2c2e; font-size: 0.65rem; margin-top: 25px; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1 style="margin:0; font-size:1.4rem;">""" + START_STATION_NAME + """ ➔ """ + END_STATION_NAME + """</h1>
                    <div style="color:#8e8e93; font-size:0.85rem; margin-top:4px; font-weight: 300; letter-spacing: 1px;">專屬列車時刻導引</div>
                </div>
                {% CARDS %}
                <div class="update-time">最後數據更新：""" + datetime.now().strftime("%H:%M:%S") + """</div>
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
            cards_html = '<div style="text-align:center; padding:50px; color:#444;">目前時段暫無班次</div>'
        with open("index.html", "w", encoding="utf-8") as f:
            f.write(html_template.replace("{% CARDS %}", cards_html))

if __name__ == "__main__":
    app = TrainApp(CLIENT_ID, CLIENT_SECRET)
    data = app.fetch_data()
    app.generate_html(data)
