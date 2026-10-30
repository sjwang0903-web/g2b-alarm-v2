import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from urllib.parse import unquote
import requests
import xml.etree.ElementTree as ET

sys.stdout.reconfigure(line_buffering=True)

KST = timezone(timedelta(hours=9))
now = datetime.now(KST)

# 조회 기간: 최근 7일
inqryBgnDt14 = (now - timedelta(days=7)).strftime("%Y%m%d") + "000000"
inqryEndDt14 = now.strftime("%Y%m%d%H%M59")

# Service Key 안전하게 불러오기
RAW_SERVICE_KEY = os.environ.get("SERVICE_KEY", "").strip()
# 이미 디코딩되어 있다면 unquote를 거쳐도 원본 유지
SERVICE_KEY = unquote(RAW_SERVICE_KEY)

WEB_JSON_FILE = "notices.json"

# 키워드 및 금액 필터 (테스트 시 조건을 완화하여 동작 여부 확인)
P1_KEYWORDS = ["설계", "건립", "신축", "개발"]
P2_KEYWORDS = ["타당성", "마스터", "기본계획", "기본구상", "공모관리", "공모 관리"]
EXCLUDE_KEYWORDS = ["건설사업관리용역", "폐기물", "감리자", "내진보강"]

def save_web_dashboard_json(items):
    existing_items_map = {}
    if os.path.exists(WEB_JSON_FILE):
        try:
            with open(WEB_JSON_FILE, "r", encoding="utf-8") as f:
                old_data = json.load(f)
                if isinstance(old_data, list):
                    for old_item in old_data:
                        if "id" in old_item:
                            existing_items_map[old_item["id"]] = old_item
        except Exception:
            pass

    formatted_list = []
    for idx, item in enumerate(items, 1):
        item_id = f"AUTO_{idx:03d}"
        
        is_hidden = False
        comments = []
        is_important = False
        is_checked = False
        
        if item_id in existing_items_map:
            is_hidden = existing_items_map[item_id].get("isHidden", False)
            comments = existing_items_map[item_id].get("comments", [])
            is_important = existing_items_map[item_id].get("isImportant", False)
            is_checked = existing_items_map[item_id].get("isChecked", False)

        formatted_list.append({
            "id": item_id,
            "ntceKindNm": item.get('source_type'),
            "ntceNm": item.get('title'),
            "organ": item.get('notice_instt'),
            "price": item.get('raw_price', 0),
            "dateNotice": item.get('notice_dt', '-'),
            "dateBrief": item.get('expl_info', '-'),
            "dateLimit": item.get('bid_close_dt', '-') if item.get('bid_close_dt', '-') != '-' else item.get('reg_close_dt', '-'),
            "dateOpen": item.get('open_dt', '-'),
            "chgRsn": item.get('chg_rsn', ''),
            "isImportant": is_important,
            "isHidden": is_hidden,
            "isChecked": is_checked,
            "url": item.get('url', ''),
            "comments": comments,
            "files": []
        })

    try:
        with open(WEB_JSON_FILE, "w", encoding="utf-8") as f:
            json.dump(formatted_list, f, ensure_ascii=False, indent=4)
        print(f"웹 대시보드 연동 파일({WEB_JSON_FILE}) 생성 완료. (총 {len(formatted_list)}건)")
        
        if os.environ.get("GITHUB_ACTIONS") == "true":
            subprocess.run(["git", "config", "--global", "user.name", "github-actions[bot]"], check=True)
            subprocess.run(["git", "config", "--global", "user.email", "github-actions[bot]@users.noreply.github.com"], check=True)
            subprocess.run(["git", "add", WEB_JSON_FILE], check=True)
            status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
            if status.stdout.strip():
                subprocess.run(["git", "commit", "-m", "Auto-update notices.json via bot [skip ci]"], check=True)
                subprocess.run(["git", "push"], check=True)
                print("notices.json 깃허브 자동 푸시 완료!")
            else:
                print("변경사항이 없어 푸시를 스킵합니다.")
    except Exception as e:
        print(f"웹 대시보드 JSON 저장 및 푸시 중 오류: {e}")

def fetch_api_data(base_url, query_params):
    if not SERVICE_KEY:
        print("❌ SERVICE_KEY가 설정되지 않았습니다.")
        return None
    try:
        params = query_params.copy()
        params['ServiceKey'] = SERVICE_KEY
        
        response = requests.get(base_url, params=params, timeout=15)
        
        if response.status_code != 200:
            print(f"⚠️ HTTP Error {response.status_code} - {base_url}")
            return None
        if "<errMsg>" in response.text or "SERVICE ERROR" in response.text:
            print(f"⚠️ API Response Error: {response.text[:200]}")
            return None
        return ET.fromstring(response.text)
    except Exception as e:
        print(f"❌ API 요청 중 예외 발생: {e}")
        return None

def format_datetime_str(dt_str):
    if not dt_str or dt_str == '-': return '-'
    clean_str = "".join(filter(str.isdigit, dt_str))
    try:
        if len(clean_str) >= 8: return f"{clean_str[:4]}-{clean_str[4:6]}-{clean_str[6:8]}"
    except Exception: pass
    return dt_str

def check_bids():
    matched_bids = []
    endpoints = [
        ("본공고", "http://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServc"),
        ("본공고", "http://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoCnstwk"),
        ("사전규격", "http://apis.data.go.kr/1230000/ad/BidPublicInfoService/getPreSpecListServc"),
        ("사전규격", "http://apis.data.go.kr/1230000/ad/BidPublicInfoService/getPreSpecListCnstwk"),
        ("발주계획", "http://apis.data.go.kr/1230000/ad/BidPublicInfoService/getOrderPlanList")
    ]

    print(f"🔍 수집 시작: {inqryBgnDt14[:8]} ~ {inqryEndDt14[:8]}")

    for source_type, base_url in endpoints:
        page_no = 1
        while page_no <= 2:
            root = fetch_api_data(base_url, {
                "inqryDiv": "1",
                "inqryBgnDt": inqryBgnDt14,
                "inqryEndDt": inqryEndDt14,
                "pageNo": str(page_no),
                "numOfRows": "50"
            })
            
            if root is None:
                break
                
            items = root.findall(".//item")
            print(f"[{source_type}] Page {page_no}: {len(items)}건 조회됨")
            
            if not items:
                break
                
            for item in items:
                bid_nm = item.findtext('bidNtceNm') or item.findtext('prslPblancNm') or item.findtext('bfSpecNm') or item.findtext('ordrPlnNm') or '-'
                
                # 제외 키워드 검사
                if any(ex in bid_nm for ex in EXCLUDE_KEYWORDS):
                    continue
                
                # 포함 키워드 검사
                has_p1 = any(k in bid_nm for k in P1_KEYWORDS)
                has_p2 = any(k in bid_nm for k in P2_KEYWORDS)
                
                if not (has_p1 or has_p2):
                    continue

                presmpt_prce = item.findtext('presmptPrce') or item.findtext('asignBdgAmt') or item.findtext('totBudget') or '0'
                try:
                    price_val = float(presmpt_prce.replace(',', '').strip())
                except ValueError:
                    price_val = 0

                # 조건 만족 시 수집 리스트에 추가
                matched_bids.append({
                    'source_type': source_type,
                    'title': bid_nm,
                    'notice_instt': item.findtext('ntceInsttNm') or item.findtext('dlryInsttNm') or '-',
                    'raw_price': price_val,
                    'notice_dt': format_datetime_str(item.findtext('bidNtceDt') or item.findtext('prslRegDt') or item.findtext('rgstDt') or '-'),
                    'expl_info': format_datetime_str(item.findtext('dcmtgOprtnDt') or '-'),
                    'reg_close_dt': format_datetime_str(item.findtext('bidQlfctRgstDt') or item.findtext('prslClseDt') or '-'),
                    'bid_close_dt': format_datetime_str(item.findtext('bidClseDt') or item.findtext('propClseDt') or '-'),
                    'open_dt': format_datetime_str(item.findtext('opengDt') or '-'),
                    'url': item.findtext('bidNtceDtlUrl') or item.findtext('prslDtlUrl') or item.findtext('dtlUrl') or '',
                    'chg_rsn': item.findtext('chgNtceRsn') or ''
                })
            
            if len(items) < 50:
                break
            page_no += 1

    print(f"🎯 키워드 필터링 후 최종 공고 수: {len(matched_bids)}건")
    save_web_dashboard_json(matched_bids)

if __name__ == "__main__":
    check_bids()
