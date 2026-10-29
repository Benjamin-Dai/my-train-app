const STATION_INDEX={};Object.keys(STATION_DATA).forEach(r=>{STATION_DATA[r].forEach(s=>{STATION_INDEX[s]=r;});});
const DEFAULT_STATIONS = {"基隆市": "基隆", "新北市": "板橋", "臺北市": "臺北", "桃園市": "桃園", "新竹縣市": "新竹", "苗栗縣": "苗栗", "臺中市": "臺中", "彰化縣": "彰化", "南投縣": "集集", "雲林縣": "斗六", "嘉義縣市": "嘉義", "臺南市": "臺南", "高雄市": "高雄", "屏東縣": "屏東", "宜蘭縣": "羅東", "花蓮縣": "花蓮", "臺東縣": "臺東"};

const CACHE_PREFIX="train_data_v2_";
const PREF_START_R_KEY="pref_start_region";const PREF_START_S_KEY="pref_start_station";
const PREF_END_R_KEY="pref_end_region";const PREF_END_S_KEY="pref_end_station";

const LS_SKELETON_COUNT="tl_skeleton_count";

const startRegion=document.getElementById('startRegion');const startStation=document.getElementById('startStation');
const endRegion=document.getElementById('endRegion');const endStation=document.getElementById('endStation');
const btnAction=document.getElementById('btnAction');
const statusMsg=document.getElementById('statusMsg');const updateTimeDiv=document.getElementById('updateTime');
const list=document.getElementById('cardList');const btnInstall = document.getElementById('btnInstall');
const resumePill = document.getElementById('resumePill'); 

let retryTimer=null; let actionTicker=null; let isFetching=false;
const LS_SEARCH_COUNT="tl_search_count";const LS_SEARCH_RESET="tl_search_reset_time";
const LS_SEARCH_LOCK="tl_search_locked_until";const LS_REFRESH_LOCK="tl_refresh_locked_until";
const LS_UI_LOCK = "tl_ui_button_locked_until"; 

const LS_IS_24H="tl_pref_is_24h"; 
const LS_ROW_TAPPED="tl_row_tapped";
// 主要車站（選站清單中以白字顯示）
const MAJOR_STATIONS = new Set(["基隆","七堵","南港","松山","臺北","板橋","樹林","桃園","中壢","新竹","竹南","苗栗","豐原","臺中","彰化","員林","二水","斗六","嘉義","新營","臺南","岡山","新左營","高雄","鳳山","屏東","潮州","枋寮","臺東","玉里","花蓮","宜蘭","羅東","瑞芳"]);

const MAX_SEARCH_PER_MIN=3;
let lastFetchedPair={start:"",end:""};
let is24Hour = localStorage.getItem(LS_IS_24H) !== 'false';
let isShowAll = false;
let lastDiagnostics = { route_source: "--", route_quota: "--", delay_source: "--", delay_quota: "--" };
let systemLogs=[]; let requestHistory=[];

let isNextDayLoaded = false;
let currentTrainData = null;
let lastUpdateTime = 0; 
let isResumeHintActive = false;

// 自動喚醒計時器
let autoResumeTimer = null; 


try { localStorage.removeItem('tl_session_v2'); } catch(e) {}
// 站名更正：侯硐 → 猴硐（舊的偏好設定和常用路線一起改）
try {
    ['pref_start_station','pref_end_station'].forEach(k => { if (localStorage.getItem(k) === '侯硐') localStorage.setItem(k, '猴硐'); });
    ['tl_favorites','tl_history'].forEach(k => { const v = localStorage.getItem(k); if (v && v.includes('侯硐')) localStorage.setItem(k, v.split('侯硐').join('猴硐')); });
} catch(e) {}

let deferredPrompt;
const isIos = /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
const isInStandaloneMode = ('standalone' in window.navigator) && (window.navigator.standalone) || window.matchMedia('(display-mode: standalone)').matches;
const isInApp = /Line|Instagram|FBAN|FBAV/i.test(navigator.userAgent);

if (!isInStandaloneMode) { btnInstall.style.display = 'flex'; }
window.addEventListener('beforeinstallprompt', (e) => { e.preventDefault(); deferredPrompt = e; });

// 打開彈出視窗並切到指定頁面
function openSheet(id) {
    const modal = document.getElementById('aboutModal');
    modal.style.display = 'flex';
    document.body.classList.add('noscroll');
    setTimeout(() => modal.classList.add('active'), 10);
    history.pushState({modal: true}, '', '');
    goToPage(id);
}

function handleInstall() {
    if (isInApp) { document.getElementById('inAppOverlay').style.display = 'flex'; return; }
    if (!isIos && deferredPrompt) {
        deferredPrompt.prompt();
        deferredPrompt.userChoice.then((c) => { if(c.outcome==='accepted') btnInstall.style.display='none'; deferredPrompt=null; });
        return;
    }
    openSheet('IOS');
}
async function shareApp() {
    const data = { url: window.location.href };
    if (navigator.share) try { await navigator.share(data); } catch(e){} else { try{await navigator.clipboard.writeText(window.location.href);alert('連結已複製');}catch(e){} }
}

// --- God Mode：開發者查看使用者回報 ---
// 登入成功後伺服器發一組 30 分鐘有效的 token，只存在記憶體；密碼不會留在前端或網址
let adminToken = null;
let logoClickCount = 0; let logoClickTimer = null;
function handleLogoClick() {
    logoClickCount++;
    if (logoClickCount === 1) { logoClickTimer = setTimeout(() => { logoClickCount = 0; }, 1000); }
    if (logoClickCount >= 5) { clearTimeout(logoClickTimer); logoClickCount = 0; activateGodMode(); }
}
function activateGodMode() {
    if (adminToken) { openSheet('Dev'); fetchReportList(); }
    else {
        document.getElementById('loginMsg').innerText = "";
        openSheet('Login');
        setTimeout(() => document.getElementById('loginPass').focus(), 350);
    }
}

async function adminApi(action, body) {
    const headers = { 'Content-Type': 'application/json' };
    if (adminToken) headers['Authorization'] = `Bearer ${adminToken}`;
    const res = await fetch(`/api/index?admin=${encodeURIComponent(action)}`, {
        method: 'POST', headers, body: JSON.stringify(body || {}), cache: 'no-store'
    });
    let json = {};
    try { json = await res.json(); } catch (e) {}
    if (res.status === 401 && action !== 'login') {
        // token 過期或無效：回到登入頁
        adminToken = null;
        document.getElementById('loginMsg').innerText = "登入已過期，請重新登入";
        goToPage('Login');
    }
    if (!res.ok || json.error) throw new Error(json.error || `HTTP ${res.status}`);
    return json;
}

async function doLogin() {
    const pEl = document.getElementById('loginPass');
    const msg = document.getElementById('loginMsg');
    const btn = document.getElementById('btnLogin');
    const p = pEl.value;
    if (!p) return;
    btn.disabled = true; msg.innerText = "";
    adminToken = null; // 驗證成功前一律視為未登入
    try {
        const json = await adminApi('login', { p });
        if (!json.token) throw new Error("Login Failed");
        adminToken = json.token;
        goToPage('Dev');
        fetchReportList();
    } catch (e) {
        adminToken = null;
        msg.innerText = e.message === 'Too Many Attempts' ? "嘗試次數過多，請 15 分鐘後再試"
                      : e.message === 'Auth Failed' ? "密碼錯誤" : "登入失敗：" + e.message;
        pEl.classList.add('shake-anim');
        setTimeout(() => pEl.classList.remove('shake-anim'), 300);
    } finally {
        pEl.value = "";
        btn.disabled = false;
    }
}

function adminLogout() {
    if (adminToken) adminApi('logout').catch(() => {});
    adminToken = null;
    document.getElementById('reportListContainer').innerText = "";
    document.getElementById('reportDetailContainer').innerText = "點上方的回報查看內容";
    closeModal();
}

async function clearReports() {
    if (!confirm("確定清空所有報告？")) return;
    try { await adminApi('clear_reports'); } catch (e) { alert("清空失敗：" + e.message); }
    fetchReportList();
}

async function fetchReportList() {
    const container = document.getElementById('reportListContainer');
    container.innerText = "載入中…";
    try {
        const json = await adminApi('list_reports');
        container.innerHTML = "";
        if (!json.reports || json.reports.length === 0) { container.innerHTML = '<div class="report-list-empty">目前沒有回報</div>'; return; }
        json.reports.forEach(key => {
            // key 格式：report:YYYYMMDD_HHMMSS_xxxx
            const parts = key.replace('report:', '').split('_');
            const item = document.createElement('button');
            item.className = 'report-list-item';
            const d = parts[0] || '', t = parts[1] || '';
            item.innerText = (d.length === 8 && t.length === 6)
                ? `${d.slice(0,4)}/${d.slice(4,6)}/${d.slice(6)}  ${t.slice(0,2)}:${t.slice(2,4)}:${t.slice(4)}`
                : `${d} ${t}`;
            item.onclick = () => {
                container.querySelectorAll('.report-list-item').forEach(i => i.classList.remove('active'));
                item.classList.add('active');
                loadReportDetail(key);
            };
            container.appendChild(item);
        });
    } catch (e) { container.innerText = "讀取失敗：" + e.message; }
}

function formatReport(data) {
    const logs = Array.isArray(data.logs) ? data.logs.join('\n') : "No logs";
    const d = data.diagnostics || {};
    return `時間　　${data.timestamp || '--'}
描述　　${data.user_desc || '（無）'}
裝置　　${data.user_agent || '--'}
畫面　　${data.screen || '--'}
請求數　一分鐘 ${data.rpm ?? '--'} / 總共 ${data.total_requests ?? '--'}
時刻表　${d.route_source || '--'}（剩 ${d.route_quota || '--'}）
誤點　　${d.delay_source || '--'}（剩 ${d.delay_quota || '--'}）

[系統紀錄]
${logs}`;
}

async function loadReportDetail(reportId) {
    const detailBox = document.getElementById('reportDetailContainer');
    detailBox.innerText = "載入中…";
    try {
        const json = await adminApi('get_report', { id: reportId });
        detailBox.innerText = json.report_content ? formatReport(json.report_content) : "Error: Not Found";
    } catch (e) { detailBox.innerText = "讀取失敗：" + e.message; }
}

async function runTdxCheck() {
    const box = document.getElementById('reportDetailContainer');
    box.innerText = "檢查中…";
    try {
        const json = await adminApi('tdx_check', { start: startStation.value || '臺北', end: endStation.value || '高雄' });
        box.innerText = JSON.stringify(json, null, 2);
    } catch (e) { box.innerText = "檢查失敗：" + e.message; }
}

async function runStationCheck() {
    const box = document.getElementById('reportDetailContainer');
    box.innerText = "檢查中…";
    try { box.innerText = JSON.stringify(await adminApi('station_check'), null, 2); }
    catch (e) { box.innerText = "檢查失敗：" + e.message; }
}

function copyDevContent() {
    const text = document.getElementById('reportDetailContainer').innerText || "";
    if (!text || text.includes("載入中") || text.includes("點上方的回報")) { showToast("沒有內容可複製"); return; }
    navigator.clipboard.writeText(text).then(() => showToast("已複製")).catch(err => showToast("複製失敗"));
}

// --- 智慧休眠系統 (Smart Sleep System) ---
let blinkInterval = null;
let dataInterval = null;

function startTicker() {
    // 啟動前先確保舊的已清除，避免重複
    stopTicker();

    // 1. LED 閃爍計時器 (0.5s)
    blinkInterval = setInterval(() => {
        if (document.body.classList.contains('tick-a')) {
            document.body.classList.remove('tick-a'); document.body.classList.add('tick-b');
        } else {
            document.body.classList.remove('tick-b'); document.body.classList.add('tick-a');
        }
    }, 500);

    // 2. 資料倒數計時器 (15s)
    dataInterval = setInterval(() => {
        if (currentTrainData) renderCards(currentTrainData);
    }, 15000);
    
    console.log("App Woke Up: Timers Started");
}

function stopTicker() {
    if (blinkInterval) { clearInterval(blinkInterval); blinkInterval = null; }
    if (dataInterval) { clearInterval(dataInterval); dataInterval = null; }
    console.log("App Sleeping: Timers Stopped");
}

// 監聽頁面可見度變化 (關鍵！)
document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
        stopTicker(); // 頁面隱藏/螢幕關閉 -> 停止運作
    } else {
        startTicker(); // 頁面開啟 -> 恢復運作
        // 回來時順便立刻更新一次畫面，修正時間差
        if(currentTrainData) renderCards(currentTrainData); 
    }
});

// 斷線偵測
window.addEventListener('offline', () => {
    statusMsg.innerText = currentTrainData ? "離線中，顯示的是最後一次的資料" : "網路已中斷";
    statusMsg.className = "status-left warning";
});
window.addEventListener('online', () => {
    statusMsg.innerText = "網路已恢復"; statusMsg.className = "status-left";
    // 剛才是顯示舊資料的話，自動更新一次
    if (showingSaved && startStation.value && endStation.value) setTimeout(() => doRefresh(true), 800);
    else setTimeout(() => { if (statusMsg.innerText === "網路已恢復") statusMsg.innerText = ""; }, 2000);
});

// 讓沒有網路時也能打開網頁
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => { navigator.serviceWorker.register('/sw.js').catch(() => {}); });
}

// [修改] 喚醒提示邏輯 (改為 setTimeout 觸發)
function showResumeHint() {
    isResumeHintActive = true;
    resumePill.style.display = 'flex';
}

function closeResumePill(e) {
    if(e) e.stopPropagation();
    isResumeHintActive = false;
    resumePill.style.display = 'none';
}

function getSearchCount(){return parseInt(localStorage.getItem(LS_SEARCH_COUNT)||"0");}
function setSearchCount(v){localStorage.setItem(LS_SEARCH_COUNT,v);}
function getSearchResetTime(){return parseInt(localStorage.getItem(LS_SEARCH_RESET)||"0");}
function setSearchResetTime(v){localStorage.setItem(LS_SEARCH_RESET,v);}
function getSearchLockedUntil(){return parseInt(localStorage.getItem(LS_SEARCH_LOCK)||"0");}
function setSearchLockedUntil(v){localStorage.setItem(LS_SEARCH_LOCK,v);}
function getRefreshLockedUntil(){return parseInt(localStorage.getItem(LS_REFRESH_LOCK)||"0");}
function setRefreshLockedUntil(v){localStorage.setItem(LS_REFRESH_LOCK,v);}
function getUiLockedUntil(){return parseInt(localStorage.getItem(LS_UI_LOCK)||"0");}
function setUiLockedUntil(v){localStorage.setItem(LS_UI_LOCK,v);}

function updateToggleBtns() {
    document.getElementById('btnTimeFormat').innerText = is24Hour ? '24 小時' : '12 小時';
    // 「顯示已發車」的文字在 renderCards 依班次數更新
}

function toggleTimeFormat() { is24Hour=!is24Hour; localStorage.setItem(LS_IS_24H, is24Hour); updateToggleBtns(); reRenderLocal(); scrollToFirstActive();}
function toggleShowAll() { isShowAll=!isShowAll; updateToggleBtns(); reRenderLocal(); scrollToFirstActive();}

function formatTime(t) {
    if(!t) return "";
    if(is24Hour) return t;
    const p = t.split(':'); if(p.length < 2) return t;
    let h = parseInt(p[0]); let suffix = "上午";
    if(h >= 12) { suffix = "下午"; if(h > 12) h -= 12; } else if(h === 0) { h = 12; }
    return `<span class="ampm">${suffix}</span> ${h}:${p[1]}`;
}

let lastScroll = 0; let currentTranslate = 0;

const sticky = document.getElementById('stickyHeader');
const placeholder = document.getElementById('stickyPlaceholder');
const backToTop = document.getElementById('btnBackToTop');
const staticPart = document.querySelector('.header-static-part');
const headerEl = document.querySelector('.header');

window.addEventListener('scroll', () => {
    const current = window.scrollY;
    const headerOffset = headerEl ? headerEl.offsetTop : 0;
    const threshold = staticPart ? (staticPart.offsetHeight + headerOffset) : 150;
    const stickyHeight = sticky.offsetHeight || 150;

    if(current > 300) backToTop.classList.add('visible'); else backToTop.classList.remove('visible');

    if (current <= threshold - 1) {
        sticky.classList.remove('is-fixed');
        sticky.style.transform = 'translateY(0)';
        placeholder.style.display = 'none';
        currentTranslate = 0;
    } else if (current > threshold) {
        if (!sticky.classList.contains('is-fixed')) {
              placeholder.style.height = stickyHeight + 'px'; 
              placeholder.style.display = 'block';
              sticky.classList.add('is-fixed');
        }
        const diff = current - lastScroll;
        currentTranslate -= diff;
        if (currentTranslate > 0) currentTranslate = 0;
        if (currentTranslate < -stickyHeight) currentTranslate = -stickyHeight;
        if (current < threshold + stickyHeight + 10) currentTranslate = 0;
        sticky.style.transform = `translateX(-50%) translateY(${currentTranslate}px)`;
    }
    lastScroll = current <= 0 ? 0 : current;
});

function scrollToFirstActive() {
    setTimeout(() => {
        const el = document.getElementById("firstActive");
        if (el) {
            el.scrollIntoView({ behavior: "smooth", block: "center" });
        }
    }, 300); 
}

// 只有「從來沒查詢過」才顯示第一次打開的畫面（快取過期不算）
const LS_HAS_QUERIED = "tl_has_queried";
function hasQueriedBefore() {
    try {
        return localStorage.getItem(LS_HAS_QUERIED) === '1'
            || JSON.parse(localStorage.getItem('tl_history') || '[]').length > 0
            || JSON.parse(localStorage.getItem('tl_favorites') || '[]').length > 0;
    } catch (e) { return false; }
}

function init() {
    logSystem("App Started"); 
    if (!hasQueriedBefore()) document.body.classList.add('fresh');
    startTicker(); 
    updateToggleBtns();
    
    document.getElementById('rowTools').style.display = 'none';

    // Cache 安全性檢查
    try {
        const regions=Object.keys(STATION_DATA); const rOpts=regions.map(r=>`<option value="${r}">${r}</option>`).join('');
        const savedSR = localStorage.getItem(PREF_START_R_KEY);
        startRegion.innerHTML=`<option value=""></option>`+rOpts; endRegion.innerHTML=`<option value=""></option>`+rOpts;
        if (savedSR) {
            setMenu('start',savedSR,localStorage.getItem(PREF_START_S_KEY)||"屏東"); 
            setMenu('end',localStorage.getItem(PREF_END_R_KEY)||"屏東縣",localStorage.getItem(PREF_END_S_KEY)||"潮州");
            checkLocksOnLoad(); loadDataOrFetch();
        } else {
            startStation.innerHTML=endStation.innerHTML=`<option value=""></option>`;
            list.innerHTML='';
            checkLocksOnLoad();
        }
    } catch(e) {
        console.error("Cache corrupted, clearing...", e);
        localStorage.clear();
        window.location.reload();
    }
    
    updateStationDisplay();
    renderQuickRoutes();
    updateStarState();
    updateActionButton();
}

function checkLocksOnLoad() {
    updateActionButton();
}

function setMenu(type,rV,sV) {
    const rSel=type==='start'?startRegion:endRegion; const sSel=type==='start'?startStation:endStation;
    if(!STATION_DATA[rV]) { rSel.value = ""; updateStationDisplay(); return; }
    rSel.value=rV; sSel.innerHTML=STATION_DATA[rV].map(s=>`<option value="${s}">${s}</option>`).join('');
    if(STATION_DATA[rV].includes(sV)) sSel.value=sV; else sSel.selectedIndex=0;
    updateStationDisplay();
}

function updateStationDisplay() {
    [['start', startStation, startRegion, '選擇起站'], ['end', endStation, endRegion, '選擇迄站']].forEach(([type, sSel, rSel, ph]) => {
        const el = document.getElementById(type === 'start' ? 'startPick' : 'endPick');
        const has = !!sSel.value;
        el.classList.toggle('empty', !has);
        el.querySelector('b').innerText = has ? sSel.value : '';
        el.querySelector('span').innerText = has ? rSel.value : '';
    });
    document.body.classList.toggle('nostation', !(startStation.value && endStation.value));
}

// ---------- 選站畫面 ----------
let pickerType = 'start'; let pickerRegion = '';
function openStationPicker(type) {
    pickerType = type;
    const sSel = type === 'start' ? startStation : endStation;
    const rSel = type === 'start' ? startRegion : endRegion;
    const other = type === 'start' ? endRegion : startRegion;
    pickerRegion = rSel.value || other.value || '臺北市';
    document.getElementById('pickerTitle').innerText = type === 'start' ? '起站' : '迄站';
    document.getElementById('pickerSearch').value = '';
    renderPickerRegions();
    renderPickerStations();
    openSheet('Station');
    setTimeout(() => {
        const on = document.querySelector('#pickerStations .on');
        if (on) on.scrollIntoView({ block: 'center' });
        const reg = document.querySelector('#pickerRegions .on');
        if (reg) reg.scrollIntoView({ block: 'nearest' });
    }, 60);
}
function renderPickerRegions() {
    const box = document.getElementById('pickerRegions');
    box.innerHTML = '';
    Object.keys(STATION_DATA).forEach(r => {
        const b = document.createElement('button');
        b.innerText = r;
        if (r === pickerRegion) b.className = 'on';
        b.onclick = () => {
            pickerRegion = r;
            document.getElementById('pickerSearch').value = '';
            renderPickerRegions(); renderPickerStations();
            document.getElementById('pickerStations').scrollTop = 0;
        };
        box.appendChild(b);
    });
}
function renderPickerStations() {
    const box = document.getElementById('pickerStations');
    const q = document.getElementById('pickerSearch').value.trim().replace(/台/g, '臺');
    const current = (pickerType === 'start' ? startStation : endStation).value;
    let items;
    if (q) {
        items = Object.keys(STATION_INDEX).filter(s => s.includes(q))
            .sort((a, b) => (a === q ? -1 : b === q ? 1 : 0))
            .map(s => [s, STATION_INDEX[s], true]);
    } else {
        items = (STATION_DATA[pickerRegion] || []).map(s => [s, pickerRegion, false]);
    }
    box.innerHTML = '';
    if (items.length === 0) { box.innerHTML = '<div class="picker-empty">找不到這個車站</div>'; return; }
    items.forEach(([s, r, showRegion]) => {
        const b = document.createElement('button');
        const cls = [];
        if (MAJOR_STATIONS.has(s)) cls.push('major');
        if (s === current) cls.push('on');
        b.className = cls.join(' ');
        const name = document.createElement('span'); name.innerText = s;
        b.appendChild(name);
        if (s === current) {
            b.insertAdjacentHTML('beforeend', '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8.5l3.2 3L13 4.5"/></svg>');
        } else if (showRegion) {
            const sm = document.createElement('small'); sm.innerText = r; b.appendChild(sm);
        }
        b.onclick = () => pickStation(s, r);
        box.appendChild(b);
    });
}
function pickStation(station, region) {
    logSystem(`Action: Pick ${pickerType} ${station}`);
    setMenu(pickerType, region, station);
    if (startStation.value && endStation.value) markAsChanged();
    else { updateStarState(); updateActionButton(); }
    closeModal();
}



function swapStations() {
    if(!startStation.value||!endStation.value) return; logSystem("Action: Swap");
    const sR=startRegion.value; const sS=startStation.value;
    setMenu('start',endRegion.value,endStation.value); setMenu('end',sR,sS);
    markAsChanged();
}

function markAsChanged() {
    if (isResumeHintActive) {
        closeResumePill();
    }

    if(!startStation.value||!endStation.value) return;
    localStorage.setItem(PREF_START_R_KEY,startRegion.value); localStorage.setItem(PREF_START_S_KEY,startStation.value);
    localStorage.setItem(PREF_END_R_KEY,endRegion.value); localStorage.setItem(PREF_END_S_KEY,endStation.value);
    
    isNextDayLoaded = false;
    
    attemptLoadCache(false);
    updateStarState();
    updateActionButton();
}
function getCacheKey(){return `${CACHE_PREFIX}${startStation.value}_${endStation.value}`;}

function reRenderLocal() {
    if (currentTrainData) {
        renderCards(currentTrainData);
        return;
    }
    const baseKey = getCacheKey();
    const fullKey = baseKey + "_full";
    const cFull = localStorage.getItem(fullKey);
    const c = localStorage.getItem(baseKey);

    if(cFull) {
        const d = JSON.parse(cFull);
        if(Date.now()-d.timestamp < 60000) { renderCards(d.payload); isNextDayLoaded=true; return; }
    }
    if(c) renderCards(JSON.parse(c).payload); 
}

function attemptLoadCache(isInit) {
    if(!startStation.value||!endStation.value) return;
    
    const baseKey = getCacheKey();
    const fullKey = baseKey + "_full";
    const cFull = localStorage.getItem(fullKey);
    const c = localStorage.getItem(baseKey);
    let hitData = null;

    if (cFull) {
        const d = JSON.parse(cFull);
        if (Date.now() - d.timestamp < 60000) { hitData = d; isNextDayLoaded = true; }
    }
    if (!hitData && c) {
        const d = JSON.parse(c);
        if (Date.now() - d.timestamp < 60000) { hitData = d; }
    }

    if(hitData) {
        if(hitData.payload.diagnostics) parseDiagnostics(hitData.payload.diagnostics, false); 
        renderCards(hitData.payload); 
        setUpdateText(`${String(hitData.payload.update_time).slice(0,5)} 更新`);
        statusMsg.innerText=""; statusMsg.className="status-left"; 
        list.style.opacity="1"; 
        lastFetchedPair={start:startStation.value,end:endStation.value}; 
        scrollToFirstActive(); 
    } else {
        if(isInit || !currentTrainData) {
            if (!currentTrainData) list.innerHTML='';
            if (isInit && navigator.onLine === false) showSavedRoute('離線中');
        } else {
            list.style.opacity="0.4"; statusMsg.innerText="已換站，按查詢看新的班次"; statusMsg.className="status-left warning";
            document.getElementById('rowTools').style.display = 'flex';
        }
    }
    updateActionButton();
}
function loadDataOrFetch(){attemptLoadCache(true);}

// 沒網路或連不上時，拿這條路線最後一次存下來的結果（不管多舊）
function getSavedRoute() {
    const base = getCacheKey();
    let best = null;
    [base + "_full", base].forEach(k => {
        try {
            const d = JSON.parse(localStorage.getItem(k) || 'null');
            if (d && d.payload && (!best || d.timestamp > best.timestamp)) best = d;
        } catch (e) {}
    });
    return best;
}
function savedTimeLabel(d) {
    const t = new Date(d.timestamp);
    const sameDay = t.toDateString() === new Date().toDateString();
    const hm = `${String(t.getHours()).padStart(2,'0')}:${String(t.getMinutes()).padStart(2,'0')}`;
    return sameDay ? hm : `${t.getMonth()+1}/${t.getDate()} ${hm}`;
}
let showingSaved = false;
function showSavedRoute(reason) {
    const d = getSavedRoute();
    if (!d) return false;
    renderCards(d.payload);
    showingSaved = true;
    lastFetchedPair = { start: startStation.value, end: endStation.value };
    statusMsg.innerText = `${reason}，顯示 ${savedTimeLabel(d)} 的資料`;
    statusMsg.className = "status-left warning";
    return true;
}
// ---------- 查詢／更新共用的按鈕 ----------
function routeIsCurrent() {
    return !!startStation.value && startStation.value === lastFetchedPair.start && endStation.value === lastFetchedPair.end;
}
const ICON_REFRESH = '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M13.5 8A5.5 5.5 0 1 1 11.9 4.1M13.5 2.5v3h-3"/></svg>';
function updateActionButton() {
    const now = Date.now();
    const sL = getSearchLockedUntil(); const uL = getUiLockedUntil();
    // UI 冷卻結束時，同步解除更新鎖（沿用原本的行為）
    if (uL && uL <= now) { setUiLockedUntil(0); setRefreshLockedUntil(0); }
    if (sL && sL <= now) { setSearchLockedUntil(0); }

    let html = '查詢', disabled = false;
    const secs = t => Math.ceil((t - now) / 1000);
    if (isFetching) {
        html = '載入中'; disabled = true;
    } else if (!startStation.value || !endStation.value) {
        disabled = true;
    } else if (routeIsCurrent()) {
        html = ICON_REFRESH + '更新';
        if (uL > now) { html += ` <span class="cd">${secs(uL)}</span>`; disabled = true; }
    } else if (sL > now) {
        html = `查詢次數已滿 <span class="cd">${secs(sL)}</span>`; disabled = true;
    }
    btnAction.innerHTML = html;
    btnAction.disabled = disabled;

    const needTick = (uL > now) || (sL > now);
    if (needTick && !actionTicker) actionTicker = setInterval(updateActionButton, 1000);
    if (!needTick && actionTicker) { clearInterval(actionTicker); actionTicker = null; }
}
function handleAction() {
    if (btnAction.disabled) return;
    if (routeIsCurrent()) doRefresh(); else doSearch();
}

function doSearch() {
    const sS=startStation.value; const eS=endStation.value;
    if(!sS||!eS) { showToast("請先選擇起訖站"); return; }
    markAsChanged();
    if(sS===lastFetchedPair.start&&eS===lastFetchedPair.end) { doRefresh(); return; }
    const now=Date.now(); let cnt=getSearchCount(); let rst=getSearchResetTime();
    if(now-rst>60000) { cnt=0; setSearchCount(0); rst=now; setSearchResetTime(now); }
    if(cnt===0) { rst=now; setSearchResetTime(now); }
    if(cnt>=MAX_SEARCH_PER_MIN) {
        const w=Math.ceil((60000-(now-rst))/1000); const safeW=w>0?w:60;
        setSearchLockedUntil(now+safeW*1000); lockSearchButton(safeW); logSystem("Limit: Search Limit"); return;
    }
    addToHistory();
    cnt++; setSearchCount(cnt); 
    const spaces = "            "; 
    logSystem(`Action: Search(${cnt}/${MAX_SEARCH_PER_MIN})\n${spaces}${sS} -> ${eS}`); 
    fetchData("search");
}
function doRefresh(skip=false) {
    const now = Date.now();
    
    if (isResumeHintActive) {
        closeResumePill();
    }

    if(!skip) {
        const uL = getUiLockedUntil();
        if(uL > now) return; 
    }
    const rL = getRefreshLockedUntil();
    
    if(rL > now && !skip) {
        logSystem("Action: Soft Refresh (Cache)");
        
        reRenderLocal(); 
        statusMsg.innerText = "已是最新資料";
        statusMsg.className = "status-left";
        setTimeout(() => statusMsg.innerText="", 2000);
        setUiLockedUntil(now + 30000); 
        lockRefreshButton(30);
        return; 
    }
    const spaces = "            "; 
    logSystem(`Action: Refresh\n${spaces}${startStation.value} -> ${endStation.value}`); 
    fetchData("refresh");
}

function handleLoadNextDay() {
    logSystem("Action: Load Next Day");
    const btn = document.getElementById('btnLoadNext');
    if(btn) { btn.disabled=true; btn.innerText = "載入中…"; }
    fetchData("load_next_day");
}

async function uploadReportInternal(desc, isAuto) {
    const statusHint = document.getElementById('autoUploadHint');
    const now = Date.now();
    const rpm = requestHistory.filter(t => now - t < 60000).length;
    
    const reportData = {
        timestamp: new Date().toLocaleString(),
        user_agent: navigator.userAgent,
        screen: `${window.innerWidth}x${window.innerHeight}`,
        rpm: rpm,
        total_requests: requestHistory.length,
        diagnostics: lastDiagnostics,
        logs: systemLogs,
        user_desc: desc || "(Auto Upload on Open)"
    };

    try {
        const res = await fetch('/api/index', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(reportData)
        });
        const json = await res.json();
        
        if (json.status === 'ok') {
            if (isAuto) {
                statusHint.style.opacity = '1';
                setTimeout(() => { statusHint.style.opacity = '0'; }, 3000);
            } else {
                showToast("已送出，謝謝回報");
                document.getElementById('userDesc').value = ""; 
            }
        } else {
            if (!isAuto) showToast(json.error === 'Too Many Reports' ? '回報太頻繁，請稍後再試' : '送出失敗，請稍後再試');
        }
    } catch (e) {
        if (!isAuto) showToast('送出失敗，請檢查網路');
    }
}

function uploadReport() {
    uploadReportInternal("", true);
}

function manualUploadReport() {
    const desc = document.getElementById('userDesc').value;
    uploadReportInternal(desc, false);
}

function parseDiagnostics(diag, isCdn) {
    const parseDiag = (str, isC) => {
        let source = "API"; let quota = "--";
        if (isC) source = "Vercel";
        else if (str.includes("Hit") || str.includes("Cache") || str.includes("Redis")) source = "Redis";
        else if (str.includes("API")) source = "API";
        const match = str.match(/\(剩:\s*(\d+)\)/); if (match) quota = match[1];
        return { source, quota };
    };
    const rInfo = parseDiag(diag.route_status, isCdn);
    const dInfo = diag.delay_status ? parseDiag(diag.delay_status, isCdn) : { source: "--", quota: "--" };
    lastDiagnostics = { route_source: rInfo.source, route_quota: rInfo.quota, delay_source: dInfo.source, delay_quota: dInfo.quota };
    return { rInfo, dInfo };
}

function getSkeletonHTML() {
    const lastCount = parseInt(localStorage.getItem(LS_SKELETON_COUNT) || "3");
    const count = Math.min(Math.max(lastCount, 3), 8);
    let html = '';
    for(let i=0; i<count; i++) html += `<div class="skeleton-row"><div class="sk-line sk-main"></div><div class="sk-line sk-sub"></div></div>`;
    return html;
}

async function fetchData(mode) {
    isFetching = true; updateActionButton();
    document.body.classList.remove('fresh');
    try { localStorage.setItem(LS_HAS_QUERIED, '1'); } catch (e) {}
    
    if(mode !== "load_next_day") {
        list.innerHTML = getSkeletonHTML(); 
        list.style.opacity="1"; 
    }
    statusMsg.innerText="載入中..."; 
    if(retryTimer){clearTimeout(retryTimer);retryTimer=null;}

    const s=startStation.value; const e=endStation.value; 
    
    const needNextDay = (mode === "load_next_day" || isNextDayLoaded) ? 1 : 0;
    const cacheKeySuffix = needNextDay ? "_full" : ""; 
    const cacheKey = getCacheKey() + cacheKeySuffix; 
    
    const now = Date.now();
    const rpmVal = requestHistory.filter(t => now - t < 60000).length;

    recordRequest();
    try {
        const url = `/api/index?start=${encodeURIComponent(s)}&end=${encodeURIComponent(e)}&next_day=${needNextDay}&mode=${mode}`;

        const res=await fetch(url);
        const age = res.headers.get('Age');
        const isVercelCache = age && parseInt(age) > 0;
        const json=await res.json();
        if(json.error) throw new Error(json.error);

        lastFetchedPair={start:s,end:e};
        showingSaved = false;
        
        if (needNextDay) isNextDayLoaded = true;

        const { rInfo, dInfo } = parseDiagnostics(json.diagnostics, isVercelCache);
        
        localStorage.setItem(cacheKey,JSON.stringify({timestamp:Date.now(),payload:json}));
        renderCards(json);

        logSystem(`${rInfo.source}${rInfo.quota !== "--" ? `(剩:${rInfo.quota})` : ""} / ${dInfo.source}${dInfo.quota !== "--" ? `(剩:${dInfo.quota})` : ""}`);

        if(json.delay_failed) {
            scheduleRetry("誤點資料失敗", "status-left warning");
            setUpdateText(`${String(json.update_time).slice(0,5)} 更新 · 誤點資料暫缺`);
        } else {
            setUpdateText(`${String(json.update_time).slice(0,5)} 更新`);
            statusMsg.innerText = ""; statusMsg.className = "status-left";
        }
        
        if(mode==="search"){ 
            setRefreshLockedUntil(now+90000); 
            setUiLockedUntil(now+30000);
            lockRefreshButton(30);            
        }
        if(mode==="refresh"){ 
            setRefreshLockedUntil(now+90000); 
            setUiLockedUntil(now+30000);
            lockRefreshButton(30);            
        }
        
        if (mode === "load_next_day") {
            const divider = document.getElementById('tomorrow-divider');
            if (divider) {
                divider.scrollIntoView({ behavior: 'smooth', block: 'start' });
                setTimeout(() => window.scrollBy({ top: -60, behavior: 'smooth' }), 500);
            }
        } else {
            scrollToFirstActive(); 
        }

        lastUpdateTime = Date.now(); 

        // [新增] 3分鐘自動提示邏輯 (無論是否離開)
        if(autoResumeTimer) clearTimeout(autoResumeTimer);
        autoResumeTimer = setTimeout(() => {
             showResumeHint();
        }, 180000); // 3分鐘

    } catch(err) {
        console.error(err); logSystem("API Error: " + err.message);
        const offline = navigator.onLine === false || err instanceof TypeError;
        if (err.message === 'Too Many Requests') {
            // 後端次數限制：不自動重試，等使用者自己再按
            statusMsg.innerText = "查詢太頻繁，請稍等一分鐘"; statusMsg.className = "status-left alert";
            if (!showSavedRoute('查詢太頻繁')) list.innerHTML = `<div class="message">查詢太頻繁<small>請稍等一分鐘再試</small></div>`;
        } else if (offline) {
            // 沒有網路：顯示上次的結果，網路恢復時自動更新一次
            if (!showSavedRoute('離線中')) list.innerHTML = `<div class="message">目前沒有網路<small>網路恢復後會自動更新</small></div>`;
        } else {
            const hadSaved = showSavedRoute('連線失敗');
            scheduleRetry(hadSaved ? statusMsg.innerText : "連線錯誤", hadSaved ? "status-left warning" : "status-left alert");
            if (!hadSaved) list.innerHTML=`<div class="message">連線失敗<small>30 秒後會自動重試</small></div>`;
        }
    } finally {
        isFetching = false;
        updateActionButton();
    }
}

function setUpdateText(t){updateTimeDiv.innerText=t;localStorage.setItem("last_update_text",t);}

function scheduleRetry(msg="誤點資訊無法取得", cls="status-left warning") {
    let c=30; 
    if(retryTimer) clearInterval(retryTimer);
    statusMsg.className = cls; statusMsg.innerText = `${msg} (30s)`;
    retryTimer=setInterval(()=>{
        c--; statusMsg.innerText=`${msg} (${c}s)`;
        if(c<=0){ clearInterval(retryTimer); retryTimer=null; doRefresh(true); }
    },1000);
}

function lockSearchButton(s) {
    statusMsg.innerText = "查詢太頻繁，請稍等"; statusMsg.className = "status-left alert";
    updateActionButton();
}

function lockRefreshButton(s) {
    updateActionButton();
}

function getStrictDateStr(ts) {
    const d = new Date(ts * 1000);
    return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
}

function renderCards(data) {
    currentTrainData = data; 
    document.body.classList.remove('fresh');
    if(data.trains) localStorage.setItem(LS_SKELETON_COUNT, data.trains.length);

    const elTools = document.getElementById('rowTools');
    const btnAll = document.getElementById('btnShowAll');
    const trains = data.trains || [];
    const originalCount = (data.stats && data.stats.original_count) ? data.stats.original_count : 0;
    elTools.style.display = (trains.length > 0 || originalCount > 0) ? 'flex' : 'none';
    list.style.opacity = "1";
    renderAlerts(data.alerts || []);
    const susp = (data.stats && data.stats.suspended) || 0;
    document.getElementById('suspNote').innerText = susp > 0 ? `　·　${susp} 班停駛未顯示` : '';

    const nowSec = Math.floor(Date.now() / 1000);
    const now = new Date();
    const todayStr = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`;
    const isLateNight = now.getHours() >= 22;
    const delayOk = !data.delay_failed;

    // 已發車超過 10 分鐘的班次預設收起來
    const hiddenCount = trains.filter(t => Math.floor((t.sort_key - nowSec) / 60) < -10).length;
    const CHEVRON = '<svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M2 3.5l3 3 3-3"/></svg>';
    if (hiddenCount > 0) {
        btnAll.style.display = 'inline-flex';
        btnAll.innerHTML = (isShowAll ? '收起已發車' : `顯示 ${hiddenCount} 班已發車`) + CHEVRON;
        btnAll.classList.toggle('active', isShowAll);
    } else {
        btnAll.style.display = 'none';
    }

    const loadNextBtn = (isLateNight && !isNextDayLoaded)
        ? `<button id="btnLoadNext" class="load-next" onclick="handleLoadNextDay()">載入明天的班次</button>` : '';

    if (trains.length === 0) {
        list.innerHTML = originalCount > 0
            ? `<div class="message">今天的班次都已經開走了<small>今日共 ${originalCount} 班</small></div>${loadNextBtn}`
            : `<div class="message">這兩站之間沒有直達車</div>`;
        return;
    }

    let html = '';
    let shown = 0, anyArriving = false, foundFirstActive = false, shownDivider = false;
    trains.forEach(t => {
        const diffSec = t.sort_key - nowSec;
        const diffMin = Math.floor(diffSec / 60);
        const isDeparted = diffSec < 0;
        const isArriving = !isDeparted && diffMin <= 10;
        if (!isShowAll && diffMin < -10) return;

        const isTomorrow = getStrictDateStr(t.sort_key) > todayStr;
        if (isTomorrow && !shownDivider) {
            html += `<div id="tomorrow-divider" class="day-divider">明天</div>`;
            shownDivider = true;
        }

        const isLate = !isTomorrow && delayOk && t.delay > 0;
        if (isArriving) anyArriving = true;
        let activeId = '';
        if (!isDeparted && !foundFirstActive) { activeId = 'id="firstActive"'; foundFirstActive = true; }

        const cls = ['row'];
        if (isDeparted) cls.push('departed');
        if (isLate) cls.push('late');
        if (isArriving) cls.push('arriving');

        const led = isArriving ? '<div class="led"><div class="led-dot top"></div><div class="led-dot bottom"></div></div>' : '';
        const typeColor = t.color && t.color.toLowerCase() !== '#ffffff' ? t.color : '#ddd';
        const side = isDeparted ? '已發車' : (isLate ? `晚 ${t.delay} 分<span class="o">原定 ${formatTime(t.sch_dep)}</span>` : '');
        const url = `https://railway.chienwen.net/taiwan/train/TRA-${encodeURIComponent(t.no)}/live`;

        html += `<a class="${cls.join(' ')}" style="--tc:${typeColor}" href="${url}" target="_blank" rel="noopener" ${activeId} onclick="markRowTapped()">
                    ${led}
                    <div class="r-time"><span class="r-dep">${formatTime(t.act_dep)}</span><span class="r-arr">${formatTime(t.act_arr)}</span></div>
                    <div class="r-meta"><span class="r-type" style="color:${typeColor}">${t.type}</span><span>${t.no}</span></div>
                    <div class="r-side">${side}</div>
                </a>`;
        shown++;
    });

    if (shown === 0) html = `<div class="message">目前沒有要發車的班次</div>`;

    const tips = [];
    if (anyArriving) tips.push('<span class="led inline"><span class="led-dot top"></span><span class="led-dot bottom"></span></span>10 分鐘內發車');
    if (tips.length) html += `<div class="list-foot">${tips.join('<br>')}</div>`;

    list.innerHTML = html + loadNextBtn;
    maybeStartListCoach();
}

function renderAlerts(alerts) {
    const bar = document.getElementById('alertBar');
    if (!alerts.length) { bar.hidden = true; return; }
    const title = alerts[0].title + (alerts.length > 1 ? `（還有 ${alerts.length - 1} 則）` : '');
    document.getElementById('alertTitle').textContent = title;
    const body = document.getElementById('alertBody');
    body.innerHTML = '';
    alerts.forEach(a => {
        const item = document.createElement('div'); item.className = 'alert-item';
        if (alerts.length > 1) { const b = document.createElement('b'); b.textContent = a.title; item.appendChild(b); }
        const p = document.createElement('div'); p.textContent = a.desc || a.title; item.appendChild(p);
        if (a.url) { const l = document.createElement('a'); l.href = a.url; l.target = '_blank'; l.rel = 'noopener'; l.textContent = '台鐵公告'; item.appendChild(l); }
        body.appendChild(item);
    });
    const key = alerts.map(a => a.title).join('|');
    if (bar.dataset.key !== key) { bar.classList.remove('open'); bar.dataset.key = key; }
    bar.hidden = false;
}

function markRowTapped() {
    try { localStorage.setItem(LS_ROW_TAPPED, '1'); } catch (e) {}
}

// [新增] 關閉教學並判斷 Checkbox




function showToast(msg) {
    const t = document.getElementById('toastMsg');
    t.innerText = msg;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 2000);
}

function logSystem(d){
    const time = new Date().toLocaleTimeString('en-GB', {hour12:false});
    systemLogs.push(`[${time}] ${d}`);
    if(systemLogs.length>30)systemLogs.shift();
}
function recordRequest(){requestHistory.push(Date.now());}

// [修改] Modal System
function openMenu(){ openSheet('Menu'); }

function closeModal(){
    // Clear manual transforms first
    document.querySelectorAll('.modal-page').forEach(el => {
        el.style.transform = '';
        el.style.transition = '';
    });
    history.back();
}

window.addEventListener('popstate', () => {
    const modal = document.getElementById('aboutModal');
    if (modal.style.display === 'flex') {
        modal.classList.remove('active');
        
        // Close active pages inside
        document.querySelectorAll('.modal-page.active').forEach(p => p.classList.remove('active'));

        setTimeout(() => {
            modal.style.display = 'none';
            document.body.classList.remove('noscroll');
        }, 300);
    }
});

function goToPage(id){
    document.querySelectorAll('.modal-page').forEach(p=>p.classList.remove('active'));
    document.getElementById('page'+id).classList.add('active');
    if(id==='Report'){ uploadReport(); }
}

// [Advanced] 1:1 Interactive Swipe Gestures
let dragModal = null;
let dragStartY = 0;
let dragStartX = 0;
let isDragging = false;

// Helper to find parent modal
function getParentModal(el) {
    return el.closest('.modal-page');
}

document.addEventListener('touchstart', (e) => {
    const modal = getParentModal(e.target);
    if (!modal) return;

    // Logic for Bottom Sheet
    if (modal.classList.contains('sheet-bottom')) {
        // Allow drag if touching handle OR (touching content AND at top)
        const isHandle = e.target.closest('.sheet-handle') || e.target.closest('.modal-header-row');
        // Note: overflow-y is on modal-page itself
        const isAtTop = modal.scrollTop <= 0; 
        
        // [New] Prevent drag if touching inner scrollable area
        const isInnerScroll = e.target.closest('.terminal-box') || 
                              e.target.closest('.dev-terminal') || 
                              e.target.closest('.picker-col') || 
                              e.target.closest('.report-list') || 
                              e.target.tagName === 'TEXTAREA';

        if (isInnerScroll) return; 

        if (isHandle || isAtTop) {
            dragModal = modal;
            dragStartY = e.touches[0].clientY;
            isDragging = true;
            // Disable transition for instant 1:1 follow
            dragModal.style.transition = 'none';
        }
    }

    // Logic for Right Sheet
    if (modal.classList.contains('sheet-right')) {
        dragModal = modal;
        dragStartX = e.touches[0].clientX;
        isDragging = true;
        dragModal.style.transition = 'none';
    }
}, {passive: false});

document.addEventListener('touchmove', (e) => {
    if (!isDragging || !dragModal) return;

    if (dragModal.classList.contains('sheet-bottom')) {
        const currentY = e.touches[0].clientY;
        const deltaY = currentY - dragStartY;

        if (deltaY > 0) { // Only allow dragging down
            // Prevent background scroll only if we are actually dragging the window
            if (e.cancelable) e.preventDefault(); 
            dragModal.style.transform = `translateY(${deltaY}px)`;
        }
    }

    if (dragModal.classList.contains('sheet-right')) {
        const currentX = e.touches[0].clientX;
        const deltaX = currentX - dragStartX;

        if (deltaX > 0) { // Only allow dragging right
            if (e.cancelable) e.preventDefault();
            dragModal.style.transform = `translateX(${deltaX}px)`;
        }
    }
}, {passive: false});

document.addEventListener('touchend', (e) => {
    if (!isDragging || !dragModal) return;

    // Restore animation for snap back or close
    dragModal.style.transition = 'transform 0.3s cubic-bezier(0.16, 1, 0.3, 1)';

    let shouldClose = false;

    if (dragModal.classList.contains('sheet-bottom')) {
        const deltaY = e.changedTouches[0].clientY - dragStartY;
        if (deltaY > 100) shouldClose = true; // Threshold 100px
    }

    if (dragModal.classList.contains('sheet-right')) {
        const deltaX = e.changedTouches[0].clientX - dragStartX;
        if (deltaX > 100) shouldClose = true;
    }

    if (shouldClose) {
        closeModal();
    } else {
        // Snap back
        dragModal.style.transform = ''; 
    }

    isDragging = false;
    dragModal = null;
});

const LS_FAV = "tl_favorites"; const LS_HIST = "tl_history";
const MAX_HIST = 3; const MAX_FAV = 6;
const btnStar = document.getElementById('btnStar');
const quickArea = document.getElementById('quickRouteArea');

function getCurrentPair() { return { start: startStation.value, end: endStation.value }; }
function isFavorite(s, e) {
    const favs = JSON.parse(localStorage.getItem(LS_FAV) || "[]");
    return favs.some(f => f.start === s && f.end === e);
}
function toggleFavorite() {
    const cur = getCurrentPair(); if (!cur.start || !cur.end) return;
    let favs = JSON.parse(localStorage.getItem(LS_FAV) || "[]");
    const idx = favs.findIndex(f => f.start === cur.start && f.end === cur.end);
    if (idx >= 0) { favs.splice(idx, 1); logSystem("Fav: Removed"); } 
    else { if (favs.length >= MAX_FAV) { alert(`常用路線最多 ${MAX_FAV} 組`); return; } favs.unshift(cur); logSystem("Fav: Added"); }
    localStorage.setItem(LS_FAV, JSON.stringify(favs));
    updateStarState(); renderQuickRoutes();
}
function addToHistory() {
    const cur = getCurrentPair(); if (!cur.start || !cur.end) return;
    let hist = JSON.parse(localStorage.getItem(LS_HIST) || "[]");
    hist = hist.filter(h => !(h.start === cur.start && h.end === cur.end));
    hist.unshift(cur); if (hist.length > MAX_HIST) hist.pop();
    localStorage.setItem(LS_HIST, JSON.stringify(hist));
    renderQuickRoutes();
}
function updateStarState() {
    const cur = getCurrentPair();
    const on = isFavorite(cur.start, cur.end);
    btnStar.classList.toggle('fav-active', on);
    btnStar.setAttribute('aria-label', on ? '取消收藏' : '收藏路線');
    btnStar.innerHTML = `<svg width="18" height="18" viewBox="0 0 20 20" fill="${on ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"><path d="M10 2.5l2.3 4.8 5.2.7-3.8 3.6.9 5.2L10 14.3l-4.6 2.5.9-5.2-3.8-3.6 5.2-.7z"/></svg>`;
    renderQuickRoutes();
}

function loadRoute(s, e) {
    const sR = STATION_INDEX[s]; const eR = STATION_INDEX[e];
    if (sR && eR) {
        setMenu('start', sR, s); setMenu('end', eR, e);
        markAsChanged(); doSearch(); 
    }
}
function renderQuickRoutes() {
    const favs = JSON.parse(localStorage.getItem(LS_FAV) || "[]");
    const hist = JSON.parse(localStorage.getItem(LS_HIST) || "[]");
    const chip = (r, cls) => `<button class="chip ${cls}" onclick="loadRoute('${r.start}', '${r.end}')">${r.start}–${r.end}</button>`;
    let html = favs.map(r => chip(r, 'fav')).join('');
    hist.forEach(r => { if (!isFavorite(r.start, r.end)) html += chip(r, 'hist'); });
    quickArea.innerHTML = html;

    const elRow = document.getElementById('rowQuickRoute');
    const hasRoute = !!(startStation.value && endStation.value);
    elRow.style.display = (favs.length || hist.length || (hasRoute && currentTrainData)) ? 'flex' : 'none';
    setTimeout(updateScrollHint, 100);
}

function updateScrollHint() {
    const el = document.getElementById('quickRouteArea');
    const hint = document.getElementById('scrollHint');
    if (el.scrollWidth > el.clientWidth) {
        hint.style.opacity = '1';
        el.onscroll = () => {
            if (el.scrollLeft + el.clientWidth >= el.scrollWidth - 5) {
                hint.style.opacity = '0';
            } else {
                hint.style.opacity = '1';
            }
        };
    } else {
        hint.style.opacity = '0';
    }
}

// ---------- 第一次使用的教學提示 ----------
const LS_COACH_LIST = "tl_coach_list_v1";
let coachSteps = [], coachIdx = 0, coachKey = null;

function coachSeen(key) { try { return localStorage.getItem(key) === '1'; } catch (e) { return true; } }
function coachMark(key) { try { localStorage.setItem(key, '1'); } catch (e) {} }
function modalOpen() { return document.getElementById('aboutModal').style.display === 'flex'; }

// 教學用的示範班次（不依賴真實資料，每一步都看得到）
function demoRow({ type, color, no, dep, arr, late, orig, led, tap }) {
    return `<div class="row${late ? ' late' : ''}${tap ? ' tap' : ''}" style="--tc:${color}">
                ${led ? '<div class="led"><div class="led-dot top"></div><div class="led-dot bottom"></div></div>' : ''}
                <div class="r-meta"><span class="r-type" style="color:${color}">${type}</span><span>${no}</span></div>
                <div class="r-time"><span class="r-dep">${dep}</span><span class="r-arr">${arr}</span></div>
                <div class="r-side">${late ? `晚 ${late} 分<span class="o">原定 ${orig}</span>` : ''}</div>
            </div>`;
}
const COACH_STEPS = [
    { demo: [{ type: '自強號', color: '#DF3F1F', no: '117', dep: '16:01', arr: '16:51' }],
      text: '<b>大字是發車時間</b>，箭頭後面是抵達時間。' },
    { demo: [{ type: '自強號', color: '#DF3F1F', no: '117', dep: '16:01', arr: '16:51' },
             { type: '區間車', color: '#0076B2', no: '3175', dep: '16:08', arr: '16:58', late: 5, orig: '16:03' }],
      text: '<span class="late">黃色</span>是誤點的車，顯示的時間<b>已經加上誤點</b>。' },
    { demo: [{ type: '區間快', color: '#0076B2', no: '3179', dep: '16:12', arr: '17:02', led: true, tap: true }],
      text: '<b>綠燈閃爍</b>代表 10 分鐘內發車。<b>點班次</b>可以看列車現在在哪。' }
];

function startCoach(key) {
    coachKey = key; coachSteps = COACH_STEPS; coachIdx = 0;
    document.getElementById('coach').classList.add('on');
    document.body.classList.add('noscroll');
    showCoachStep();
}
function showCoachStep() {
    const st = coachSteps[coachIdx];
    document.getElementById('coachDemo').innerHTML = st.demo.map(demoRow).join('');
    document.getElementById('coachText').innerHTML = st.text;
    document.getElementById('coachStep').innerText = `${coachIdx + 1} / ${coachSteps.length}`;
    document.getElementById('coachNext').innerText = coachIdx === coachSteps.length - 1 ? '開始使用' : '下一步';
}
function nextCoach() {
    if (coachIdx < coachSteps.length - 1) { coachIdx++; showCoachStep(); }
    else endCoach(false);
}
function endCoach() {
    if (coachKey) coachMark(coachKey);
    coachKey = null;
    document.getElementById('coach').classList.remove('on');
    document.body.classList.remove('noscroll');
}

// 第一次查到班次後出現一次
function maybeStartListCoach() {
    if (coachSeen(LS_COACH_LIST) || coachKey || modalOpen()) return;
    if (!document.querySelector('#cardList .row')) return;
    setTimeout(() => { if (!coachKey && !modalOpen() && !coachSeen(LS_COACH_LIST)) startCoach(LS_COACH_LIST); }, 700);
}
function replayCoach() {
    const wasOpen = modalOpen();
    if (wasOpen) closeModal();
    setTimeout(() => startCoach(LS_COACH_LIST), wasOpen ? 380 : 0);
}

init();
