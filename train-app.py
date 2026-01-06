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
                        raw_type = t['DailyTrainInfo']['TrainTypeName']['Zh_tw']
                        
                        # --- 精確名稱簡化與顏色邏輯 ---
                        display_type = raw_type
                        type_color = "#ffffff" # 預設白
                        
                        if "區間快" in raw_type:
                            display_type = "區間快"
                            type_color = "#0076B2" # 藍
                        elif "區間" in raw_type:
                            display_type = "區間車"
                            type_color = "#0076B2" # 藍
                        elif "普悠瑪" in raw_type:
                            display_type = "普悠瑪"
                            type_color = "#9C1637" # 酒紅
                        elif "3000" in raw_type:
                            display_type = "自強3000"
                            type_color = "#85a38f" # 深綠
                        elif "自強" in raw_type:
                            display_type = "自強號"
                            type_color = "#DF3F1F" # 亮紅
                        elif "太魯閣" in raw_type:
                            display_type = "太魯閣"
                            type_color = "#9C1637" # 酒紅

                        dep_s = stop_times[idx_start]['DepartureTime']
                        arr_s = stop_times[idx_end]['ArrivalTime']
                        delay = delays.get(no, 0)
                        
                        dep_dt = datetime.strptime(f"{today} {dep_s}", "%Y-%m-%d %H:%M")
                        arr_dt = datetime.strptime(f"{today} {arr_s}", "%Y-%m-%d %H:%M")
                        real_dep = dep_dt + timedelta(minutes=delay)
                        real_arr = arr_dt + timedelta(minutes=delay)
                        
                        # 過濾：顯示 10 分鐘前到今天的車
                        if real_dep > now - timedelta(minutes=10):
                            processed.append({
                                "no": no, "type": display_type, "delay": delay, "color": type_color,
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
            <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">

            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
            <meta http-equiv="refresh" content="30">
            <title>列車時刻導引</title>
            <style>
                body { background: #000; color: #fff; font-family: -apple-system, sans-serif; padding: 10px; margin: 0; }
                .container { max-width: 500px; margin: 0 auto; }
                .update-time { color: #999999; font-size: 0.65rem; text-align: right; margin-bottom: 8px; }
                .header { padding: 0 5px; display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
                .card { background: #151517; border-radius: 12px; padding: 10px 16px; margin-bottom: 8px; border-left: 5px solid #333; position: relative; }
                .delay-badge { position: absolute; top: 12px; right: 16px; border: 1px solid hsl(40, 100%, 50%); color: hsl(40, 100%, 50%); padding: 1px 5px; border-radius: 4px; font-size: 0.65rem; font-weight: 600; }
                .train-info { font-size: 0.82rem; font-weight: 700; margin-bottom: 2px; }
                .main-time { display: flex; align-items: center; justify-content: center; font-size: 1.8rem; font-weight: 700; padding: 4px 0; }
                .arrow { margin: 0 12px; color: #2c2c2e; font-size: 0.8rem; }
                .sub-time { text-align: center; color: #999999; font-size: 0.7rem; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="update-time">上次更新時間(約每五分鐘)：""" + datetime.now().strftime("%H:%M:%S") + """</div>
                <div class="header">
                    <h1 style="margin:0; font-size:1.3rem;">""" + START_STATION_NAME + """ ➔ """ + END_STATION_NAME + """</h1>
                    <span style="color: #3a3a3c; font-size: 0.7rem;">by Benjamin Dai</span>
                </div>
                {% CARDS %}
            </div>
        </body>
        </html>
        """
        cards_html = ""
        for t in data:
            delay_tag = f'<div class="delay-badge">誤點 {t["delay"]} 分</div>' if t['delay'] > 0 else ""
            cards_html += f"""
            <div class="card" style="border-left-color: {t['color']};">
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
