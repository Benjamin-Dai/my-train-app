import requests
import json
import os
from datetime import datetime, timedelta

# ================= 設定區 =================
CLIENT_ID = os.environ.get('TDX_ID')
CLIENT_SECRET = os.environ.get('TDX_SECRET')
START_STATION_NAME = '屏東'
START_STATION_ID = '5000'  # 屏東站
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
        token = res.json().get('access_token')
        print(f"DEBUG: Token 取得狀態: {'成功' if token else '失敗'}")
        return token

    def fetch_data(self):
        headers = {'authorization': f'Bearer {self.token}'}
        now = datetime.now()
        today = now.strftime('%Y-%m-%d')
        
        # 使用精確的車站 API
        url = f"https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/DailyTimetable/Station/{START_STATION_ID}/{today}"
        delay_url = "https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/LiveTrainDelay"

        try:
            print(f"DEBUG: 正在請求時刻表 API: {url}")
            res = requests.get(url, headers=headers).json()
            print(f"DEBUG: 原始抓取總筆數: {len(res)}")

            delay_res = requests.get(delay_url, headers=headers).json()
            delays = {t['TrainNo']: t.get('DelayTime', 0) for t in delay_res}
            print(f"DEBUG: 即時誤點資料筆數: {len(delay_res)}")

            processed = []
            for t in res:
                stop_times = t['StopTimes']
                stations = [s['StationName']['Zh_tw'].strip() for s in stop_times]

                # 檢查是否經過目的地
                if END_STATION_NAME in stations:
                    idx_start = stations.index(START_STATION_NAME)
                    idx_end = stations.index(END_STATION_NAME)

                    # 檢查方向 (屏東 -> 潮州)
                    if idx_start < idx_end:
                        no = t['DailyTrainInfo']['TrainNo']
                        dep_s = stop_times[idx_start]['DepartureTime']
                        delay = delays.get(no, 0)
                        
                        dep_dt = datetime.strptime(f"{today} {dep_s}", "%Y-%m-%d %H:%M")
                        real_dep = dep_dt + timedelta(minutes=delay)

                        # --- 測試優化：放寬時間過濾到過去 2 小時，避免 Action 延遲導致空白 ---
                        if real_dep > now - timedelta(hours=2):
                            raw_type = t['DailyTrainInfo']['TrainTypeName']['Zh_tw']
                            arr_s = stop_times[idx_end]['ArrivalTime']
                            
                            processed.append({
                                "no": no, 
                                "type": self.simplify_type(raw_type), 
                                "delay": delay, 
                                "color": self.get_color(raw_type),
                                "act_dep": real_dep.strftime("%H:%M"),
                                "act_arr": (datetime.strptime(f"{today} {arr_s}", "%Y-%m-%d %H:%M") + timedelta(minutes=delay)).strftime("%H:%M"),
                                "sch_dep": dep_s, 
                                "sch_arr": arr_s,
                                "sort_key": real_dep
                            })
                            print(f"DEBUG: 找到符合班次: {no} ({raw_type}) - 預計開車 {real_dep.strftime('%H:%M')}")

            print(f"DEBUG: 過濾後最終顯示筆數: {len(processed)}")
            return sorted(processed, key=lambda x: x['sort_key'])
        except Exception as e:
            print(f"DEBUG 異常發生: {e}")
            return []

    def get_color(self, raw_type):
        if "區間" in raw_type: return "#0076B2"
        if "3000" in raw_type: return "#85a38f"
        if "自強" in raw_type: return "#DF3F1F"
        if "普悠瑪" in raw_type or "太魯閣" in raw_type: return "#9C1637"
        return "#ffffff"

    def simplify_type(self, raw_type):
        if "區間快" in raw_type: return "區間快"
        if "區間" in raw_type: return "區間車"
        if "3000" in raw_type: return "自強3000"
        if "自強" in raw_type: return "自強號"
        return raw_type

    def generate_html(self, data):
        html_template = """
        <!DOCTYPE html>
        <html lang="zh-TW">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
            <meta http-equiv="refresh" content="10">
            <title>列車時刻 (DEBUG版)</title>
            <style>
                body { background: #000; color: #fff; font-family: -apple-system, sans-serif; padding: 10px; margin: 0; }
                .container { max-width: 500px; margin: 0 auto; }
                .update-time { color: #999999; font-size: 0.65rem; text-align: right; margin-bottom: 8px; }
                .header { padding: 0 5px; display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
                .card { background: #151517; border-radius: 12px; padding: 10px 16px; margin-bottom: 8px; border-left: 5px solid #333; position: relative; }
                .delay-badge { position: absolute; top: 12px; right: 16px; border: 1px solid #f2a900; color: #f2a900; padding: 1px 5px; border-radius: 4px; font-size: 0.65rem; font-weight: 600; }
                .train-info { font-size: 0.82rem; font-weight: 700; margin-bottom: 2px; }
                .main-time { display: flex; align-items: center; justify-content: center; font-size: 1.8rem; font-weight: 700; padding: 4px 0; }
                .arrow { margin: 0 12px; color: #999999; font-size: 0.8rem; }
                .sub-time { text-align: center; color: #999999; font-size: 0.7rem; }
                a { text-decoration: none; color: inherit; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="update-time">最後更新：""" + datetime.now().strftime("%H:%M:%S") + """</div>
                <div class="header">
                    <h1 style="margin:0; font-size:1.3rem;">""" + START_STATION_NAME + """ ➔ """ + END_STATION_NAME + """</h1>
                    <span style="font-size: 0.6rem; color: #444;">Debug Mode</span>
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
                    <div class="train-info" style="color: {t['color']};">{t['type']} {t['no']} 次</div>
                    <div class="main-time"><span>{t['act_dep']}</span><span class="arrow">➔</span><span>{t['act_arr']}</span></div>
                    <div class="sub-time">原定 {t['sch_dep']} ➔ {t['sch_arr']}</div>
                </div>
            </a>"""
        
        if not data:
            cards_html = '<div style="text-align:center; padding:50px; color:#444;">目前無符合班次 (已放寬過濾條件)</div>'
            
        with open("index.html", "w", encoding="utf-8") as f:
            f.write(html_template.replace("{% CARDS %}", cards_html))

if __name__ == "__main__":
    app = TrainApp(CLIENT_ID, CLIENT_SECRET)
    data = app.fetch_data()
    app.generate_html(data)
