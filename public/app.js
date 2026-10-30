const STATION_INDEX={};Object.keys(STATION_DATA).forEach(r=>{STATION_DATA[r].forEach(s=>{STATION_INDEX[s]=r;});});
const DEFAULT_STATIONS = {"基隆市": "基隆", "新北市": "板橋", "臺北市": "臺北", "桃園市": "桃園", "新竹縣市": "新竹", "苗栗縣": "苗栗", "臺中市": "臺中", "彰化縣": "彰化", "南投縣": "集集", "雲林縣": "斗六", "嘉義縣市": "嘉義", "臺南市": "臺南", "高雄市": "高雄", "屏東縣": "屏東", "宜蘭縣": "羅東", "花蓮縣": "花蓮", "臺東縣": "臺東"};

const CACHE_PREFIX="train_data_v2_";

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
const LS_MOTION = "tl_pref_motion";
let motionOn = localStorage.getItem(LS_MOTION) !== 'off';
document.body.classList.toggle('no-motion', !motionOn);
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
    const v = localStorage.getItem('tl_favorites'); if (v && v.includes('侯硐')) localStorage.setItem('tl_favorites', v.split('侯硐').join('猴硐'));
} catch(e) {}
// 不再記查詢紀錄、也不再自動帶上次的路線（每次打開都是首頁）
try { ['tl_history','pref_start_region','pref_start_station','pref_end_region','pref_end_station'].forEach(k => localStorage.removeItem(k)); } catch(e) {}

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
    history.pushState({ modal: true, depth: histDepth() + 1 }, '', '');
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
    // 時刻表裡點 LOGO 回首頁；首頁連點 5 下才進後台
    if (!isHome()) { leaveTimetable(); return; }
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
    document.getElementById('fmt24').classList.toggle('on', is24Hour);
    document.getElementById('fmt12').classList.toggle('on', !is24Hour);
    document.getElementById('motionOn').classList.toggle('on', motionOn);
    document.getElementById('motionOff').classList.toggle('on', !motionOn);
    // 「顯示已發車」的文字在 renderCards 依班次數更新
}

function toggleTimeFormat() { setTimeFormat(!is24Hour); }
function setTimeFormat(v) { if (v === is24Hour) return; is24Hour=v; localStorage.setItem(LS_IS_24H, is24Hour); updateToggleBtns(); reRenderLocal(); scrollToFirstActive();}
// 選單「動畫」開關：關掉時跟系統「減少動態效果」一樣，過場都不播
function setMotion(v) { motionOn = v; localStorage.setItem(LS_MOTION, v ? 'on' : 'off'); document.body.classList.toggle('no-motion', !v); updateToggleBtns(); }
function toggleShowAll() { isShowAll=!isShowAll; updateToggleBtns(); reRenderLocal(); playListEnter(); scrollToFirstActive();}
// 列表淡入只在查到新資料或展開／收起時播一次，每秒重畫時不要重播
function playListEnter() {
    list.classList.remove('enter'); void list.offsetWidth; list.classList.add('enter');
    clearTimeout(playListEnter.t); playListEnter.t = setTimeout(() => list.classList.remove('enter'), 700);
}

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

function init() {
    logSystem("App Started"); 
    startTicker(); 
    updateToggleBtns();
    
    document.getElementById('rowTools').style.display = 'none';

    // Cache 安全性檢查
    try {
        const regions=Object.keys(STATION_DATA); const rOpts=regions.map(r=>`<option value="${r}">${r}</option>`).join('');
        startRegion.innerHTML=`<option value=""></option>`+rOpts; endRegion.innerHTML=`<option value=""></option>`+rOpts;
        clearStations();
        list.innerHTML='';
        checkLocksOnLoad();
    } catch(e) {
        console.error("Cache corrupted, clearing...", e);
        localStorage.clear();
        window.location.reload();
    }
    
    // 重新整理時瀏覽器會留著原本那一筆紀錄：退回最底下那筆（首頁），不然首頁左右滑會滑出另一個一樣的首頁
    if (histDepth() > 0) history.go(-histDepth()); else history.replaceState({ depth: 0 }, '', '');
    updateStationDisplay();
    renderFavs();
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
    else { renderFavs(); updateActionButton(); }
    closeModal();
}



function swapStations() {
    if(!startStation.value||!endStation.value) return; logSystem("Action: Swap");
    const sR=startRegion.value; const sS=startStation.value;
    // 兩個站名交叉換位置
    const parts = ['b', 'span'].map(t => [document.querySelector('#startPick ' + t), document.querySelector('#endPick ' + t)]);
    const before = parts.map(p => p.map(rectOf));
    setMenu('start',endRegion.value,endStation.value); setMenu('end',sR,sS);
    if (!reduceMotion()) parts.forEach((p, j) => { flipFrom(p[0], before[j][1], null, 260); flipFrom(p[1], before[j][0], null, 260); });
    markAsChanged();
}

function markAsChanged() {
    if (isResumeHintActive) {
        closeResumePill();
    }

    if(!startStation.value||!endStation.value) return;
    isNextDayLoaded = false;
    // 首頁不套快取：不然 1 分鐘內再選同一條路線，按鈕會在首頁變成冷卻中的「更新」按不下去
    if (isHome()) { updateActionButton(); return; }
    
    attemptLoadCache(false);
    renderFavs();
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
    showTimetable();
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
    showTimetable();
    
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
        renderCards(json); playListEnter();

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
        if (!isDeparted && !foundFirstActive) {
            activeId = 'id="firstActive"'; foundFirstActive = true;
            // 展開後畫面停在這裡，收起按鈕放在已發車和還沒發車中間，不用往上滑找
            if (isShowAll && hiddenCount > 0) html += `<button class="fold-departed" onclick="toggleShowAll()">收起已發車${CHEVRON}</button>`;
        }

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
    const title = alerts.length > 1 ? `營運公告（${alerts.length} 則）` : alerts[0].title;
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

// 每筆自己加的瀏覽紀錄都記著第幾層，首頁是 0
function histDepth() { return (history.state && history.state.depth) || 0; }
window.addEventListener('popstate', () => {
    const modal = document.getElementById('aboutModal');
    const st = history.state || {};
    // iOS 往左滑（下一頁）會走到已經關掉的紀錄：選單那筆直接退回；時刻表那筆就重新打開剛剛那條路線（不自動查詢）
    if (st.modal && modal.style.display !== 'flex') { history.back(); return; }
    if (st.view && isHome()) {
        if (lastRoute) { const r = lastRoute; loadRoute(r.start, r.end, null, true); } else history.back();
        return;
    }
    // 在時刻表按返回（或往右滑）回到首頁，而不是離開網站
    if (!isHome() && !(history.state && history.state.view)) goHome();
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

const LS_FAV = "tl_favorites";
const MAX_FAV = 6;
const homeFavs = document.getElementById('homeFavs');
const favPanel = document.getElementById('favPanel');
const btnFav = document.getElementById('btnFav');

// ---------- 首頁／時刻表切換 ----------
function isHome() { return document.body.classList.contains('home'); }
function clearStations() {
    startRegion.value = ''; endRegion.value = '';
    startStation.innerHTML = endStation.innerHTML = `<option value=""></option>`;
}
// ---------- 過場動畫：短、安靜；系統設定「減少動態效果」時全部不播 ----------
const EASE = 'cubic-bezier(.2,.7,.2,1)';
function reduceMotion() { return !motionOn || !!(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches); }
const rectOf = el => el ? el.getBoundingClientRect() : null;
// FLIP：元素已經在新位置，從舊位置 from 平移（必要時縮放）過去。fit = 'width' / 'height' 決定縮放比例，不給就只平移
function flipFrom(el, from, fit, dur) {
    if (!el || !from || !el.animate) return;
    const to = el.getBoundingClientRect();
    if (!to.width || !from.width) return;
    const k = fit ? from[fit] / to[fit] : 1;
    el.animate([
        { transformOrigin: '0 0', transform: `translate(${from.left - to.left}px, ${from.top - to.top}px) scale(${k})` },
        { transformOrigin: '0 0', transform: 'none' }
    ], { duration: dur || 320, easing: EASE });
}
// 換頁：其他東西從旁邊滑一點點進來（dir 1 從右、-1 從左）
function slideIn(els, dir) {
    els.forEach(el => el && el.animate && el.animate([
        { opacity: 0, transform: `translateX(${dir * 16}px)` }, { opacity: 1, transform: 'none' }
    ], { duration: 260, delay: 40, easing: EASE, fill: 'backwards' }));
}
function restartClass(el, cls, ms) {
    el.classList.remove(cls); void el.offsetWidth; el.classList.add(cls);
    clearTimeout(el['_t' + cls]); el['_t' + cls] = setTimeout(() => el.classList.remove(cls), ms);
}
const stnB = () => [document.querySelector('#startPick b'), document.querySelector('#endPick b')];
// 收藏路線那一行裡的起站、迄站文字
const favNames = row => row ? [...row.querySelectorAll('.go .rt')] : [];
const homeFavRow = (s, e) => [...homeFavs.querySelectorAll('.home-fav')].find(r => {
    const n = r.querySelectorAll('.go .rt'); return n.length === 2 && n[0].textContent === s && n[1].textContent === e;
});
// 首頁 → 時刻表：按收藏進來時兩個站名從那一行平移放大到上方；按查詢進來時整組站名從中間移到左上
function playTimetableEnter(fromStops, fromNames) {
    if (reduceMotion()) return;
    if (fromNames && fromNames.length === 2) {
        stnB().forEach((b, k) => flipFrom(b, fromNames[k], 'width', 340));
        // 飛上去時要蓋在查詢按鈕那一塊上面；圓點、線條晚一點淡入
        restartClass(document.querySelector('.route'), 'dots-in', 500);
    } else {
        flipFrom(document.querySelector('.route-stops'), fromStops, 'height');
    }
    slideIn([document.querySelector('.swap'), document.querySelector('.fav-group'), btnAction, list], 1);
}
// 時刻表 → 首頁：首頁從左邊滑回來；這條路線有收藏的話，站名縮回那一行
function playHomeEnter(pair, fromNames) {
    if (reduceMotion()) return;
    slideIn([document.querySelector('.route'), homeFavs], -1);
    const row = homeFavRow(pair.start, pair.end); if (!row) return;
    // 那一行平常會切掉超出的部分（往左滑刪除用），飛進去的時候先打開
    row.style.overflow = 'visible'; setTimeout(() => { row.style.overflow = ''; }, 360);
    favNames(row).forEach((n, k) => flipFrom(n, fromNames[k], 'width', 340));
    const arrow = row.querySelector('.go .route-arrow');
    if (arrow) arrow.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 200, delay: 140, fill: 'backwards' });
}
// 進時刻表：多一筆瀏覽紀錄，讓返回鍵可以回首頁
// beforeShow：切畫面前先換站名；favRow：從首頁哪一行收藏點進來（動畫從那裡開始）
// inPlace：已經在時刻表那筆紀錄上（往下一頁滑回來），不要再多加一筆
function showTimetable(beforeShow, favRow, inPlace) {
    if (!isHome()) { if (beforeShow) beforeShow(); return; }
    hideUndo(); closeFavSwipe();
    window.scrollTo(0, 0);
    const fromStops = rectOf(document.querySelector('.route-stops'));
    const fromNames = favNames(favRow).map(rectOf);
    if (beforeShow) beforeShow();
    document.body.classList.remove('home');
    homeEditing = false;
    if (!inPlace) history.pushState({ view: 'timetable', depth: histDepth() + 1 }, '', '');
    playTimetableEnter(fromStops, fromNames);
}
function leaveTimetable() {
    if (history.state && history.state.view) history.back(); else goHome();
}
function goHome() {
    if (isHome()) return;
    window.scrollTo(0, 0);
    const pair = getCurrentPair(), fromNames = stnB().map(rectOf);
    if (pair.start && pair.end) lastRoute = pair;
    document.body.classList.add('home');
    if (retryTimer) { clearInterval(retryTimer); retryTimer = null; }
    if (autoResumeTimer) { clearTimeout(autoResumeTimer); autoResumeTimer = null; }
    closeResumePill();
    currentTrainData = null; showingSaved = false; isNextDayLoaded = false; isShowAll = false;
    lastFetchedPair = { start: '', end: '' };
    list.innerHTML = '';
    statusMsg.innerText = ''; statusMsg.className = 'status-left';
    document.getElementById('rowTools').style.display = 'none';
    document.getElementById('alertBar').hidden = true;
    clearStations();
    setFavPanel(false);
    updateStationDisplay(); renderFavs(); updateActionButton();
    window.scrollTo(0, 0);
    // 從左邊緣滑回來時首頁已經跟著手指滑進來了，不用再播一次
    if (skipHomeEnter) skipHomeEnter = false; else playHomeEnter(pair, fromNames);
}
let skipHomeEnter = false;
let lastRoute = null;

// ---------- 從螢幕左邊往右滑回首頁，滑的時候首頁會跟著滑進來 ----------
// iOS Safari、Android 手勢導航會自己接走邊緣手勢（那時這段不會動），主要給加到主畫面的 App 用
const EDGE_W = 24;
let edgeSwipe = null;
function buildBackPeek() {
    const p = document.createElement('div');
    p.className = 'back-peek';
    p.innerHTML = `<div class="container">${document.querySelector('.topbar').outerHTML}
        <div class="route"><div class="route-stops"><div class="stn from empty"><b data-ph="出發"></b></div><div class="stn to empty"><b data-ph="抵達"></b></div></div></div>
        <div class="home-favs">${homeFavs.innerHTML}</div></div>`;
    p.querySelectorAll('[id]').forEach(el => el.removeAttribute('id'));
    p.querySelectorAll('[onclick]').forEach(el => el.removeAttribute('onclick'));
    document.body.appendChild(p);
    return p;
}
document.addEventListener('touchstart', (e) => {
    if (isHome() || e.touches.length !== 1 || modalOpen() || coachKey) return;
    const t = e.touches[0];
    if (t.clientX > EDGE_W) return;
    edgeSwipe = { x0: t.clientX, y0: t.clientY, t0: Date.now(), dx: 0, peek: null };
}, { passive: true });
document.addEventListener('touchmove', (e) => {
    if (!edgeSwipe) return;
    const t = e.touches[0];
    const dx = t.clientX - edgeSwipe.x0, dy = t.clientY - edgeSwipe.y0;
    if (!edgeSwipe.peek) {
        if (Math.abs(dy) > 10 && Math.abs(dy) > dx) { edgeSwipe = null; return; }
        if (dx < 10) return;
        edgeSwipe.peek = buildBackPeek();
    }
    e.preventDefault();
    edgeSwipe.dx = Math.max(0, dx);
    edgeSwipe.peek.style.transform = `translateX(${edgeSwipe.dx - innerWidth}px)`;
}, { passive: false });
function endEdgeSwipe(cancel) {
    if (!edgeSwipe) return;
    const { peek, dx, t0 } = edgeSwipe; edgeSwipe = null;
    if (!peek) return;
    const fast = dx > 40 && dx / (Date.now() - t0) > 0.5;
    peek.style.transition = 'transform .2s ease-out';
    if (!cancel && (dx > innerWidth * 0.35 || fast)) {
        peek.style.transform = 'translateX(0)';
        setTimeout(() => { skipHomeEnter = true; leaveTimetable(); setTimeout(() => peek.remove(), 250); }, 200);
    } else {
        peek.style.transform = `translateX(-100%)`;
        setTimeout(() => peek.remove(), 220);
    }
}
document.addEventListener('touchend', () => endEdgeSwipe(false));
document.addEventListener('touchcancel', () => endEdgeSwipe(true));

// ---------- 收藏路線 ----------
function getFavs() { try { return JSON.parse(localStorage.getItem(LS_FAV) || "[]"); } catch (e) { return []; } }
function saveFavs(favs) { localStorage.setItem(LS_FAV, JSON.stringify(favs)); }
function getCurrentPair() { return { start: startStation.value, end: endStation.value }; }
function isFavorite(s, e) { return getFavs().some(f => f.start === s && f.end === e); }
const routeText = r => `<span class="rt">${r.start}</span><span class="route-arrow">→</span><span class="rt">${r.end}</span>`;

function addCurrentFavorite() {
    const cur = getCurrentPair(); if (!cur.start || !cur.end) return;
    const favs = getFavs();
    // 已收藏再按一次就取消（下面會出現「復原」）
    const i = favs.findIndex(f => f.start === cur.start && f.end === cur.end);
    if (i >= 0) { deleteFavorite(i); return; }
    if (favs.length >= MAX_FAV) { showToast(`收藏最多 ${MAX_FAV} 條`); return; }
    favs.push(cur); saveFavs(favs); logSystem("Fav: Added");
    renderFavs(); showToast('已加入收藏');
}
function loadRoute(s, e, fromEl, inPlace) {
    const sR = STATION_INDEX[s]; const eR = STATION_INDEX[e];
    if (!sR || !eR) return;
    setFavPanel(false);
    if (s === startStation.value && e === endStation.value && !isHome()) return;
    // 在時刻表的收藏欄換路線：站名淡入
    if (!isHome() && !reduceMotion()) document.querySelector('.route-stops').animate([{ opacity: .2 }, { opacity: 1 }], { duration: 220 });
    // 先換好站名再切畫面，動畫才會從首頁的收藏位置接到時刻表上的站名
    showTimetable(() => { setMenu('start', sR, s); setMenu('end', eR, e); }, fromEl && fromEl.closest('.home-fav'), inPlace);
    markAsChanged();
    if (!inPlace) doSearch();
}

function setFavPanel(open) {
    favPanel.hidden = !open;
    btnFav.classList.toggle('open', open);
    btnFav.setAttribute('aria-expanded', open);
}
function toggleFavPanel() { setFavPanel(favPanel.hidden); }

function renderFavs() {
    favOpen = null;
    const favs = getFavs();
    const cur = getCurrentPair();
    const hasRoute = !!(cur.start && cur.end);

    // 時刻表的收藏欄：目前路線綠字，還沒收藏就多一行「＋ 收藏這條路線」
    let html = favs.map(r => {
        const on = r.start === cur.start && r.end === cur.end;
        return `<button class="${on ? 'cur' : ''}" onclick="loadRoute('${r.start}','${r.end}')">${routeText(r)}</button>`;
    }).join('');
    if (hasRoute && !isFavorite(cur.start, cur.end)) html += `<button class="add" onclick="addCurrentFavorite()">＋ 收藏這條路線</button>`;
    favPanel.innerHTML = html;
    const saved = hasRoute && isFavorite(cur.start, cur.end);
    const btnAdd = document.getElementById('btnFavAdd');
    btnAdd.classList.toggle('on', saved);
    btnAdd.setAttribute('aria-label', saved ? '取消收藏' : '收藏這條路線');
    btnAdd.innerHTML = saved
        ? '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 7.5l3 3 6-7"/></svg>'
        : '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M7 2v10M2 7h10"/></svg>';

    // 首頁的收藏清單
    if (!favs.length) homeEditing = false;
    homeFavs.classList.toggle('editing', homeEditing);
    if (!favs.length) { homeFavs.innerHTML = `<div class="home-favs-empty">目前無收藏路線</div>`; return; }
    homeFavs.innerHTML = `<div class="home-favs-head"><span>收藏</span><button class="${homeEditing ? 'done' : ''}" onclick="toggleHomeEdit()">${homeEditing ? '完成' : '編輯'}</button></div>` +
        favs.map((r, i) => `<div class="home-fav" data-i="${i}">
            <button class="swipe-del" onclick="deleteFavorite(${i})" tabindex="-1">刪除</button>
            <div class="fav-inner">
            <span class="handle" aria-label="拖曳排序"><svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M3 5h10M3 8h10M3 11h10"/></svg></span>
            <button class="go" onclick="loadRoute('${r.start}','${r.end}', this)">${routeText(r)}</button>
            <button class="del" onclick="deleteFavorite(${i})">刪除</button>
            </div>
        </div>`).join('');
}

// ---------- 首頁編輯：拖曳排序、刪除 ----------
let homeEditing = false;
function toggleHomeEdit() { homeEditing = !homeEditing; renderFavs(); }
// 刪除不跳確認視窗：直接刪，下面出現「復原」6 秒，往旁邊或往下滑可以關掉
let undoFav = null;
function deleteFavorite(i, collapsed) {
    // 首頁那一行先收起來再刪
    const row = homeFavs.querySelector(`.home-fav[data-i="${i}"]`);
    if (!collapsed && row && isHome() && row.animate && !reduceMotion()) {
        if (row.dataset.removing) return;
        row.dataset.removing = '1';
        row.animate([{ height: row.offsetHeight + 'px', opacity: 1 }, { height: '0px', opacity: 0 }],
            { duration: 200, easing: 'ease-in', fill: 'forwards' }).onfinish = () => deleteFavorite(i, true);
        return;
    }
    const favs = getFavs(); const [r] = favs.splice(i, 1); if (!r) return;
    saveFavs(favs);
    logSystem("Fav: Removed"); renderFavs();
    undoFav = { i, r };
    document.getElementById('undoText').innerHTML = `已刪除　${routeText(r)}`;
    const bar = document.getElementById('undoBar'); bar.classList.add('show');
    clearTimeout(deleteFavorite.t);
    deleteFavorite.t = setTimeout(hideUndo, 6000);
}
function undoDelete() {
    if (!undoFav) return;
    const favs = getFavs();
    if (!favs.some(f => f.start === undoFav.r.start && f.end === undoFav.r.end)) { favs.splice(undoFav.i, 0, undoFav.r); saveFavs(favs); }
    const i = undoFav.i;
    logSystem("Fav: Undo"); hideUndo(); renderFavs();
    const row = homeFavs.querySelector(`.home-fav[data-i="${i}"]`);
    if (row && row.animate && !reduceMotion()) row.animate([{ height: '0px', opacity: 0 }, { height: row.offsetHeight + 'px', opacity: 1 }], { duration: 220, easing: EASE });
}
function hideUndo() {
    undoFav = null; clearTimeout(deleteFavorite.t);
    const bar = document.getElementById('undoBar');
    bar.classList.remove('show'); bar.style.transform = ''; bar.style.opacity = ''; bar.style.transition = '';
}
// 復原通知可以滑掉
const undoBar = document.getElementById('undoBar');
let undoDrag = null;
undoBar.addEventListener('pointerdown', (e) => {
    if (e.target.closest('button')) return;
    undoDrag = { x0: e.clientX, y0: e.clientY, dx: 0, dy: 0 };
    undoBar.setPointerCapture(e.pointerId); undoBar.style.transition = 'none';
    clearTimeout(deleteFavorite.t);
});
undoBar.addEventListener('pointermove', (e) => {
    if (!undoDrag) return;
    undoDrag.dx = e.clientX - undoDrag.x0; undoDrag.dy = Math.max(0, e.clientY - undoDrag.y0);
    const d = Math.max(Math.abs(undoDrag.dx), undoDrag.dy);
    undoBar.style.transform = `translate(calc(-50% + ${undoDrag.dx}px), ${undoDrag.dy}px)`;
    undoBar.style.opacity = String(Math.max(0.2, 1 - d / 200));
});
function endUndoDrag() {
    if (!undoDrag) return;
    const { dx, dy } = undoDrag; undoDrag = null;
    undoBar.style.transition = '';
    if (Math.abs(dx) > 70 || dy > 40) {
        undoBar.style.transform = Math.abs(dx) > 70 ? `translate(calc(-50% + ${dx > 0 ? '' : '-'}100vw), 0)` : 'translate(-50%, 120%)';
        undoBar.style.opacity = '0';
        setTimeout(hideUndo, 200);
    } else {
        undoBar.style.transform = ''; undoBar.style.opacity = '';
        deleteFavorite.t = setTimeout(hideUndo, 6000);
    }
}
undoBar.addEventListener('pointerup', endUndoDrag);
undoBar.addEventListener('pointercancel', endUndoDrag);

// 收藏往左滑：露出紅色「刪除」，要再按一下才刪
const SWIPE_W = 80;
let favSwipe = null, favOpen = null, favSwipedAt = 0;
function closeFavSwipe() {
    if (!favOpen) return;
    favOpen.style.transform = ''; favOpen = null;
}
homeFavs.addEventListener('pointerdown', (e) => {
    if (homeEditing || e.target.closest('.swipe-del')) return;
    const inner = e.target.closest('.fav-inner'); if (!inner) return;
    if (favOpen && favOpen !== inner) closeFavSwipe();
    favSwipe = { inner, x0: e.clientX, y0: e.clientY, base: favOpen === inner ? -SWIPE_W : 0, dx: 0, on: false, id: e.pointerId };
});
homeFavs.addEventListener('pointermove', (e) => {
    if (!favSwipe || e.pointerId !== favSwipe.id) return;
    const dx = e.clientX - favSwipe.x0, dy = e.clientY - favSwipe.y0;
    if (!favSwipe.on) {
        if (Math.abs(dy) > 8 && Math.abs(dy) > Math.abs(dx)) { favSwipe = null; return; }
        if (Math.abs(dx) < 8) return;
        favSwipe.on = true; favSwipe.inner.setPointerCapture(e.pointerId);
        favSwipe.inner.style.transition = 'none';
    }
    // 拉超過刪除按鈕的寬度後變得很難拉，提示到底了
    const x = Math.min(0, favSwipe.base + dx);
    favSwipe.dx = x < -SWIPE_W ? -SWIPE_W + (x + SWIPE_W) / 4 : x;
    favSwipe.inner.style.transform = `translateX(${favSwipe.dx}px)`;
});
function endFavSwipe() {
    if (!favSwipe) return;
    const { inner, dx, on } = favSwipe; favSwipe = null;
    if (!on) return;
    inner.style.transition = '';
    favSwipedAt = Date.now();
    if (dx < -SWIPE_W / 2) { inner.style.transform = `translateX(${-SWIPE_W}px)`; favOpen = inner; }
    else { inner.style.transform = ''; if (favOpen === inner) favOpen = null; }
}
homeFavs.addEventListener('pointerup', endFavSwipe);
// 剛滑完放開會多一次 click；已經滑開的那列，點一下是收回去，不是進時刻表
homeFavs.addEventListener('click', (e) => {
    const inner = e.target.closest('.fav-inner'); if (!inner) return;
    if (Date.now() - favSwipedAt < 400 || inner === favOpen) {
        e.stopPropagation(); e.preventDefault();
        if (inner === favOpen && Date.now() - favSwipedAt >= 400) closeFavSwipe();
    }
}, true);
homeFavs.addEventListener('pointercancel', endFavSwipe);
document.addEventListener('pointerdown', (e) => { if (favOpen && !e.target.closest('.home-fav')) closeFavSwipe(); });

let favDrag = null;
homeFavs.addEventListener('pointerdown', (e) => {
    const handle = e.target.closest('.handle'); if (!handle || !homeEditing) return;
    const row = handle.closest('.home-fav');
    const rows = [...homeFavs.querySelectorAll('.home-fav')];
    e.preventDefault();
    handle.setPointerCapture(e.pointerId);
    favDrag = { row, rows, from: +row.dataset.i, to: +row.dataset.i, y0: e.clientY, h: row.offsetHeight };
    row.classList.add('dragging');
});
homeFavs.addEventListener('pointermove', (e) => {
    if (!favDrag) return;
    const { row, rows, from, h } = favDrag;
    const dy = e.clientY - favDrag.y0;
    const to = Math.max(0, Math.min(rows.length - 1, from + Math.round(dy / h)));
    favDrag.to = to;
    row.style.transform = `translateY(${dy}px)`;
    rows.forEach((r, i) => {
        if (r === row) return;
        let shift = 0;
        if (from < to && i > from && i <= to) shift = -h;
        if (from > to && i < from && i >= to) shift = h;
        r.style.transition = 'transform .15s';
        r.style.transform = shift ? `translateY(${shift}px)` : '';
    });
});
function endFavDrag() {
    if (!favDrag) return;
    const { from, to } = favDrag; favDrag = null;
    if (from !== to) {
        const favs = getFavs(); const [m] = favs.splice(from, 1); favs.splice(to, 0, m); saveFavs(favs);
        logSystem("Fav: Reordered");
    }
    renderFavs();
}
homeFavs.addEventListener('pointerup', endFavDrag);
homeFavs.addEventListener('pointercancel', endFavDrag);

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
                <div class="r-time"><span class="r-dep">${formatTime(dep)}</span><span class="r-arr">${formatTime(arr)}</span></div>
                <div class="r-side">${late ? `晚 ${late} 分<span class="o">原定 ${formatTime(orig)}</span>` : ''}</div>
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
