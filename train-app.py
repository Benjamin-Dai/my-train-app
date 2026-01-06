import requests
import json
import os
from datetime import datetime, timedelta

# ================= 設定區 =================
CLIENT_ID = os.environ.get('TDX_ID')
CLIENT_SECRET = os.environ.get('TDX_SECRET')
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
                        
                        # 定義顏色邏輯
                        card_color = "#334439" # 預設深綠
                        if "區間" in type_name:
                            card_color = "#007aff" # 藍色
                        elif "自強" in type_name:
                            if any(x in type_name for x in ["3000", "普悠瑪", "太魯閣"]):
                                card_color = "#800020" # 酒紅
                            else:
                                card_color = "#ff3b30" # 亮紅
                        
                        dep_dt = datetime.strptime(f"{today} {dep_s}", "%Y-%m-%d %H:%M")
                        arr_dt = datetime.strptime(f"{today} {arr_s}", "%Y-%m-%d %H:%M")
                        real_dep = dep_dt + timedelta(minutes=delay)
                        real_arr = arr_dt + timedelta(minutes=delay)
                        
                        if real_dep > now - timedelta(minutes=10):
                            processed.append({
                                "no": no, "type": type_name, "delay": delay, "color": card_color,
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
            <title>列車時刻</title>
            <style>
                body { background: #000; color: #fff; font-family: -apple-system, sans-serif; padding: 10px; margin: 0; }
                .container { max-width: 500px; margin: 0 auto; }
                .header { padding: 5px; display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 15px; }
                .update-time { color: #48484a; font-size: 0.7rem; font-weight: 400; }
                .card { background: #151517; border-radius: 12px; padding: 12px 16px; margin-bottom: 10px; border-left: 4px solid #333; position: relative; }
                .delay-badge { position: absolute; top: 12px; right: 16px; background: hsl(40, 100%, 50%); color: #000; padding: 2px 6px; border-radius: 4px; font-size: 0.7rem; font-weight: 800; }
                .train-info { font-size: 0.8rem; font-weight: 500; margin-bottom: 2px; }
                .main-time { display: flex; align-items: center; justify-content: center; font-size: 1.8rem; font-weight: 700; padding: 5px 0; }
                .arrow { margin: 0 15px; color: #2c2c2e; font-size: 0.8rem; }
                .sub-time { text-align: center; color: #48484a; font-size: 0.7rem; margin-top: 5px; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="update-time" style="text-align: right; margin-bottom: 5px;">最後更新：""" + datetime.now().strftime("%H:%M:%S") + """</div>
                <div class="header">
                    <h1 style="margin:0; font-size:1.4rem; letter-spacing: -0.5px;">""" + START_STATION_NAME + """ ➔ """ + END_STATION_NAME + """</h1>
                    <span style="color: #636366; font-size: 0.75rem;">列車動態導引</span>
                </div>
                {% CARDS %}
            </div>
        </body>
        </html>
        """
        cards_html = ""
        for t in data:
            delay_tag = f'<div class="delay-badge">晚 {t["delay"]} 分</div>' if t['delay'] > 0 else ""
            # 如果誤點，邊框改為橘色，否則使用車種顏色
            border_color = "hsl(40, 100%, 50%)" if t['delay'] > 0 else t['color']
            
            cards_html += f"""
            <div class="card" style="border-left-color: {border_color};">
                {delay_tag}
                <div class="train-info" style="color: {t['color']};">{t['type']} {t['no']} 次</div>
                <div class="main-time"><span>{t['act_dep']}</span><span class="arrow">➔</span><span>{t['act_arr']}</span></div>
                <div class="sub-time">原定 {t['sch_dep']} ➔ {t['sch_arr']}</div>
            </div>
            """
        if not data:
            cards_html = '<div style="text-align:center; padding:50px; color:#444;">目前無符合班次</div>'
        with open("index.html", "w", encoding="utf-8") as f:
            f.write(html_template.replace("{% CARDS %}", cards_html))

if __name__ == "__main__":
    app = TrainApp(CLIENT_ID, CLIENT_SECRET)
    data = app.fetch_data()
    app.generate_html(data)
