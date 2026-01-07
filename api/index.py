import requests
import json
import traceback
from datetime import datetime

# ================= 設定區 =================
CLIENT_ID = '你的CLIENT_ID' 
CLIENT_SECRET = '你的CLIENT_SECRET'
STATION_ID = '5000' # 屏東
TODAY = datetime.now().strftime('%Y-%m-%d')

# 我們用回你一開始成功抓到 197 筆資料的那個 V2 Station 介面
# 這是最有機會成功的
URL = f"https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/DailyTrainTimetable/Station/{STATION_ID}/{TODAY}"

# ================= 函式區 =================

def get_auth_token():
    try:
        auth_url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
        headers = {'content-type': 'application/x-www-form-urlencoded'}
        data = {
            'grant_type': 'client_credentials',
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET
        }
        response = requests.post(auth_url, headers=headers, data=data)
        response.raise_for_status()
        return response.json()['access_token']
    except Exception as e:
        return f"Token Error: {str(e)}"

def get_data_safe(token):
    # 如果 Token 本身就是錯誤訊息，直接回傳
    if isinstance(token, str) and token.startswith("Token Error"):
        return None, token

    headers = {'authorization': f'Bearer {token}'}
    try:
        print(f"正在連線: {URL}")
        response = requests.get(URL, headers=headers)
        
        if response.status_code == 200:
            return response.json(), None
        else:
            return None, f"API 錯誤代碼: {response.status_code}\n網址: {URL}\n訊息: {response.text}"
            
    except Exception as e:
        return None, f"連線發生例外: {str(e)}\n{traceback.format_exc()}"

def generate_html_always(data, error_msg):
    current_time = datetime.now().strftime('%H:%M:%S')
    
    # 開始寫 HTML 頭部
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>火車時刻表除錯頁</title>
        <style>
            body {{ font-family: sans-serif; padding: 20px; background: #333; color: #fff; }}
            .container {{ max-width: 800px; margin: 0 auto; background: #444; padding: 20px; border-radius: 10px; }}
            h2 {{ border-bottom: 1px solid #666; padding-bottom: 10px; }}
            .error-box {{ background: #c0392b; color: white; padding: 15px; border-radius: 5px; font-family: monospace; white-space: pre-wrap; }}
            .success-box {{ background: #27ae60; color: white; padding: 10px; margin-bottom: 10px; border-radius: 5px; }}
            .train-item {{ background: #555; padding: 10px; margin-bottom: 5px; border-left: 5px solid #3498db; display: flex; justify-content: space-between; }}
            .time {{ font-weight: bold; font-size: 1.2em; color: #f1c40f; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>執行報告 ({current_time})</h2>
    """

    # 如果有錯誤訊息，優先顯示紅色錯誤框
    if error_msg:
        html += f"""
            <h3>⚠️ 發生錯誤</h3>
            <div class="error-box">{error_msg}</div>
            <p>請將上面的錯誤訊息截圖或複製給 Gemini。</p>
        """
    
    # 如果有資料，嘗試解析並顯示
    if data:
        try:
            trains = data.get('StationTimetables', [])
            html += f"<div class='success-box'>API 連線成功！收到 {len(trains)} 筆原始資料。</div>"
            
            count = 0
            for item in trains:
                # 簡單解析邏輯
                info = item.get('TrainInfo', {})
                direction = info.get('Direction', -1)
                
                # 只顯示順行(0)
                if direction == 0:
                    train_no = info.get('TrainNo', '???')
                    dest = info.get('EndingStationName', {}).get('Zh_tw', '未知')
                    # 時間
                    stop_times = item.get('StopTimes', [])
                    time_str = stop_times[0].get('DepartureTime', '??:??') if stop_times else '??:??'
                    
                    # 只顯示未來的車
                    if time_str >= current_time[:5]:
                        count += 1
                        html += f"""
                        <div class="train-item">
                            <span class="time">{time_str}</span>
                            <span>{train_no} 次 - 往 {dest}</span>
                        </div>
                        """
            
            if count == 0:
                html += "<p>資料讀取成功，但過濾後沒有未來的車次。</p>"
                
        except Exception as e:
            html += f"""
            <h3>⚠️ 資料解析失敗</h3>
            <div class="error-box">{str(e)}</div>
            """

    html += """
        </div>
    </body>
    </html>
    """
    
    # 強制寫入檔案
    with open("train_schedule.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("✅ 網頁已強制生成！請打開 train_schedule.html 查看結果或錯誤訊息。")

# ================= 主程式 =================
if __name__ == "__main__":
    # 1. 取得 Token
    token = get_auth_token()
    
    # 2. 嘗試抓資料 (就算失敗也會回傳 None)
    data, error = get_data_safe(token)
    
    # 3. 不管怎樣，生成網頁！
    generate_html_always(data, error)
