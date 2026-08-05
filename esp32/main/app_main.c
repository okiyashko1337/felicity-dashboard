#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "esp_event.h"
#include "driver/gpio.h"
#include "esp_eth.h"
#include "esp_eth_mac_openeth.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_netif_sntp.h"
#include "esp_wifi.h"
#include "apps/esp_sntp.h"
#include "nvs_flash.h"
#include "sdkconfig.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"

#include "dashboard_data.h"
#include "device_settings.h"
#include "nextion.h"
#include "wifi_provisioning.h"

static const char *TAG = "felicity";
#if CONFIG_FELICITY_EMULATOR && !CONFIG_FELICITY_EMULATOR_LIVE_API
#define FELICITY_DEMO_MODE 1
#else
#define FELICITY_DEMO_MODE 0
#endif

#if !CONFIG_FELICITY_EMULATOR
static void time_sync_notification(struct timeval *time_value)
{
    (void)time_value;
    ESP_LOGI(TAG, "Local clock synchronized");
}

static void clock_init(void)
{
    setenv("TZ", CONFIG_FELICITY_TIMEZONE, 1);
    tzset();
    esp_sntp_config_t config =
        ESP_NETIF_SNTP_DEFAULT_CONFIG(CONFIG_FELICITY_SNTP_SERVER);
    config.smooth_sync = true;
    config.sync_cb = time_sync_notification;
    ESP_ERROR_CHECK(esp_netif_sntp_init(&config));
    /* The system clock ticks locally; network correction is deliberately
       infrequent and never touches the Raspberry API. */
    esp_sntp_set_sync_interval(6U * 60U * 60U * 1000U);
}
#endif

#if !CONFIG_FELICITY_EMULATOR
static EventGroupHandle_t wifi_events;
static device_settings_t wifi_settings;
static const int WIFI_STARTED = BIT0;
static const int CONNECTED = BIT1;
static const int WIFI_ATTEMPT_FAILED = BIT2;

#define WIFI_MAX_CANDIDATES 12
#define WIFI_CONNECT_TIMEOUT_MS 12000
#define WIFI_RESCAN_DELAY_MIN_MS 5000
#define WIFI_RESCAN_DELAY_MAX_MS 60000
#define SETUP_BUTTON_HOLD_MS 3000

static void setup_button_task(void *arg)
{
    (void)arg;
    const gpio_num_t button = (gpio_num_t)CONFIG_FELICITY_SETUP_BUTTON_GPIO;
    gpio_config_t config = {
        .pin_bit_mask = 1ULL << button,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&config));

    while (true) {
        if (gpio_get_level(button) != 0) {
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }
        TickType_t pressed_at = xTaskGetTickCount();
        while (gpio_get_level(button) == 0 &&
               xTaskGetTickCount() - pressed_at < pdMS_TO_TICKS(SETUP_BUTTON_HOLD_MS)) {
            vTaskDelay(pdMS_TO_TICKS(50));
        }
        if (gpio_get_level(button) != 0 ||
            xTaskGetTickCount() - pressed_at < pdMS_TO_TICKS(SETUP_BUTTON_HOLD_MS)) {
            continue;
        }

        ESP_LOGW(TAG, "BOOT held for 3 seconds; release it to enter setup mode");
        while (gpio_get_level(button) == 0) vTaskDelay(pdMS_TO_TICKS(50));
        if (!device_settings_clear()) {
            ESP_LOGE(TAG, "Could not clear Felicity network settings");
            vTaskDelay(pdMS_TO_TICKS(1000));
            continue;
        }
        ESP_LOGW(TAG, "Felicity network settings cleared; restarting into setup AP");
        vTaskDelay(pdMS_TO_TICKS(250));
        esp_restart();
    }
}

static void setup_button_init(void)
{
    ESP_ERROR_CHECK(xTaskCreate(setup_button_task, "setup_button", 2048,
                                NULL, 5, NULL) == pdPASS ? ESP_OK : ESP_ERR_NO_MEM);
}

static const char *wifi_auth_name(wifi_auth_mode_t mode)
{
    switch (mode) {
    case WIFI_AUTH_OPEN: return "OPEN";
    case WIFI_AUTH_WEP: return "WEP";
    case WIFI_AUTH_WPA_PSK: return "WPA-PSK";
    case WIFI_AUTH_WPA2_PSK: return "WPA2-PSK";
    case WIFI_AUTH_WPA_WPA2_PSK: return "WPA/WPA2-PSK";
    case WIFI_AUTH_ENTERPRISE: return "ENTERPRISE";
    case WIFI_AUTH_WPA3_PSK: return "WPA3-PSK";
    case WIFI_AUTH_WPA2_WPA3_PSK: return "WPA2/WPA3-PSK";
    case WIFI_AUTH_WAPI_PSK: return "WAPI-PSK";
    case WIFI_AUTH_OWE: return "OWE";
    default: return "OTHER";
    }
}

static void wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        xEventGroupSetBits(wifi_events, WIFI_STARTED);
    }
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        const wifi_event_sta_disconnected_t *event = data;
        ESP_LOGW(TAG,
                 "Wi-Fi disconnected: reason=%u, RSSI=%d dBm, BSSID="
                 "%02x:%02x:%02x:%02x:%02x:%02x",
                 event ? event->reason : 0,
                 event ? event->rssi : 0,
                 event ? event->bssid[0] : 0,
                 event ? event->bssid[1] : 0,
                 event ? event->bssid[2] : 0,
                 event ? event->bssid[3] : 0,
                 event ? event->bssid[4] : 0,
                 event ? event->bssid[5] : 0);
        xEventGroupClearBits(wifi_events, CONNECTED);
        xEventGroupSetBits(wifi_events, WIFI_ATTEMPT_FAILED);
    }
    if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) xEventGroupSetBits(wifi_events, CONNECTED);
}

static void wifi_configure_network(void)
{
    wifi_config_t config = {0};
    memcpy(config.sta.ssid, wifi_settings.wifi_ssid,
           strnlen(wifi_settings.wifi_ssid, sizeof(config.sta.ssid)));
    memcpy(config.sta.password, wifi_settings.wifi_password,
           strnlen(wifi_settings.wifi_password, sizeof(config.sta.password)));
    /* Mesh networks must be free to choose and roam between their nodes.
       Pinning a station to a scanned BSSID can make the controller ignore
       authentication even though the SSID and password are correct. */
    config.sta.scan_method = WIFI_ALL_CHANNEL_SCAN;
    config.sta.sort_method = WIFI_CONNECT_AP_BY_SIGNAL;
    config.sta.failure_retry_cnt = 0;
    config.sta.bssid_set = false;
    config.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    config.sta.pmf_cfg.capable = true;
    config.sta.pmf_cfg.required = false;
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &config));
}

static bool wifi_try_network(void)
{
    wifi_configure_network();
    xEventGroupClearBits(wifi_events, CONNECTED | WIFI_ATTEMPT_FAILED);
    ESP_LOGI(TAG, "Connecting by SSID and allowing the mesh to select a node");
    if (esp_wifi_connect() != ESP_OK) return false;

    EventBits_t bits = xEventGroupWaitBits(
        wifi_events, CONNECTED | WIFI_ATTEMPT_FAILED,
        pdFALSE, pdFALSE, pdMS_TO_TICKS(WIFI_CONNECT_TIMEOUT_MS));
    if (bits & CONNECTED) return true;
    if (!(bits & WIFI_ATTEMPT_FAILED)) {
        ESP_LOGW(TAG, "Wi-Fi connection timed out");
        esp_wifi_disconnect();
        xEventGroupWaitBits(wifi_events, WIFI_ATTEMPT_FAILED,
                            pdTRUE, pdTRUE, pdMS_TO_TICKS(1000));
    } else {
        xEventGroupClearBits(wifi_events, WIFI_ATTEMPT_FAILED);
    }
    return false;
}

static void wifi_connection_manager(void *arg)
{
    (void)arg;
    xEventGroupWaitBits(wifi_events, WIFI_STARTED,
                        pdFALSE, pdTRUE, portMAX_DELAY);
    uint32_t retry_delay_ms = WIFI_RESCAN_DELAY_MIN_MS;
    while (true) {
        wifi_scan_config_t scan = {
            .ssid = (uint8_t *)wifi_settings.wifi_ssid,
            .show_hidden = true,
        };
        esp_err_t result = esp_wifi_scan_start(&scan, true);
        if (result != ESP_OK) {
            ESP_LOGW(TAG, "Wi-Fi scan failed: %s", esp_err_to_name(result));
            vTaskDelay(pdMS_TO_TICKS(retry_delay_ms));
            retry_delay_ms = retry_delay_ms < WIFI_RESCAN_DELAY_MAX_MS / 2
                                 ? retry_delay_ms * 2
                                 : WIFI_RESCAN_DELAY_MAX_MS;
            continue;
        }

        wifi_ap_record_t candidates[WIFI_MAX_CANDIDATES] = {0};
        uint16_t count = WIFI_MAX_CANDIDATES;
        result = esp_wifi_scan_get_ap_records(&count, candidates);
        if (result != ESP_OK || count == 0) {
            ESP_LOGW(TAG, "Configured Wi-Fi is not visible; rescanning");
            vTaskDelay(pdMS_TO_TICKS(retry_delay_ms));
            retry_delay_ms = retry_delay_ms < WIFI_RESCAN_DELAY_MAX_MS / 2
                                 ? retry_delay_ms * 2
                                 : WIFI_RESCAN_DELAY_MAX_MS;
            continue;
        }

        ESP_LOGI(TAG, "Found %u Wi-Fi node(s) for configured SSID", count);
        for (uint16_t index = 0; index < count; index++) {
            ESP_LOGI(TAG,
                     "Available node %02x:%02x:%02x:%02x:%02x:%02x, "
                     "channel=%u, RSSI=%d dBm, security=%s (%d)",
                     candidates[index].bssid[0], candidates[index].bssid[1],
                     candidates[index].bssid[2], candidates[index].bssid[3],
                     candidates[index].bssid[4], candidates[index].bssid[5],
                     candidates[index].primary, candidates[index].rssi,
                     wifi_auth_name(candidates[index].authmode),
                     candidates[index].authmode);
        }
        bool connected = wifi_try_network();

        if (!connected) {
            ESP_LOGW(TAG, "Wi-Fi connection failed; retrying in %lu seconds",
                     (unsigned long)(retry_delay_ms / 1000));
            vTaskDelay(pdMS_TO_TICKS(retry_delay_ms));
            retry_delay_ms = retry_delay_ms < WIFI_RESCAN_DELAY_MAX_MS / 2
                                 ? retry_delay_ms * 2
                                 : WIFI_RESCAN_DELAY_MAX_MS;
            continue;
        }

        retry_delay_ms = WIFI_RESCAN_DELAY_MIN_MS;

        /* Stay idle while the selected node works.  A disconnect wakes this
           task and causes a fresh scan, so changed mesh topology is handled. */
        xEventGroupWaitBits(wifi_events, WIFI_ATTEMPT_FAILED,
                            pdTRUE, pdTRUE, portMAX_DELAY);
    }
}

static void wifi_init(const device_settings_t *settings)
{
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();
    wifi_events = xEventGroupCreate();
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event, NULL));
    wifi_settings = *settings;
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(xTaskCreate(wifi_connection_manager, "wifi_manager", 4096,
                                NULL, 5, NULL) == pdPASS ? ESP_OK : ESP_ERR_NO_MEM);
}
#endif

#if CONFIG_FELICITY_EMULATOR_LIVE_API
static EventGroupHandle_t ethernet_events;
static const int ETHERNET_CONNECTED = BIT0;

static void ethernet_ip_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg; (void)data;
    if (base == IP_EVENT && id == IP_EVENT_ETH_GOT_IP) {
        xEventGroupSetBits(ethernet_events, ETHERNET_CONNECTED);
    }
}

static void ethernet_init(void)
{
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    ethernet_events = xEventGroupCreate();

    eth_mac_config_t mac_config = ETH_MAC_DEFAULT_CONFIG();
    eth_phy_config_t phy_config = ETH_PHY_DEFAULT_CONFIG();
    phy_config.autonego_timeout_ms = 100;
    esp_eth_mac_t *mac = esp_eth_mac_new_openeth(&mac_config);
    esp_eth_phy_t *phy = esp_eth_phy_new_generic(&phy_config);
    ESP_ERROR_CHECK(mac && phy ? ESP_OK : ESP_ERR_NO_MEM);

    esp_eth_handle_t ethernet = NULL;
    esp_eth_config_t config = ETH_DEFAULT_CONFIG(mac, phy);
    ESP_ERROR_CHECK(esp_eth_driver_install(&config, &ethernet));
    esp_netif_config_t netif_config = ESP_NETIF_DEFAULT_ETH();
    esp_netif_t *netif = esp_netif_new(&netif_config);
    ESP_ERROR_CHECK(netif ? ESP_OK : ESP_ERR_NO_MEM);
    ESP_ERROR_CHECK(esp_netif_attach(netif, esp_eth_new_netif_glue(ethernet)));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_ETH_GOT_IP,
                                               ethernet_ip_event, NULL));
    ESP_ERROR_CHECK(esp_eth_start(ethernet));
}
#endif

void app_main(void)
{
    esp_err_t nvs_result = nvs_flash_init();
    if (nvs_result == ESP_ERR_NVS_NO_FREE_PAGES ||
        nvs_result == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        nvs_result = nvs_flash_init();
    }
    ESP_ERROR_CHECK(nvs_result);
    device_settings_t settings;
    ESP_ERROR_CHECK(device_settings_load(&settings) ? ESP_OK : ESP_FAIL);
#if !CONFIG_FELICITY_EMULATOR
    setup_button_init();
    if (!settings.wifi_ssid[0]) wifi_provisioning_run(&settings);
#endif
    const char *api_base_url = settings.api_base_url;
    dashboard_page_t page = DASH_PAGE_HOME;
    dashboard_snapshot_t snapshot = {0};
    dashboard_summary_t summary = {0};
    dashboard_chart_t chart = {0};
    dashboard_gaps_t gaps = {0};
    bool gaps_live = false;
    nextion_data_state_t current_state = NEXTION_DATA_NONE;
    nextion_data_state_t summary_state = NEXTION_DATA_NONE;
    nextion_data_state_t gaps_state = NEXTION_DATA_NONE;
#if !CONFIG_FELICITY_NEXTION_TCP_BRIDGE
    nextion_init();
    nextion_show_page(page);
#endif

#if CONFIG_FELICITY_EMULATOR_LIVE_API
    ethernet_init();
    ESP_LOGI(TAG, "Waiting for QEMU Ethernet");
    xEventGroupWaitBits(ethernet_events, ETHERNET_CONNECTED, pdFALSE, pdTRUE, portMAX_DELAY);
    ESP_LOGI(TAG, "QEMU Ethernet ready; API: %s", api_base_url);
#elif FELICITY_DEMO_MODE
    dashboard_sample_snapshot(&snapshot);
    dashboard_sample_summary(&summary);
    ESP_LOGI(TAG, "ESP32-C3 emulator mode; using deterministic Raspberry sample");
#else
    wifi_init(&settings);
#if CONFIG_FELICITY_OFFLINE_DEMO
    ESP_LOGW(TAG, "Offline demo enabled; Wi-Fi will connect in the background");
#else
    ESP_LOGI(TAG, "Waiting for configured Wi-Fi");
    xEventGroupWaitBits(wifi_events, CONNECTED, pdFALSE, pdTRUE, portMAX_DELAY);
    ESP_LOGI(TAG, "Wi-Fi connected; API: %s", api_base_url);
#endif
#endif

#if !CONFIG_FELICITY_EMULATOR
    clock_init();
#else
    /* QEMU inherits a usable RTC; only the local timezone is needed. */
    setenv("TZ", CONFIG_FELICITY_TIMEZONE, 1);
    tzset();
#endif

#if CONFIG_FELICITY_NEXTION_TCP_BRIDGE
    /* lwIP must be online before the temporary test server is created. */
    nextion_init();
    nextion_show_page(page);
#endif

    TickType_t next_poll = 0;
    TickType_t next_summary = 0;
    TickType_t next_chart = 0;
    TickType_t next_clock = 0;
    bool summary_live = false;
#if CONFIG_FELICITY_EMULATOR && !CONFIG_FELICITY_EMULATOR_UART_BRIDGE
    TickType_t next_demo_page = pdMS_TO_TICKS(5000);
#endif
    while (true) {
        TickType_t now = xTaskGetTickCount();
#if CONFIG_FELICITY_EMULATOR && !CONFIG_FELICITY_EMULATOR_UART_BRIDGE
        if (now >= next_demo_page) {
            page = page >= DASH_PAGE_GAPS ? DASH_PAGE_HOME : (dashboard_page_t)(page + 1);
            ESP_LOGI(TAG, "Demo navigation: %s", touch_page_name(page));
            nextion_show_page(page);
            next_poll = 0;
            next_chart = 0;
            next_clock = 0;
            if (page == DASH_PAGE_GAPS) gaps_live = false;
            next_demo_page = now + pdMS_TO_TICKS(5000);
        }
#endif
        nextion_event_t nextion_event = nextion_read_event(&page);
        if (nextion_event != NEXTION_EVENT_NONE) {
            if (nextion_event == NEXTION_EVENT_DISPLAY_READY) {
                ESP_LOGI(TAG, "Nextion restarted; restoring %s", touch_page_name(page));
            } else {
                ESP_LOGI(TAG, "Touch navigation: %s", touch_page_name(page));
            }
            nextion_show_page(page);
            next_poll = 0;
            next_chart = 0;
            next_clock = 0;
            if (page == DASH_PAGE_GAPS) gaps_live = false;
        }
        if (now >= next_clock) {
            nextion_render_clock();
            next_clock = now + pdMS_TO_TICKS(1000);
        }
        if (now >= next_summary) {
#if FELICITY_DEMO_MODE
            dashboard_sample_summary(&summary);
            summary_live = true;
            summary_state = NEXTION_DATA_DEMO;
#else
            summary_live = dashboard_fetch_summary(api_base_url, &summary);
            summary_state = summary_live ? NEXTION_DATA_LIVE : NEXTION_DATA_NONE;
#if CONFIG_FELICITY_OFFLINE_DEMO
            if (!summary_live) {
                dashboard_sample_summary(&summary);
                summary_state = NEXTION_DATA_DEMO;
            }
#endif
#endif
            if (page == DASH_PAGE_HOME || page == DASH_PAGE_SYSTEM || page == DASH_PAGE_TODAY) {
                next_poll = 0;
            }
            next_summary = now + pdMS_TO_TICKS(60000);
        }
        if (now >= next_poll) {
            if (page == DASH_PAGE_GAPS) {
                if (gaps_state != NEXTION_DATA_NONE) nextion_render_gaps(&gaps, gaps_state);
                next_poll = now + pdMS_TO_TICKS(2000);
            } else if (page == DASH_PAGE_SYSTEM || page == DASH_PAGE_TODAY) {
                nextion_render_detail(page, &snapshot, &summary, summary_state);
                next_poll = now + pdMS_TO_TICKS(2000);
            } else {
#if FELICITY_DEMO_MODE
                current_state = NEXTION_DATA_DEMO;
#else
                bool live = dashboard_fetch_current(api_base_url, &snapshot);
                current_state = live ? NEXTION_DATA_LIVE : NEXTION_DATA_NONE;
#if CONFIG_FELICITY_OFFLINE_DEMO
                if (!live) {
                    dashboard_sample_snapshot(&snapshot);
                    current_state = NEXTION_DATA_DEMO;
                }
#endif
#endif
                if (page == DASH_PAGE_HOME) nextion_render_home(&snapshot, &summary, current_state);
                else nextion_render_detail(page, &snapshot, &summary, current_state);
                next_poll = now + pdMS_TO_TICKS(2000);
            }
        }
        if (page >= DASH_PAGE_PV && page <= DASH_PAGE_GAPS && now >= next_chart) {
            if (page == DASH_PAGE_GAPS) {
#if FELICITY_DEMO_MODE
                dashboard_sample_gaps(&gaps);
                gaps_live = true;
                gaps_state = NEXTION_DATA_DEMO;
#else
                gaps_live = dashboard_fetch_gaps(api_base_url, &gaps);
                gaps_state = gaps_live ? NEXTION_DATA_LIVE : NEXTION_DATA_NONE;
#if CONFIG_FELICITY_OFFLINE_DEMO
                if (!gaps_live) {
                    dashboard_sample_gaps(&gaps);
                    gaps_state = NEXTION_DATA_DEMO;
                }
#endif
#endif
                nextion_render_gaps(&gaps, gaps_state);
                if (gaps_state != NEXTION_DATA_NONE) nextion_render_chart(page, &gaps.chart);
                next_chart = now + pdMS_TO_TICKS(60000);
                vTaskDelay(pdMS_TO_TICKS(20));
                continue;
            }
            const char *metric = touch_page_name(page);
#if FELICITY_DEMO_MODE
            dashboard_sample_chart(metric, &chart);
            bool chart_ok = true;
#else
            bool chart_ok = dashboard_fetch_chart(api_base_url, metric, &chart);
#if CONFIG_FELICITY_OFFLINE_DEMO
            if (!chart_ok) {
                dashboard_sample_chart(metric, &chart);
                chart_ok = true;
            }
#endif
#endif
            if (chart_ok) nextion_render_chart(page, &chart);
            next_chart = now + pdMS_TO_TICKS(page == DASH_PAGE_SYSTEM ? 10000 : 60000);
        }
        /* Keep live values and touch responsive while a large daily chart is
           replayed.  At most two sample columns are queued per loop. */
        nextion_advance_chart(page, 2);
        vTaskDelay(pdMS_TO_TICKS(20));
    }
}
