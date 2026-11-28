import contextlib
import json
import os
import time

from playwright.sync_api import sync_playwright

BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:5173")
TARGET_URL = f"{BASE_URL}/pm/users/u29"
OUTPUT_DIR = os.path.abspath("test-results")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def boxes_overlap(a, b):
    if not a or not b:
        return False
    return not (
        a["x"] + a["width"] <= b["x"]
        or b["x"] + b["width"] <= a["x"]
        or a["y"] + a["height"] <= b["y"]
        or b["y"] + b["height"] <= a["y"]
    )


def goto_ready(page, url, wait_ms=1200):
    t0 = time.time()
    resp = page.goto(url, wait_until="domcontentloaded", timeout=25000)
    with contextlib.suppress(Exception):
        page.wait_for_load_state("load", timeout=10000)
    page.wait_for_timeout(wait_ms)
    return resp.status if resp else None, round(time.time() - t0, 2)


def run_walkthrough(loops=2):
    report = {
        "target_url": TARGET_URL,
        "viewport": "1440x900 (Desktop) + 1920x1080 check",
        "loops_executed": loops,
        "console_errors": [],
        "page_errors": [],
        "console_warnings": [],
        "failed_requests": [],
        "iterations": [],
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/google-chrome", headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        page.on("console", lambda msg: (
            report["console_errors"].append(msg.text) if msg.type == "error"
            else report["console_warnings"].append(msg.text) if msg.type == "warning"
            else None
        ))
        page.on("pageerror", lambda err: report["page_errors"].append(str(err)))
        page.on("requestfailed", lambda req: report["failed_requests"].append({
            "url": req.url,
            "failure": str(req.failure),
        }))

        for loop_idx in range(1, loops + 1):
            it = {"iteration": loop_idx, "branches": {}}

            # --- Branch 1: Direct entry to /pm/users/u29 (fresh tab for Back button check) ---
            fresh_page = context.new_page()
            fresh_status, fresh_time = goto_ready(fresh_page, TARGET_URL, wait_ms=1000)
            url_before_back = fresh_page.url
            back_btn_fresh = fresh_page.locator(".cvd-pill:has-text('Quay lại'), button:has-text('Quay lại')").first
            if back_btn_fresh.count() > 0:
                back_btn_fresh.click()
                fresh_page.wait_for_timeout(500)
            url_after_direct_back = fresh_page.url
            fresh_page.close()

            it["branches"]["direct_entry_back_button"] = {
                "status": fresh_status,
                "load_s": fresh_time,
                "url_before": url_before_back,
                "url_after_click": url_after_direct_back,
                "stuck_on_same_url": url_before_back == url_after_direct_back,
            }

            # --- Branch 2: Main /pm/users/u29 full walkthrough ---
            status, load_s = goto_ready(page, TARGET_URL, wait_ms=1000)
            scroll_w = page.evaluate("() => document.documentElement.scrollWidth")

            if loop_idx == 1:
                page.screenshot(path=os.path.join(OUTPUT_DIR, "desktop_1440.png"), full_page=True)

            # Check KPI goal label vs Today tooltip bounding-box collision
            goal_box = page.locator(".cvd-daily-goal span").first.bounding_box()
            tooltip_box = page.locator(".cvd-tooltip").first.bounding_box()
            overlap_default = boxes_overlap(goal_box, tooltip_box)

            # Sample hover across first, middle, last bars
            slots = page.locator(".cvd-daily-slot")
            slot_count = slots.count()
            bar_tooltips = []
            for idx in [0, slot_count // 2, max(0, slot_count - 1)]:
                if idx < slot_count:
                    slots.nth(idx).hover()
                    page.wait_for_timeout(150)
                    tt = page.locator(".cvd-tooltip").all_inner_texts()
                    bar_tooltips.append({"bar_index": idx, "tooltip": tt})

            # Walk through ALL tabs in "Chi tiết"
            tab_buttons = page.locator(".cvd-card:has-text('Chi tiết') [role='tab']")
            tab_labels = tab_buttons.all_inner_texts()
            tabs_walked = []
            rework_job_link_nav = None

            for t_i in range(tab_buttons.count()):
                btn = tab_buttons.nth(t_i)
                label = btn.inner_text().strip()
                btn.click()
                page.wait_for_timeout(300)
                active_selected = btn.get_attribute("aria-selected")

                card_text = page.locator(".cvd-card:has-text('Chi tiết')").inner_text()
                tab_info = {
                    "label": label,
                    "aria_selected": active_selected,
                    "content_preview": card_text.replace("\n", " | ")[:220],
                }

                if loop_idx == 1:
                    if "Lý do rework" in label:
                        page.screenshot(path=os.path.join(OUTPUT_DIR, "desktop_tab_rework.png"), full_page=True)
                    elif "Tỉ lệ bị trả lại" in label:
                        page.screenshot(path=os.path.join(OUTPUT_DIR, "desktop_tab_trend.png"), full_page=True)
                    elif "Thống kê QC" in label:
                        page.screenshot(path=os.path.join(OUTPUT_DIR, "desktop_tab_qc.png"), full_page=True)

                # Test sorting on Job tab
                if label.startswith("Job"):
                    sort_headers = page.locator(".cvd-card:has-text('Chi tiết') th.ant-table-column-has-sorters")
                    tab_info["sortable_columns"] = sort_headers.count()
                    if sort_headers.count() > 0:
                        sort_headers.first.click()
                        page.wait_for_timeout(150)
                        sort_headers.first.click()
                        page.wait_for_timeout(150)

                # Test clicking a job link inside "Lý do rework"
                if "Lý do rework" in label:
                    job_links = page.locator(".cvd-card:has-text('Chi tiết') a[href^='/jobs/']")
                    tab_info["rework_job_links_count"] = job_links.count()
                    if job_links.count() > 0:
                        href = job_links.first.get_attribute("href")
                        job_links.first.click()
                        page.wait_for_timeout(600)
                        rework_job_link_nav = {
                            "clicked_href": href,
                            "landed_url": page.url,
                            "job_page_title": page.locator("h1").first.inner_text() if page.locator("h1").count() > 0 else "",
                        }
                        goto_ready(page, TARGET_URL, wait_ms=600)
                        tab_buttons = page.locator(".cvd-card:has-text('Chi tiết') [role='tab']")

                tabs_walked.append(tab_info)

            it["branches"]["u29_main"] = {
                "status": status,
                "load_s": load_s,
                "horizontal_overflow_px": max(0, scroll_w - 1440),
                "kpi_label_overlaps_today_tooltip": overlap_default,
                "goal_box": goal_box,
                "tooltip_box": tooltip_box,
                "bar_slots": slot_count,
                "bar_tooltips_sampled": bar_tooltips,
                "tab_labels": tab_labels,
                "tabs_walked": tabs_walked,
                "rework_job_link_nav": rework_job_link_nav,
            }

            # --- Branch 3: Global Shell (QuickSearch, NotificationBell, Subnav, TopNav) ---
            page.keyboard.press("/")
            page.wait_for_timeout(300)
            qs_input = page.locator(".ant-modal input[aria-label*='Tìm']")
            qs_opened = qs_input.count() > 0 and qs_input.first.is_visible()
            qs_result_count = 0
            if qs_opened:
                qs_input.first.fill("a")
                page.wait_for_timeout(300)
                qs_result_count = page.locator(".cvd-qs-results a").count()
                page.keyboard.press("Escape")
                page.wait_for_timeout(200)

            bell = page.locator(".cvd-noti-trigger").first
            noti_before = bell.get_attribute("aria-label") if bell.count() > 0 else None
            noti_items_count = 0
            noti_after = None
            if bell.count() > 0:
                bell.click()
                page.wait_for_timeout(300)
                noti_items_count = page.locator(".cvd-noti-panel a").count()
                mark_all = page.locator(".cvd-noti-head button:has-text('Đánh dấu đã đọc')")
                if mark_all.count() > 0 and loop_idx == 1:
                    mark_all.click()
                    page.wait_for_timeout(200)
                noti_after = bell.get_attribute("aria-label")
                bell.click()
                page.wait_for_timeout(200)

            nav_results = {}
            for nav_label, selector in [
                ("Subnav Thống kê", "a:has-text('Thống kê')"),
                ("TopNav Hàng đợi", "header a:has-text('Hàng đợi'), nav a:has-text('Hàng đợi')"),
                ("TopNav Audits", "header a:has-text('Audits'), nav a:has-text('Audits')"),
                ("TopNav Tổng quan", "header a:has-text('Tổng quan'), nav a:has-text('Tổng quan')"),
            ]:
                el = page.locator(selector).first
                if el.count() > 0:
                    el.click()
                    page.wait_for_timeout(500)
                    nav_results[nav_label] = {
                        "url": page.url,
                        "h1": page.locator("h1").first.inner_text() if page.locator("h1").count() > 0 else "",
                    }

            it["branches"]["global_shell"] = {
                "quick_search_opened_via_slash": qs_opened,
                "quick_search_results_for_a": qs_result_count,
                "notification_before": noti_before,
                "notification_items": noti_items_count,
                "notification_after": noti_after,
                "nav_transitions": nav_results,
            }

            # --- Branch 4: Navigate /pm -> /pm/users/u29 -> click Back ---
            goto_ready(page, f"{BASE_URL}/pm", wait_ms=600)
            goto_ready(page, TARGET_URL, wait_ms=600)
            back_btn = page.locator(".cvd-pill:has-text('Quay lại'), button:has-text('Quay lại')").first
            back_btn.click()
            page.wait_for_timeout(500)
            it["branches"]["history_back_from_pm"] = {
                "landed_url": page.url,
                "returned_to_pm": page.url.rstrip("/").endswith("/pm"),
            }

            # --- Branch 5: Non-QC Annotator with assigned jobs (/pm/users/u10) ---
            non_qc_url = f"{BASE_URL}/pm/users/u10"
            nqc_status, nqc_time = goto_ready(page, non_qc_url, wait_ms=800)
            nqc_h1 = page.locator("h1").first.inner_text() if page.locator("h1").count() > 0 else ""
            nqc_tabs = page.locator(".cvd-card:has-text('Chi tiết') [role='tab']").all_inner_texts()
            nqc_stats = [t.replace("\n", " | ") for t in page.locator(".cvd-row-stats .cvd-card").all_inner_texts()]
            nqc_rows = page.locator(".cvd-card:has-text('Chi tiết') tbody tr.ant-table-row").count()
            if loop_idx == 1:
                page.screenshot(path=os.path.join(OUTPUT_DIR, "desktop_non_qc_u10.png"), full_page=True)
            nqc_tab_btns = page.locator(".cvd-card:has-text('Chi tiết') [role='tab']")
            for ti in range(nqc_tab_btns.count()):
                nqc_tab_btns.nth(ti).click()
                page.wait_for_timeout(200)

            it["branches"]["non_qc_user_u10"] = {
                "status": nqc_status,
                "load_s": nqc_time,
                "name": nqc_h1,
                "stat_cards": nqc_stats,
                "tabs": nqc_tabs,
                "has_qc_tab": any("QC" in t for t in nqc_tabs),
                "job_rows_count": nqc_rows,
            }

            # --- Branch 6: Invalid user ID (/pm/users/invalid-999) ---
            inv_status, inv_time = goto_ready(page, f"{BASE_URL}/pm/users/invalid-999", wait_ms=600)
            inv_h1 = page.locator("h1").first.inner_text() if page.locator("h1").count() > 0 else ""
            if loop_idx == 1:
                page.screenshot(path=os.path.join(OUTPUT_DIR, "desktop_invalid_user.png"), full_page=True)
            fallback_btn = page.locator(".cvd-pill:has-text('Về tổng quan'), button:has-text('Về tổng quan')").first
            inv_after_click = None
            if fallback_btn.count() > 0:
                fallback_btn.click()
                page.wait_for_timeout(500)
                inv_after_click = page.url

            it["branches"]["invalid_user"] = {
                "status": inv_status,
                "load_s": inv_time,
                "heading": inv_h1,
                "after_click_ve_tong_quan": inv_after_click,
            }

            report["iterations"].append(it)

        # Final 1920x1080 check
        ctx_1920 = browser.new_context(viewport={"width": 1920, "height": 1080})
        p_1920 = ctx_1920.new_page()
        goto_ready(p_1920, TARGET_URL, wait_ms=800)
        sw_1920 = p_1920.evaluate("() => document.documentElement.scrollWidth")
        goal_1920 = p_1920.locator(".cvd-daily-goal span").first.bounding_box()
        tt_1920 = p_1920.locator(".cvd-tooltip").first.bounding_box()
        p_1920.screenshot(path=os.path.join(OUTPUT_DIR, "desktop_1920.png"), full_page=True)
        report["desktop_1920_check"] = {
            "horizontal_overflow_px": max(0, sw_1920 - 1920),
            "kpi_label_overlaps_today_tooltip": boxes_overlap(goal_1920, tt_1920),
        }
        ctx_1920.close()

        context.close()
        browser.close()

    report_path = os.path.join(OUTPUT_DIR, "usability_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    return report


if __name__ == "__main__":
    res = run_walkthrough(loops=2)
    print("WALKTHROUGH_DONE")
    print(json.dumps(res, indent=2, ensure_ascii=False))
