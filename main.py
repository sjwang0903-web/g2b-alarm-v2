import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from urllib.parse import unquote, quote
import requests
import xml.etree.ElementTree as ET

# 콘솔 출력 버퍼링 해제 (GitHub Actions 실시간 로그 출력)
sys.stdout.reconfigure(line_buffering=True)

# 한국 표준시(KST: UTC+9) 고정
KST = timezone(timedelta(hours=9))
now = datetime.now(KST)

# -------------------------------------------------------------
# 날짜 및 기간 설정
# -------------------------------------------------------------
past_7_days = now - timedelta(days=7)

inqryBgnDt14 = past_7_days.strftime("%Y%m%d%H%M00")
inqryEndDt14 = now.strftime("%Y%m%d%H%M59")

inqryBgnDate12 = past_7_days.strftime("%Y%m%d0000")
today_str12 = now.strftime("%Y%m%d2359")

order_bgn_ym = past_7_days.strftime("%Y%m")
order_end_ym = f"{now.year + 1}{now.month:02d}"

RAW_SERVICE_KEY = unquote(unquote(os.environ.get("SERVICE_KEY", "").strip()))

WEB_JSON_FILE = "notices.json"

# 키워드 및 제외키워드 설정 ("00부대" 포함)
P1_KEYWORDS = ["설계", "건립", "신축", "개발"]
P2_KEYWORDS = ["타당성", "마스터", "기본계획", "기본구상", "공모관리", "공모 관리"]
EXCLUDE_KEYWORDS = ["건설사업관리용역", "폐기물", "감리자", "내진보강", "00부대"]

def fetch_api_data(base_url, query_params):
    if not RAW_SERVICE_KEY:
        print("    [경고] SERVICE_KEY가 설정되지 않았습니다.")
        return None

    try:
        encoded_key = quote(RAW_SERVICE_KEY, safe='')
        query_str = "&".join([f"{k}={v}" for k, v in query_params.items()])
        full_url = f"{base_url}?{query_str}&ServiceKey={encoded_key}"
        
        response = requests.get(full_url, timeout=15)
        
        if response.status_code != 200:
            print(f"    [HTTP 에러 {response.status_code}] - {base_url}")
            return None
            
        if "<errMsg>" in response.text or "<returnAuthMsg>" in response.text or "SERVICE ERROR" in response.text:
            print(f"    [API 인증/시스템 에러]: {response.text[:180].strip()}")
            return None

        return ET.fromstring(response.text)
    except Exception as e:
        print(f"    [API 예외 발생]: {e}")
        return None

def format_datetime_str(dt_str):
    if not dt_str or dt_str == '-':
        return '-'
    clean_str = "".join(filter(str.isdigit, dt_str))
    try:
        if len(clean_str) >= 12:
            return f"{clean_str[:4]}-{clean_str[4:6]}-{clean_str[6:8]} {clean_str[8:10]}:{clean_str[10:12]}"
        elif len(clean_str) == 8:
            return f"{clean_str[:4]}-{clean_str[4:6]}-{clean_str[6:8]}"
    except Exception:
        pass
    return dt_str

def extract_attachments(item):
    attachments_map = {}
    
    for child in item:
        tag = child.tag
        val = (child.text or "").strip()
        if not val:
            continue
            
        if "url" in tag.lower():
            digits = "".join(filter(str.isdigit, tag))
            idx = digits if digits else "1"
            if idx not in attachments_map:
                attachments_map[idx] = {'name': '', 'url': ''}
            attachments_map[idx]['url'] = val
            
        elif "filenm" in tag.lower() or "specfile" in tag.lower() or "docnm" in tag.lower():
            digits = "".join(filter(str.isdigit, tag))
            idx = digits if digits else "1"
            if idx not in attachments_map:
                attachments_map[idx] = {'name': '', 'url': ''}
            attachments_map[idx]['name'] = val

    final_attachments = []
    for idx, info in sorted(attachments_map.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0):
        if info['url']:
            name = info['name'] if info['name'] else f"첨부문서_{idx}"
            final_attachments.append({'name': name, 'url': info['url']})
            
    return final_attachments

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
            "files": item.get('attachments', [])
        })

    try:
        with open(WEB_JSON_FILE, "w", encoding="utf-8") as f:
            json.dump(formatted_list, f, ensure_ascii=False, indent=4)
        print(f"\n[성공] 웹 대시보드 연동 파일({WEB_JSON_FILE}) 생성 완료. (총 {len(formatted_list)}건)")
        
        if os.environ.get("GITHUB_ACTIONS") == "true":
            subprocess.run(["git", "config", "--global", "user.name", "github-actions[bot]"], check=True)
            subprocess.run(["git", "config", "--global", "user.email", "github-actions[bot]@users.noreply.github.com"], check=True)
            subprocess.run(["git", "add", WEB_JSON_FILE], check=True)
            status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
            if status.stdout.strip():
                subprocess.run(["git", "commit", "-m", "Auto-update notices.json via bot [skip ci]"], check=True)
                subprocess.run(["git", "push"], check=True)
                print("-> notices.json 깃허브 자동 푸시 완료!")
            else:
                print("-> 변경사항이 없어 푸시를 스킵합니다.")
    except Exception as e:
        print(f"웹 대시보드 JSON 저장 및 푸시 중 오류: {e}")

def check_bids():
    matched_bids = []

    print(f"==================================================")
    print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')} KST] 알리미2 수집 시작")
    print(f"==================================================")

    # 1. 본공고 API (알리미1 검증 로직 반영)[cite: 4]
    print("\n[1] 본공고 API 조회 중...")
    bid_endpoints = [
        ("용역", "http://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServc"),
        ("공사", "http://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoCnstwk")
    ]

    for category_name, base_url in bid_endpoints:
        page_no = 1
        num_of_rows = "100"
        
        while True:
            params = {
                "inqryDiv": "1",
                "inqryBgnDt": inqryBgnDt14,
                "inqryEndDt": inqryEndDt14,
                "pageNo": str(page_no),
                "numOfRows": num_of_rows
            }
            
            root = fetch_api_data(base_url, params)
            items = root.findall(".//item") if root is not None else []
            
            if not items and page_no == 1:
                params["inqryBgnDt"] = inqryBgnDate12
                params["inqryEndDt"] = today_str12
                root = fetch_api_data(base_url, params)
                items = root.findall(".//item") if root is not None else []

            total_count_elem = root.find(".//totalCount") if root is not None else None
            total_count = int(total_count_elem.text) if total_count_elem is not None and total_count_elem.text.isdigit() else 0

            print(f"  -> [{category_name}] 본공고 페이지 {page_no} 조회 성공! (수집 건수: {len(items)}건)")

            if not items:
                break

            for item in items:
                bid_nm = item.findtext('bidNtceNm') or '-'

                if any(ex in bid_nm for ex in EXCLUDE_KEYWORDS):
                    continue

                has_p1_kw = any(k in bid_nm for k in P1_KEYWORDS)
                has_p2_kw = any(k in bid_nm for k in P2_KEYWORDS)

                if not (has_p1_kw or has_p2_kw):
                    continue

                presmpt_prce = (
                    item.findtext('presmptPrce') or 
                    item.findtext('asignBdgAmt') or 
                    item.findtext('estmAmt') or
                    item.findtext('totpjtPrce') or '0'
                )

                try:
                    price_val = float(presmpt_prce.replace(',', '').strip())
                except ValueError:
                    price_val = 0

                is_p1 = has_p1_kw and price_val >= 500000000
                is_p2 = has_p2_kw

                if is_p1 or is_p2:
                    matched_bids.append({
                        'source_type': '본공고',
                        'title': bid_nm,
                        'notice_instt': item.findtext('ntceInsttNm') or item.findtext('rlSndInsttNm') or '-',
                        'raw_price': price_val,
                        'notice_dt': format_datetime_str(item.findtext('bidNtceDt', '-')),
                        'expl_info': format_datetime_str(item.findtext('dcmtgOprtnDt') or item.findtext('bidExplnDt', '-')),
                        'reg_close_dt': format_datetime_str(item.findtext('bidQlfctRgstDt') or item.findtext('cprtnRgstClseDt') or '-'),
                        'bid_close_dt': format_datetime_str(item.findtext('bidClseDt') or item.findtext('proposalClseDt') or '-'),
                        'open_dt': format_datetime_str(item.findtext('opengDt') or '-'),
                        'url': item.findtext('bidNtceDtlUrl', ''),
                        'attachments': extract_attachments(item),
                        'chg_rsn': item.findtext('chgNtceRsn', '')
                    })

            if len(items) < int(num_of_rows) or (total_count and page_no * int(num_of_rows) >= total_count):
                break
            page_no += 1

    # 2. 발주계획 API[cite: 4]
    print("\n[2] 발주계획 API 조회 중...")
    plan_endpoints = [
        ("용역", "http://apis.data.go.kr/1230000/ao/OrderPlanSttusService/getOrderPlanSttusListServc"),
        ("공사", "http://apis.data.go.kr/1230000/ao/OrderPlanSttusService/getOrderPlanSttusListCnstwk")
    ]

    for category_name, base_url in plan_endpoints:
        params = {
            "inqryDiv": "1",
            "orderBgnYm": order_bgn_ym,
            "orderEndYm": order_end_ym,
            "inqryBgnDt": inqryBgnDate12,
            "inqryEndDt": today_str12,
            "numOfRows": "500"
        }
        
        root = fetch_api_data(base_url, params)
        items = root.findall(".//item") if root is not None else []
        print(f"  -> [{category_name}] 발주계획 조회 성공! (수집 건수: {len(items)}건)")

        for item in items:
            biz_nm = item.findtext('bizNm') or item.findtext('orderPlanNm') or item.findtext('pblancNm') or '-'

            if any(ex in biz_nm for ex in EXCLUDE_KEYWORDS):
                continue

            has_p1_kw = any(k in biz_nm for k in P1_KEYWORDS)
            has_p2_kw = any(k in biz_nm for k in P2_KEYWORDS)

            if not (has_p1_kw or has_p2_kw):
                continue

            sum_order_amt = item.findtext('sumOrderAmt') or item.findtext('totpjtPrce') or item.findtext('orderPrce') or '0'
            try:
                price_val = float(sum_order_amt.replace(',', '').strip())
            except ValueError:
                price_val = 0

            is_p1 = has_p1_kw and price_val >= 500000000
            is_p2 = has_p2_kw

            if is_p1 or is_p2:
                matched_bids.append({
                    'source_type': '발주계획',
                    'title': biz_nm,
                    'notice_instt': item.findtext('orderInsttNm') or item.findtext('rlSndInsttNm') or '-',
                    'raw_price': price_val,
                    'notice_dt': format_datetime_str(item.findtext('nticeDt', '-')),
                    'expl_info': '-',
                    'reg_close_dt': '-',
                    'bid_close_dt': '-',
                    'open_dt': '-',
                    'url': item.findtext('orderPlanDtlUrl', ''),
                    'attachments': [],
                    'chg_rsn': ''
                })

    # 3. 사전규격 API[cite: 4]
    print("\n[3] 사전규격 API 조회 중...")
    bf_spec_endpoints = [
        ("용역", "http://apis.data.go.kr/1230000/ao/HrcspSsstndrdInfoService/getPublicPrcureThngInfoServc"),
        ("공사", "http://apis.data.go.kr/1230000/ao/HrcspSsstndrdInfoService/getPublicPrcureThngInfoCnstwk")
    ]

    for category_name, base_url in bf_spec_endpoints:
        for inqry_div in ["1", "2"]:
            params = {
                "inqryDiv": inqry_div,
                "inqryBgnDt": inqryBgnDate12,
                "inqryEndDt": today_str12,
                "numOfRows": "500"
            }
            
            root = fetch_api_data(base_url, params)
            items = root.findall(".//item") if root is not None else []
            print(f"  -> [{category_name}][모드{inqry_div}] 사전규격 조회 성공! (수집 건수: {len(items)}건)")

            if not items:
                continue

            for item in items:
                product_nm = item.findtext('prdctClsfcNoNm') or item.findtext('ntceNm') or item.findtext('bfSpecNm') or '-'

                if any(ex in product_nm for ex in EXCLUDE_KEYWORDS):
                    continue

                has_p1_kw = any(k in product_nm for k in P1_KEYWORDS)
                has_p2_kw = any(k in product_nm for k in P2_KEYWORDS)

                if not (has_p1_kw or has_p2_kw):
                    continue

                assign_budget = item.findtext('asignBdgtAmt') or item.findtext('presmptPrce') or item.findtext('totpjtPrce') or '0'
                try:
                    price_val = float(assign_budget.replace(',', '').strip())
                except ValueError:
                    price_val = 0

                is_p1 = has_p1_kw and price_val >= 500000000
                is_p2 = has_p2_kw

                if is_p1 or is_p2:
                    matched_bids.append({
                        'source_type': '사전규격',
                        'title': product_nm,
                        'notice_instt': item.findtext('orderInsttNm') or item.findtext('rlSndInsttNm') or '-',
                        'raw_price': price_val,
                        'notice_dt': format_datetime_str(item.findtext('rcptDt') or item.findtext('rgstDt') or item.findtext('nticeDt') or '-'),
                        'expl_info': '-',
                        'reg_close_dt': '-',
                        'bid_close_dt': format_datetime_str(item.findtext('opninRgstClseDt', '-')),
                        'open_dt': '-',
                        'url': '',
                        'attachments': extract_attachments(item),
                        'chg_rsn': ''
                    })

    # 4. 민간입찰공고 API[cite: 4]
    print("\n[4] 민간입찰공고 API 조회 중...")
    private_url = "http://apis.data.go.kr/1230000/ao/PrvtBidNtceService/getPrvtBidPblancListInfoServc"
    
    page_no = 1
    num_of_rows = "100"
    
    while True:
        params = {
            "inqryDiv": "1",
            "inqryBgnDt": inqryBgnDate12,
            "inqryEndDt": today_str12,
            "pageNo": str(page_no),
            "numOfRows": num_of_rows
        }
        
        root = fetch_api_data(private_url, params)
        items = root.findall(".//item") if root is not None else []
        print(f"  -> [민간입찰공고] 페이지 {page_no} 조회 성공! (수집 건수: {len(items)}건)")
        
        if not items:
            break
            
        for item in items:
            title = item.findtext('ntceNm') or item.findtext('pblancNm') or item.findtext('bizNm') or '-'
            
            if any(ex in title for ex in EXCLUDE_KEYWORDS):
                continue
                
            if "설계자" not in title:
                continue
            
            matched_bids.append({
                'source_type': '민간입찰',
                'title': f"(정비사업){title}",
                'notice_instt': item.findtext('ntceInsttNm') or item.findtext('rlSndInsttNm') or '-',
                'raw_price': 0,
                'notice_dt': format_datetime_str(item.findtext('ntceDt', '-')),
                'expl_info': format_datetime_str(item.findtext('sptDscrptDt', '-')),
                'reg_close_dt': '-',
                'bid_close_dt': format_datetime_str(item.findtext('bidClseDt', '-')),
                'open_dt': format_datetime_str(item.findtext('opengDt', '-')),
                'url': '',
                'attachments': extract_attachments(item),
                'chg_rsn': ''
            })
            
        if len(items) < int(num_of_rows):
            break
        page_no += 1

    print(f"\n🎯 키워드 및 금액 조건 필터링 후 최종 수집 건수: {len(matched_bids)}건")
    save_web_dashboard_json(matched_bids)

if __name__ == "__main__":
    check_bids()
