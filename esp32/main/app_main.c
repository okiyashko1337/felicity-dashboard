#include <string.h>
#include <stdlib.h>
#include <time.h>

#include "esp_log.h"
#include "esp_app_desc.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "nvs_flash.h"
#include "sdkconfig.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "dashboard_data.h"
#include "device_update.h"
#include "device_settings.h"
#include "nextion.h"
#include "setup_ui.h"
#include "wifi_manager.h"
#include "wifi_setup.h"

static const char *TAG = "felicity";
static char ha_app_version[24];

static void render_local_settings(bool ha_live, const char *status,
                                  unsigned page)
{
    wifi_diagnostics_t wifi;
    char ha_host[FELICITY_HA_HOST_MAX];
    device_time_settings_t time_settings;
    wifi_manager_get_diagnostics(&wifi);
    device_settings_load_ha_host(ha_host, sizeof(ha_host));
    device_settings_load_time(&time_settings);
    setup_ui_render_local_settings(&wifi, ha_host, ha_live, status, page,
                                   &time_settings, ha_app_version,
                                   esp_app_get_description()->version,
                                   (uint32_t)(esp_timer_get_time() / 1000000));
}

void app_main(void)
{
    esp_err_t nvs_result = nvs_flash_init();
    if (nvs_result == ESP_ERR_NVS_NO_FREE_PAGES ||
        nvs_result == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        nvs_result = nvs_flash_init();
    }
    ESP_ERROR_CHECK(nvs_result);
    bool pending_ota = device_update_running_app_pending();
    device_time_settings_t startup_time_settings;
    device_settings_load_time(&startup_time_settings);
    device_settings_apply_time(&startup_time_settings);
    nextion_init();
    dashboard_page_t page = DASH_PAGE_HOME;
    dashboard_page_t setup_return_page = DASH_PAGE_HOME;
    /* Chart buffers are several kilobytes each. Keeping them on app_main's
     * task stack leaves almost no guard margin and eventually trips stack
     * protection as the snapshot grows. They have application lifetime, so
     * BSS is the correct storage. */
    static dashboard_snapshot_t snapshot;
    static dashboard_summary_t summary;
    static dashboard_chart_t chart;
    static dashboard_gaps_t gaps;
    char api_base_url[FELICITY_API_URL_MAX] = CONFIG_FELICITY_API_BASE_URL;
    char current_status[48] = "STARTING";
    bool current_live = false;
    unsigned local_setup_page = 0;
    bool gaps_live = false;
    nextion_show_page(page);

#if CONFIG_FELICITY_EMULATOR
    dashboard_sample_snapshot(&snapshot);
    dashboard_sample_summary(&summary);
    ESP_LOGI(TAG, "ESP32-C3 emulator mode; using deterministic Raspberry sample");
#else
    wifi_setup_run(api_base_url, sizeof(api_base_url));
    ESP_LOGI(TAG, "Wi-Fi connected; dashboard API: %s", api_base_url);
    /* NVS, Nextion UART and Wi-Fi have now all passed their boot diagnostics.
     * Confirm only here so a broken OTA image is eligible for rollback. */
    if (pending_ota) device_update_confirm_running_app();
    current_live = api_base_url[0] &&
                   dashboard_fetch_current(api_base_url, &snapshot);
    if (!current_live) {
        ESP_LOGW(TAG, "Dashboard data unavailable; requesting Home Assistant address");
        wifi_setup_configure_ha(api_base_url, sizeof(api_base_url));
        ESP_LOGI(TAG, "Dashboard API changed to: %s", api_base_url);
        current_live = api_base_url[0] &&
                       dashboard_fetch_current(api_base_url, &snapshot);
    }
    snprintf(current_status, sizeof(current_status), "%s",
             current_live ? "HA DATA OK" : "HA REQUEST FAILED");
    if (api_base_url[0]) device_update_confirm_with_server(api_base_url);
    if (api_base_url[0]) {
        dashboard_fetch_app_version(api_base_url, ha_app_version,
                                    sizeof(ha_app_version));
    }
#endif

    /* Present the first complete dashboard frame atomically. The setup flow
     * may have used the same physical HMI page for its own UI. */
    nextion_command("ref_stop");
    nextion_show_page(DASH_PAGE_HOME);
    nextion_render_home(&snapshot, &summary, current_live);
    nextion_render_clock();
    nextion_command("ref_star");

    TickType_t next_poll = 0;
    TickType_t next_summary = 0;
    TickType_t next_chart = 0;
    TickType_t next_clock = 0;
    TickType_t next_update = 0;
    bool summary_live = false;
#if CONFIG_FELICITY_EMULATOR
    TickType_t next_demo_page = pdMS_TO_TICKS(5000);
#endif
    while (true) {
        TickType_t now = xTaskGetTickCount();
        if (now >= next_update) {
#if !CONFIG_FELICITY_EMULATOR
            device_update_request_t update = {0};
            if (device_update_poll(api_base_url, &update)) {
                ESP_LOGI(TAG, "Applying %s update %s",
                         update.target == DEVICE_UPDATE_ESP32 ? "ESP32" : "Nextion",
                         update.version);
                device_update_apply(api_base_url, &update);
                nextion_command("page home");
                nextion_render_home(&snapshot, &summary, current_live);
            }
#endif
            next_update = now + pdMS_TO_TICKS(15000);
        }
        if (now >= next_clock) {
            if (page == DASH_PAGE_SETUP && local_setup_page == 1) {
                setup_ui_render_time_value();
            } else if (page != DASH_PAGE_SETUP) {
                nextion_render_clock();
            }
            next_clock = now + pdMS_TO_TICKS(1000);
        }
#if CONFIG_FELICITY_EMULATOR
        if (now >= next_demo_page) {
            page = page >= DASH_PAGE_GAPS ? DASH_PAGE_HOME : (dashboard_page_t)(page + 1);
            ESP_LOGI(TAG, "Demo navigation: %s", touch_page_name(page));
            nextion_show_page(page);
            next_poll = 0;
            next_chart = 0;
            next_demo_page = now + pdMS_TO_TICKS(5000);
        }
#endif
        touch_event_t touch;
        if (nextion_read_touch_event(&touch)) {
            if (page == DASH_PAGE_SETUP) {
                setup_ui_local_settings_touch_feedback(touch.x, touch.y,
                                                       touch.pressed,
                                                       local_setup_page);
                if (!touch.pressed) {
                    local_setup_action_t action = setup_ui_local_settings_hit(
                        touch.x, touch.y, local_setup_page);
                    if (action == LOCAL_SETUP_ACTION_BACK) {
                        page = setup_return_page;
                        nextion_command("ref_stop");
                        nextion_show_page(page);
                        if (page == DASH_PAGE_SYSTEM) {
                            nextion_render_detail(page, &snapshot, &summary,
                                                  summary_live);
                        } else {
                            nextion_render_home(&snapshot, &summary,
                                                current_live);
                        }
                        nextion_render_clock();
                        nextion_command("ref_star");
                        next_poll = now + pdMS_TO_TICKS(2000);
                        next_chart = 0;
                    } else if (action == LOCAL_SETUP_ACTION_WIFI) {
                        snprintf(current_status, sizeof(current_status),
                                 "OPENING WI-FI SETUP");
                        render_local_settings(current_live, current_status,
                                              local_setup_page);
                        vTaskDelay(pdMS_TO_TICKS(250));
                        wifi_manager_request_setup_and_restart();
                    } else if (action == LOCAL_SETUP_ACTION_HA) {
                        wifi_setup_configure_ha(api_base_url,
                                                sizeof(api_base_url));
                        current_live = dashboard_fetch_current(api_base_url,
                                                               &snapshot);
                        dashboard_fetch_app_version(api_base_url,
                                                    ha_app_version,
                                                    sizeof(ha_app_version));
                        snprintf(current_status, sizeof(current_status), "%s",
                                 current_live ? "HA DATA OK" : "HA REQUEST FAILED");
                        page = DASH_PAGE_SETUP;
                        render_local_settings(current_live, current_status,
                                              local_setup_page);
                        next_poll = now + pdMS_TO_TICKS(2000);
                    } else if (action == LOCAL_SETUP_ACTION_RETRY) {
                        snprintf(current_status, sizeof(current_status),
                                 "CONTACTING HA...");
                        char ha_host[FELICITY_HA_HOST_MAX];
                        device_settings_load_ha_host(ha_host, sizeof(ha_host));
                        bool address_ready = device_settings_prepare_api_url(
                            ha_host, api_base_url, sizeof(api_base_url));
                        current_live = address_ready && dashboard_fetch_current(
                            api_base_url, &snapshot);
                        if (address_ready) {
                            dashboard_fetch_app_version(api_base_url,
                                                        ha_app_version,
                                                        sizeof(ha_app_version));
                        }
                        snprintf(current_status, sizeof(current_status), "%s",
                                 current_live ? "HA DATA OK" : "HA REQUEST FAILED");
                        render_local_settings(current_live, current_status,
                                              local_setup_page);
                        next_poll = now + pdMS_TO_TICKS(2000);
                    } else if (action == LOCAL_SETUP_ACTION_DOWN) {
                        if (local_setup_page < 2) local_setup_page++;
                        render_local_settings(current_live, current_status,
                                              local_setup_page);
                    } else if (action == LOCAL_SETUP_ACTION_UP) {
                        if (local_setup_page > 0) local_setup_page--;
                        render_local_settings(current_live, current_status,
                                              local_setup_page);
                    } else if (action == LOCAL_SETUP_ACTION_NAV_NETWORK ||
                               action == LOCAL_SETUP_ACTION_NAV_TIME ||
                               action == LOCAL_SETUP_ACTION_NAV_RESET) {
                        local_setup_page = action == LOCAL_SETUP_ACTION_NAV_NETWORK
                                               ? 0
                                           : action == LOCAL_SETUP_ACTION_NAV_TIME
                                               ? 1
                                               : 2;
                        render_local_settings(current_live, current_status,
                                              local_setup_page);
                    } else if (action == LOCAL_SETUP_ACTION_RESET) {
                        local_setup_page = 3;
                        render_local_settings(current_live, current_status,
                                              local_setup_page);
                    } else if (action == LOCAL_SETUP_ACTION_RESET_CANCEL) {
                        local_setup_page = 2;
                        render_local_settings(current_live, current_status,
                                              local_setup_page);
                    } else if (action == LOCAL_SETUP_ACTION_RESET_CONFIRM) {
                        bool settings_reset = device_settings_factory_reset();
                        bool wifi_reset = wifi_manager_factory_reset();
                        bool reset_ok = settings_reset && wifi_reset;
                        setup_ui_render_factory_reset_result(reset_ok);
                        if (reset_ok) {
                            vTaskDelay(pdMS_TO_TICKS(800));
                            esp_restart();
                        }
                        vTaskDelay(pdMS_TO_TICKS(1200));
                        render_local_settings(current_live, "RESET FAILED",
                                              local_setup_page);
                    } else if (action == LOCAL_SETUP_ACTION_TIME_MINUS ||
                               action == LOCAL_SETUP_ACTION_TIME_PLUS ||
                               action == LOCAL_SETUP_ACTION_TIME_DST) {
                        device_time_settings_t settings;
                        device_settings_load_time(&settings);
                        if (action == LOCAL_SETUP_ACTION_TIME_MINUS &&
                            settings.offset_minutes > -720) {
                            settings.offset_minutes -= 30;
                        } else if (action == LOCAL_SETUP_ACTION_TIME_PLUS &&
                                   settings.offset_minutes < 840) {
                            settings.offset_minutes += 30;
                        } else if (action == LOCAL_SETUP_ACTION_TIME_DST) {
                            settings.european_dst = !settings.european_dst;
                        }
                        device_settings_save_time(&settings);
                        device_settings_apply_time(&settings);
                        render_local_settings(current_live, "TIME SAVED",
                                              local_setup_page);
                    }
                }
            } else {
                dashboard_page_t source_page = page;
                dashboard_page_t target = touch_page_for_coordinates(
                    page, touch.x, touch.y);
                if (page == DASH_PAGE_SYSTEM && touch.x >= 360 &&
                    touch.y >= 44 && touch.y < 110) {
                    nextion_command("draw 374,54,464,97,%d",
                                    touch.pressed ? 65535 : 2016);
                }
                if (!touch.pressed && target != page) {
                    page = target;
                    ESP_LOGI(TAG, "Touch navigation: %s", touch_page_name(page));
                    if (page == DASH_PAGE_SETUP) {
                        setup_return_page = source_page == DASH_PAGE_SYSTEM
                                                ? DASH_PAGE_SYSTEM
                                                : DASH_PAGE_HOME;
                        nextion_show_page(page);
                        local_setup_page = 0;
                        render_local_settings(current_live, current_status,
                                              local_setup_page);
                    } else {
                        nextion_command("ref_stop");
                        nextion_show_page(page);
                        if (page == DASH_PAGE_HOME) {
                            nextion_render_home(&snapshot, &summary,
                                                current_live);
                        } else if (page == DASH_PAGE_GAPS) {
                            nextion_render_gaps(&gaps, gaps_live);
                        } else {
                            nextion_render_detail(
                                page, &snapshot, &summary,
                                (page == DASH_PAGE_SYSTEM ||
                                 page == DASH_PAGE_TODAY)
                                    ? summary_live
                                    : current_live);
                        }
                        nextion_render_clock();
                        nextion_command("ref_star");
                    }
                    next_poll = now + pdMS_TO_TICKS(2000);
                    next_chart = 0;
                }
            }
        }
        if (now >= next_summary) {
#if CONFIG_FELICITY_EMULATOR
            dashboard_sample_summary(&summary);
            summary_live = true;
#else
            summary_live = dashboard_fetch_summary(api_base_url, &summary);
#endif
            if (page == DASH_PAGE_HOME || page == DASH_PAGE_SYSTEM || page == DASH_PAGE_TODAY) {
                next_poll = 0;
            }
            next_summary = now + pdMS_TO_TICKS(60000);
        }
        if (now >= next_poll) {
            if (page == DASH_PAGE_SETUP) {
                /* Static page: refresh individual fields only. Full-screen
                 * redraws make the Nextion visibly flash. */
                next_poll = now + pdMS_TO_TICKS(1000);
            } else if (page == DASH_PAGE_GAPS) {
                nextion_render_gaps_values(&gaps, gaps_live);
                next_poll = now + pdMS_TO_TICKS(2000);
            } else if (page == DASH_PAGE_SYSTEM || page == DASH_PAGE_TODAY) {
                nextion_render_detail_values(page, &snapshot, &summary,
                                             summary_live);
                next_poll = now + pdMS_TO_TICKS(2000);
            } else {
#if CONFIG_FELICITY_EMULATOR
                bool live = true;
#else
                bool live = api_base_url[0] &&
                            dashboard_fetch_current(api_base_url, &snapshot);
#endif
                current_live = live;
                snprintf(current_status, sizeof(current_status), "%s",
                         live ? "HA DATA OK" : "HA REQUEST FAILED");
                if (page == DASH_PAGE_HOME) {
                    nextion_render_home_values(&snapshot, &summary, live);
                }
                else nextion_render_detail_values(page, &snapshot, &summary,
                                                  live);
                next_poll = now + pdMS_TO_TICKS(2000);
            }
        }
        if (page >= DASH_PAGE_PV && page <= DASH_PAGE_GAPS && now >= next_chart) {
            if (page == DASH_PAGE_GAPS) {
#if CONFIG_FELICITY_EMULATOR
                dashboard_sample_gaps(&gaps);
                gaps_live = true;
#else
                gaps_live = dashboard_fetch_gaps(api_base_url, &gaps);
#endif
                if (gaps_live) {
                    nextion_command("ref_stop");
                    nextion_show_page(page);
                    nextion_render_gaps(&gaps, gaps_live);
                    nextion_render_clock();
                    nextion_command("ref_star");
                    nextion_render_chart(page, &gaps.chart);
                }
                next_chart = now + pdMS_TO_TICKS(60000);
                vTaskDelay(pdMS_TO_TICKS(20));
                continue;
            }
            const char *metric = touch_page_name(page);
#if CONFIG_FELICITY_EMULATOR
            dashboard_sample_chart(metric, &chart);
            bool chart_ok = true;
#else
            bool chart_ok = dashboard_fetch_chart(api_base_url, metric, &chart);
#endif
                if (chart_ok) {
                    /* Atomically reveal a clean HMI canvas and stable header,
                     * then replay only the trace with screen refresh enabled. */
                    nextion_command("ref_stop");
                    nextion_show_page(page);
                    nextion_render_detail(page, &snapshot, &summary,
                                           page == DASH_PAGE_SYSTEM ? summary_live
                                                                    : current_live);
                    nextion_render_clock();
                    nextion_command("ref_star");
                    nextion_render_chart(page, &chart);
                }
            next_chart = now + pdMS_TO_TICKS(page == DASH_PAGE_SYSTEM ? 10000 : 60000);
        }
        vTaskDelay(pdMS_TO_TICKS(20));
    }
}
