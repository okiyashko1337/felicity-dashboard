#include <string.h>

#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "nvs_flash.h"
#include "sdkconfig.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"

#include "dashboard_data.h"
#include "nextion.h"

static const char *TAG = "felicity";
#if !CONFIG_FELICITY_EMULATOR
static EventGroupHandle_t wifi_events;
static const int CONNECTED = BIT0;

static void wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg; (void)data;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) esp_wifi_connect();
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        xEventGroupClearBits(wifi_events, CONNECTED);
        esp_wifi_connect();
    }
    if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) xEventGroupSetBits(wifi_events, CONNECTED);
}

static void wifi_init(void)
{
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();
    wifi_events = xEventGroupCreate();
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event, NULL));
    wifi_config_t config = {0};
    snprintf((char *)config.sta.ssid, sizeof(config.sta.ssid), "%s", CONFIG_FELICITY_WIFI_SSID);
    snprintf((char *)config.sta.password, sizeof(config.sta.password), "%s", CONFIG_FELICITY_WIFI_PASSWORD);
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &config));
    ESP_ERROR_CHECK(esp_wifi_start());
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
    nextion_init();
    dashboard_page_t page = DASH_PAGE_HOME;
    dashboard_snapshot_t snapshot = {0};
    dashboard_chart_t chart = {0};
    nextion_show_page(page);

#if CONFIG_FELICITY_EMULATOR
    dashboard_sample_snapshot(&snapshot);
    ESP_LOGI(TAG, "ESP32-C3 emulator mode; using deterministic Raspberry sample");
#else
    wifi_init();
    ESP_LOGI(TAG, "Waiting for Wi-Fi: %s", CONFIG_FELICITY_WIFI_SSID);
    xEventGroupWaitBits(wifi_events, CONNECTED, pdFALSE, pdTRUE, portMAX_DELAY);
#endif

    TickType_t next_poll = 0;
    TickType_t next_chart = 0;
#if CONFIG_FELICITY_EMULATOR
    TickType_t next_demo_page = pdMS_TO_TICKS(5000);
#endif
    while (true) {
        TickType_t now = xTaskGetTickCount();
#if CONFIG_FELICITY_EMULATOR
        if (now >= next_demo_page) {
            page = page >= DASH_PAGE_TODAY ? DASH_PAGE_HOME : (dashboard_page_t)(page + 1);
            ESP_LOGI(TAG, "Demo navigation: %s", touch_page_name(page));
            nextion_show_page(page);
            next_poll = 0;
            next_chart = 0;
            next_demo_page = now + pdMS_TO_TICKS(5000);
        }
#endif
        if (nextion_read_page_change(&page)) {
            ESP_LOGI(TAG, "Touch navigation: %s", touch_page_name(page));
            nextion_show_page(page);
            next_poll = 0;
            next_chart = 0;
        }
        if (now >= next_poll) {
#if CONFIG_FELICITY_EMULATOR
            bool live = true;
#else
            bool live = dashboard_fetch_current(CONFIG_FELICITY_API_BASE_URL, &snapshot);
#endif
            if (page == DASH_PAGE_HOME) nextion_render_home(&snapshot, live);
            else nextion_render_detail(page, &snapshot, live);
            next_poll = now + pdMS_TO_TICKS(2000);
        }
        if (page >= DASH_PAGE_PV && page <= DASH_PAGE_TODAY && now >= next_chart) {
            const char *metric = touch_page_name(page);
#if CONFIG_FELICITY_EMULATOR
            dashboard_sample_chart(metric, &chart);
            bool chart_ok = true;
#else
            bool chart_ok = dashboard_fetch_chart(CONFIG_FELICITY_API_BASE_URL, metric, &chart);
#endif
            if (chart_ok) nextion_render_chart(page, &chart);
            next_chart = now + pdMS_TO_TICKS(30000);
        }
        vTaskDelay(pdMS_TO_TICKS(20));
    }
}
