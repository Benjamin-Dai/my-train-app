import requests
import json
import os
from datetime import datetime, timedelta, timezone

# ================= 設定區 =================
CLIENT_ID = os.environ.get('TDX_ID')
CLIENT_SECRET = os.environ.get('TDX_SECRET')
START_STATION_ID = '5000'  # 屏東站
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
                'grant_type': 'client_credentials',
                'client_id': self.cid,
                'client_secret': self.csecret
            })
            if res.status_code != 200:
                return None
            return res.json().get('access_token')
        except:
            return None

    def fetch_data(self):
        # 準備診斷訊息
        self.debug_info = []
        
        if not self.token:
            self.debug_info.append("錯誤: 無法取得 Token")
            return []
        
        headers = {'authorization': f'Bearer {self.token}'}
        url = f"https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/LiveBoard/Station/{START_STATION_ID}"

        try:
            self.debug_info.append(f"正在連線: {url}")
            res = requests.get(url, headers=headers).json()
            
            # 如果 API 回傳錯誤訊息
            if isinstance(res, dict) and 'Message' in res:
                self.debug_info.append(f"API 回傳錯誤: {res['Message']}")
                return []

            self.debug_info.append(f"API 回傳資料型態: {type(res)}")
            if isinstance(res, list):
                self.debug_info.append(f"API 回傳筆數: {len(res)}")
            else:
                self.debug_info.append(f"原始回傳內容: {str(res)}")
                return []

            processed = []
            
            # ★★★ 關鍵：不做任何篩選，全抓！ ★★★
            for t in res:
                train_no = t['TrainNo']
                t_type = t['TrainTypeName']['Zh_tw'].replace("自強(3000)", "自強3000")
                direction = t.get('Direction', -1) # 0順行 1逆行
                dest = t.get('EndingStationName', {}).get('Zh_tw', '未知')
                sch_dep = t['ScheduledDepartureTime']
                delay = t.get('DelayTime', 0)
                
                # 標示方向文字
                dir_text = "順行(往南)" if direction == 0 else "逆行(往北)"
                
                # 時間處理
                tz_taiwan = timezone(timedelta(hours=8))
                now_dt = datetime.now(tz_taiwan)
                dep_dt = datetime.strptime(f"{now_dt.strftime('%Y-%m-%d')} {sch_dep}", "%Y-%m-%d %H:%M").replace(tzinfo=tz_taiwan)
                
                if dep_dt < now_dt - timedelta(hours=12):
                    dep_dt += timedelta(days=1)
                
                real_dep = dep_dt + timedelta(minutes=delay)
                
                # 顏色區分
                color = "#666666" # 預設灰色
                if direction == 0: color = "#28a745" # 往南顯示綠色
                elif direction == 1: color = "#007bff" # 往北顯示藍色

                processed.append({
                    "no": train_no,
                    "type": t_type,
                    "dir_text": dir_text, # 顯示方向
                    "delay": delay,
                    "color": color,
                    "act_dep": real_dep.strftime("%H:%M"),
                    "sch_dep": sch_dep,
                    "dest": dest,
                    "sort_key": real_dep
                })
            
            return sorted(processed, key=lambda x: x['sort_key'])
        except Exception as e:
            self.debug_info.append(f"程式執行錯誤: {str(e)}")
            return []

    def generate_html(self, data):
        tz_taiwan = timezone(timedelta(hours=8))
        update_time = datetime.now(tz_taiwan).strftime("%H:%M:%S")

        html_template = """
        <!DOCTYPE html>
        <html lang="zh-TW">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
            <title>屏東車站全診斷</title>
            <style>
                body { background: #000; color: #fff; font-family: -apple-system, sans-serif; padding: 10px; margin: 0; }
                .container { max-width: 500px; margin: 0 auto; }
                .header { padding: 10px; background: #222; margin-bottom: 10px; border-radius: 8px; }
                .card { background: #151517; border-radius: 12px; padding: 10px 16px; margin-bottom: 8px; border-left: 5px solid #666; position: relative; }
                .debug-box { background: #330000; color: #ffcccc; padding: 15px; margin-top: 20px; font-size: 0.8rem; border-radius: 8px; font-family: monospace; word-break: break-all; }
                .train-info { font-size: 0.9rem; font-weight: 700; margin-bottom: 4px; }
                .sub-info { font-size: 0.8rem; color: #aaa; }
                .time { font-size: 1.5rem; font-weight: bold; color: #fff; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h3>🔍 超級診斷模式</h3>
                    <small>更新時間: """ + update_time + """</small>
                </div>
                
                {% CARDS %}
                
                <div class="debug-box">
                    <strong>開發者診斷資訊：</strong><br>
                    {% DEBUG %}
                </div>
            </div>
        </body>
        </html>
        """
        
        cards_html = ""
        for t in data:
            delay_text = f" (誤點 {t['delay']}分)" if t['delay'] > 0 else ""
            cards_html += f"""
            <div class="card" style="border-left-color: {t['color']};">
                <div class="train-info">{t['type']} {t['no']} 次 - {t['dir_text']}</div>
                <div class="sub-info">往 {t['dest']} {delay_text}</div>
                <div class="time">{t['act_dep']} <small style="font-size:0.8rem; color:#888;">(原 {t['sch_dep']})</small></div>
            </div>
            """
        
        if not data:
            cards_html = '<div style="text-align:center; padding:30px; color:#888;">⚠️ 沒有抓到任何車次</div>'
        
        # 組合 Debug 訊息
        debug_html = "<br>".join(self.debug_info)

        with open("index.html", "w", encoding="utf-8") as f:
            content = html_template.replace("{% CARDS %}", cards_html).replace("{% DEBUG %}", debug_html)
            f.write(content)

if __name__ == "__main__":
    app = TrainApp(CLIENT_ID, CLIENT_SECRET)
    data = app.fetch_data()
    app.generate_html(data)
