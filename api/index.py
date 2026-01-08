    # === 修改：簡化後的 Header 偵測 ===
    def get_header_info(self, res):
        # 直接抓取剩餘次數 (TDX 通常是 x-ratelimit-remaining)
        # headers.get 是不分大小寫的
        remaining = res.headers.get('x-ratelimit-remaining')
        
        if remaining:
            return f"API {res.status_code} (剩: {remaining})"
        
        # 如果找不到剩餘次數，只回傳狀態碼
        return f"API {res.status_code}"
