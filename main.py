def save_web_dashboard_json(new_items):
    existing_items_map = {}
    if os.path.exists(WEB_JSON_FILE):
        try:
            with open(WEB_JSON_FILE, "r", encoding="utf-8") as f:
                content = json.load(f)
                # 형식이 리스트인 경우 딕셔너리로 감싸서 관리하도록 개선
                old_data = content.get("notices", []) if isinstance(content, dict) else content
                if isinstance(old_data, list):
                    for old_item in old_data:
                        if "id" in old_item:
                            existing_items_map[old_item["id"]] = old_item
        except Exception:
            pass

    combined_map = {}
    for item in existing_items_map.values():
        key = f"{item.get('ntceKindNm')}_{item.get('ntceNm')}"
        combined_map[key] = item

    for idx, item in enumerate(new_items, 1):
        key = f"{item.get('source_type')}_{item.get('title')}"
        
        is_hidden = False
        comments = []
        is_important = False
        is_checked = False
        item_id = f"AUTO_{idx:03d}"

        if key in combined_map:
            item_id = combined_map[key]["id"]
            is_hidden = combined_map[key].get("isHidden", False)
            comments = combined_map[key].get("comments", [])
            is_important = combined_map[key].get("isImportant", False)
            is_checked = combined_map[key].get("isChecked", False)

        combined_map[key] = {
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
        }

    final_output = {
        "last_updated": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
        "status": "success",
        "notices": list(combined_map.values())
    }

    try:
        with open(WEB_JSON_FILE, "w", encoding="utf-8") as f:
            json.dump(final_output, f, ensure_ascii=False, indent=4)
        
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
