import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from urllib.parse import unquote, quote
import requests
import xml.etree.ElementTree as ET

sys.stdout.reconfigure(line_buffering=True)

KST = timezone(timedelta(hours=9))
now = datetime.now(KST)

past_7_days = now - timedelta(days=7)
inqryBgnDt14 = past_7_days.strftime("%Y%m%d%H%M00")
inqryEndDt14 = now.strftime("%Y%m%d%H%M59")

inqryBgnDate12 = past_7_days.strftime("%Y%m%d0000")
today_str12 = now.strftime("%Y%m%d2359")

order_bgn_ym = past_7_days.strftime("%Y%m")
order_end_ym = f"{now.year + 1}{now.month:02d}"

RAW_SERVICE_KEY = unquote(unquote(os.environ.get("SERVICE_KEY", "").strip()))
WEB_JSON_FILE = "notices.json"

P1_KEYWORDS = ["설계", "건립", "신축", "개발"]
P2_KEYWORDS = ["타당성", "마스터", "기본계획", "기본구상", "공모관리", "공모 관리"]
EXCLUDE_KEYWORDS = ["건설사업관리용역", "폐기물", "감리자", "내진보강", "00부대"]

def fetch_api_data(base_url, query_params):
    if not RAW_SERVICE_KEY:
        return None
    try:
        encoded_key = quote(RAW_SERVICE_KEY, safe='')
        query_str = "&".join([f"{k}={v}" for k, v in query_params.items()])
        full_url = f"{base_url}?{query_str}&ServiceKey={encoded_key}"
        response = requests.get(full_url, timeout=15)
        if response.status_code != 200:
            return None
        if "<errMsg>" in response.text or "<returnAuthMsg>" in response.text or "SERVICE ERROR" in response.text:
            return None
        return ET.fromstring(response.text)
    except Exception:
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
            name = info['name'] if info['name'] else f"첨부문서 {idx}"
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
            "demandInstt": item.get('demand_instt', '-'),
            "price": item.get('price_str', '미기재'),
            "raw_price": item.get('raw_price', 0),
            "dateNotice": item.get('notice_dt', '-'),
            "dateBrief": item.get('expl_info', '-'),
            "dateReg": item.get('reg_close_dt', '-'),
            "dateLimit": item.get('bid_close_dt', '-'),
            "dateOpen": item.get('open_dt', '-'),
            "orderPeriod": item.get('order_period', '-'),
            "opninCloseDt": item.get('opnin_close_dt', '-'),
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
        
        if os.environ.get("GITHUB_ACTIONS") == "true":
            subprocess.run(["git", "config", "--global", "user.name", "github-actions[bot]"], check=True)
            subprocess.run(["git", "config", "--global", "user.email", "github-actions[bot]@users.noreply.github.com"], check=True)
            subprocess.run(["git", "add", WEB_JSON_FILE], check=True)
            status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
            if status.stdout.strip():
                subprocess.run(["git", "commit", "-m", "Auto-update notices.json via bot [skip ci]"], check=True)
                subprocess.run(["git", "push"], check=True)
    except Exception as e:
        print(f"Error: {e}")

def check_bids():
    matched_bids = []

    # 1. 본공고
    bid_endpoints = [
        ("용역", "http://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServc"),
        ("공사", "http://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoCnstwk")
    ]
    for category_name, base_url in bid_endpoints:
        page_no = 1
        while page_no <= 2:
            params = {"inqryDiv": "1", "inqryBgnDt": inqryBgnDt14, "inqryEndDt": inqryEndDt14, "pageNo": str(page_no), "numOfRows": "50"}
            root = fetch_api_data(base_url, params)
            items = root.findall(".//item") if root is not None else []
            if not items and page_no == 1:
                params["inqryBgnDt"] = inqryBgnDate12
                params["inqryEndDt"] = today_str12
                root = fetch_api_data(base_url, params)
                items = root.findall(".//item") if root is not None else []
            if not items:
                break
            for item in items:
                bid_nm = item.findtext('bidNtceNm') or '-'
                if any(ex in bid_nm for ex in EXCLUDE_KEYWORDS):
                    continue
                has_p1 = any(k in bid_nm for k in P1_KEYWORDS)
                has_p2 = any(k in bid_nm for k in P2_KEYWORDS)
                if not (has_p1 or has_p2):
                    continue
                presmpt_prce = item.findtext('presmptPrce') or item.findtext('asignBdgAmt') or item.findtext('estmAmt') or item.findtext('totpjtPrce') or '0'
                try:
                    price_val = float(presmpt_prce.replace(',', '').strip())
                    price_str = f"{int(price_val):,}원(VAT별도)" if price_val > 0 else "미기재"
                except ValueError:
                    price_val = 0
                    price_str = "미기재"

                if (has_p1 and price_val >= 500000000) or has_p2:
                    matched_bids.append({
                        'source_type': '본공고',
                        'title': f"(본공고) {bid_nm}",
                        'notice_instt': item.findtext('ntceInsttNm') or item.findtext('rlSndInsttNm') or '-',
                        'demand_instt': item.findtext('dminsttNm', '-'),
                        'raw_price': price_val,
                        'price_str': price_str,
                        'notice_dt': format_datetime_str(item.findtext('bidNtceDt', '-')),
                        'expl_info': format_datetime_str(item.findtext('dcmtgOprtnDt') or item.findtext('bidExplnDt', '-')),
                        'reg_close_dt': format_datetime_str(item.findtext('bidQlfctRgstDt') or item.findtext('cprtnRgstClseDt', '-')),
                        'bid_close_dt': format_datetime_str(item.findtext('bidClseDt') or item.findtext('proposalClseDt', '-')),
                        'open_dt': format_datetime_str(item.findtext('opengDt', '-')),
                        'url': item.findtext('bidNtceDtlUrl', ''),
                        'attachments': extract_attachments(item),
                        'chg_rsn': item.findtext('chgNtceRsn', '')
                    })
            page_no += 1

    # 2. 발주계획
    plan_endpoints = [
        ("용역", "http://apis.data.go.kr/1230000/ao/OrderPlanSttusService/getOrderPlanSttusListServc"),
        ("공사", "http://apis.data.go.kr/1230000/ao/OrderPlanSttusService/getOrderPlanSttusListCnstwk")
    ]
    for category_name, base_url in plan_endpoints:
        params = {"inqryDiv": "1", "orderBgnYm": order_bgn_ym, "orderEndYm": order_end_ym, "inqryBgnDt": inqryBgnDate12, "inqryEndDt": today_str12, "numOfRows": "200"}
        root = fetch_api_data(base_url, params)
        items = root.findall(".//item") if root is not None else []
        for item in items:
            biz_nm = item.findtext('bizNm') or item.findtext('orderPlanNm') or item.findtext('pblancNm') or '-'
            if any(ex in biz_nm for ex in EXCLUDE_KEYWORDS):
                continue
            has_p1 = any(k in biz_nm for k in P1_KEYWORDS)
            has_p2 = any(k in biz_nm for k in P2_KEYWORDS)
            if not (has_p1 or has_p2):
                continue
            sum_order_amt = item.findtext('sumOrderAmt') or item.findtext('totpjtPrce') or item.findtext('orderPrce') or '0'
            try:
                price_val = float(sum_order_amt.replace(',', '').strip())
                price_str = f"{int(price_val):,}원" if price_val > 0 else "미기재"
            except ValueError:
                price_val = 0
                price_str = "미기재"

            if (has_p1 and price_val >= 500000000) or has_p2:
                order_year = item.findtext('orderYear', '')
                order_mnth = item.findtext('orderMnth', '')
                order_period = f"{order_year}년 {order_mnth}월" if (order_year or order_mnth) else "-"
                matched_bids.append({
                    'source_type': '발주계획',
                    'title': f"(계획) {biz_nm}",
                    'notice_instt': item.findtext('orderInsttNm') or item.findtext('rlSndInsttNm') or '-',
                    'demand_instt': '-',
                    'raw_price': price_val,
                    'price_str': price_str,
                    'notice_dt': format_datetime_str(item.findtext('nticeDt', '-')),
                    'expl_info': '-',
                    'reg_close_dt': '-',
                    'bid_close_dt': '-',
                    'open_dt': '-',
                    'order_period': order_period,
                    'url': item.findtext('orderPlanDtlUrl', ''),
                    'attachments': [],
                    'chg_rsn': ''
                })

    # 3. 사전규격
    bf_spec_endpoints = [
        ("용역", "http://apis.data.go.kr/1230000/ao/HrcspSsstndrdInfoService/getPublicPrcureThngInfoServc"),
        ("공사", "http://apis.data.go.kr/1230000/ao/HrcspSsstndrdInfoService/getPublicPrcureThngInfoCnstwk")
    ]
    for category_name, base_url in bf_spec_endpoints:
        for inqry_div in ["1", "2"]:
            params = {"inqryDiv": inqry_div, "inqryBgnDt": inqryBgnDate12, "inqryEndDt": today_str12, "numOfRows": "200"}
            root = fetch_api_data(base_url, params)
            items = root.findall(".//item") if root is not None else []
            for item in items:
                product_nm = item.findtext('prdctClsfcNoNm') or item.findtext('ntceNm') or item.findtext('bfSpecNm') or '-'
                if any(ex in product_nm for ex in EXCLUDE_KEYWORDS):
                    continue
                has_p1 = any(k in product_nm for k in P1_KEYWORDS)
                has_p2 = any(k in product_nm for k in P2_KEYWORDS)
                if not (has_p1 or has_p2):
                    continue
                assign_budget = item.findtext('asignBdgtAmt') or item.findtext('presmptPrce') or item.findtext('totpjtPrce') or '0'
                try:
                    price_val = float(assign_budget.replace(',', '').strip())
                    price_str = f"{int(price_val):,}원" if price_val > 0 else "미기재"
                except ValueError:
                    price_val = 0
                    price_str = "미기재"

                if (has_p1 and price_val >= 500000000) or has_p2:
                    matched_bids.append({
                        'source_type': '사전규격',
                        'title': f"(사전) {product_nm}",
                        'notice_instt': item.findtext('orderInsttNm') or item.findtext('rlSndInsttNm') or '-',
                        'demand_instt': item.findtext('rlDminsttNm') or '-',
                        'raw_price': price_val,
                        'price_str': price_str,
                        'notice_dt': format_datetime_str(item.findtext('rcptDt') or item.findtext('rgstDt') or item.findtext('nticeDt') or '-'),
                        'expl_info': '-',
                        'reg_close_dt': '-',
                        'bid_close_dt': format_datetime_str(item.findtext('opninRgstClseDt', '-')),
                        'open_dt': '-',
                        'opnin_close_dt': format_datetime_str(item.findtext('opninRgstClseDt', '-')),
                        'url': '',
                        'attachments': extract_attachments(item),
                        'chg_rsn': ''
                    })

    # 4. 민간입찰공고
    private_url = "http://apis.data.go.kr/1230000/ao/PrvtBidNtceService/getPrvtBidPblancListInfoServc"
    page_no = 1
    while page_no <= 2:
        params = {"inqryDiv": "1", "inqryBgnDt": inqryBgnDate12, "inqryEndDt": today_str12, "pageNo": str(page_no), "numOfRows": "50"}
        root = fetch_api_data(private_url, params)
        items = root.findall(".//item") if root is not None else []
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
                'title': f"(정비사업) {title}",
                'notice_instt': item.findtext('ntceInsttNm') or item.findtext('rlSndInsttNm') or '-',
                'demand_instt': '-',
                'raw_price': 0,
                'price_str': '',
                'notice_dt': format_datetime_str(item.findtext('ntceDt', '-')),
                'expl_info': format_datetime_str(item.findtext('sptDscrptDt', '-')),
                'reg_close_dt': '-',
                'bid_close_dt': format_datetime_str(item.findtext('bidClseDt', '-')),
                'open_dt': format_datetime_str(item.findtext('opengDt', '-')),
                'url': '',
                'attachments': extract_attachments(item),
                'chg_rsn': ''
            })
        page_no += 1

    save_web_dashboard_json(matched_bids)

if __name__ == "__main__":
    check_bids()
