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
        
        # 使用 V2 版本的 API (全台當日時刻表)
        url = "https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/DailyTimetable/Today"
        delay_url = "https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/LiveTrainDelay"
        
        print(f"--- 執行除錯資訊 (V2 版本) ---")
        print(f"目前台灣時間: {now.strftime('%Y-%m-%d %H:%M:%S')}")
        
        try:
            # 1. 抓取時刻表
            res = requests.get(url, headers=headers)
            all_trains = res.json()
            print(f"成功連線 V2 API，原始資料包含 {len(all_trains)} 班車次")
            
            # 2. 抓取誤點
            delay_res = requests.get(delay_url, headers=headers).json()
            delays = {t['TrainNo']: t.get('DelayTime', 0) for t in delay_res}
            
            processed = []
            for t in all_trains:
                # 篩選起點與終點
                stop_times = t['StopTimes']
                stations = [s['StationName']['Zh_tw'] for s in stop_times]
                
                if START_STATION_NAME in stations and END_STATION_NAME in stations:
                    idx_start = stations.index(START_STATION_NAME)
                    idx_end = stations.index(END_STATION_NAME)
                    
                    if idx_start < idx_end:
                        no = t['DailyTrainInfo']['TrainNo']
                        type_name = t['DailyTrainInfo']['TrainTypeName']['Zh_tw']
                        dep_s = stop_times[idx_start]['DepartureTime']
                        delay = delays.get(no, 0)
                        
                        dep_dt = datetime.strptime(f"{today} {dep_s}", "%Y-%m-%d %H:%M")
                        real_dep = dep_dt + timedelta(minutes=delay)
                        
                        if real_dep > now - timedelta(minutes=10):
                            processed.append({
                                "no": no, "type": type_name, "delay": delay,
                                "act_dep": real_dep.strftime("%H:%M"),
                                "sch_dep": dep_s,
                                "sort_key": real_dep
                            })
            
            print(f"篩選出 {START_STATION_NAME} 往 {END_STATION_NAME} 班次，共 {len(processed)} 班")
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
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <meta http-equiv="refresh" content="60">
            <title>智慧火車時刻表</title>
            <style>
                body { background: #000; color: #fff; font-family: sans-serif; padding: 15px; margin: 0; }
                .container { max-width: 500px; margin: 0 auto; }
                .header { padding: 20px 0; border-bottom: 1px solid #333; margin-bottom: 20px; }
                .card { background: #1c1c1e; border-radius: 16px; padding: 20px; margin-bottom: 15px; border-left: 6px solid #30d158; }
                .late-card { border-left-color: #ff453a; }
                .train-info { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
                .train-no { color: #8e8e93; font-size: 0.9rem; font-weight: bold; }
                .delay-badge { background: #ff453a; color: white; padding: 3px 10px; border-radius: 10px; font-size: 0.8rem; font-weight: bold; }
                .main-time { display: flex; align-items: center; justify-content: center; font-size: 2.8rem; font-weight: 900; }
                .arrow { margin: 0 15px; color: #444; font-size: 1.5rem; }
                .update-time { text-align: center; color: #48484a; font-size: 0.75rem; margin-top: 30px; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1 style="margin:0; font-size:1.6rem;">屏東 ➔ 潮州</h1>
                    <div style="color:#8e8e93; font-size:0.9rem; margin-top:5px;">智慧時刻看板 (V2 穩定版)</div>
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
                <div class="main-time"><span>{t['act_dep']}</span><span class="arrow">➔</span><span>GO</span></div>
                <div class="sub-time">原定：{t['sch_dep']}</div>
            </div>
            """
        if not data:
            cards_html = '<div style="text-align:center; padding:50px; color:#666;">目前時段暫無班次 (V2)</div>'
        with open("index.html", "w", encoding="utf-8") as f:
            f.write(html_template.replace("{% CARDS %}", cards_html))

if __name__ == "__main__":
    app = TrainApp(CLIENT_ID, CLIENT_SECRET)
    data = app.fetch_data()
    app.generate_html(data)

